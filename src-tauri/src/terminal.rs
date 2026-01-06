#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::{
    collections::HashMap,
    fs::{create_dir_all, File, OpenOptions},
    io::{BufRead, BufReader, Read, Seek, SeekFrom, Write},
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Arc, Mutex,
    },
    time::{SystemTime, UNIX_EPOCH},
};

use dirs::home_dir;
use portable_pty::{native_pty_system, CommandBuilder, MasterPty, PtySize};
use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager};
use tokio::sync::Mutex as AsyncMutex;

use crate::{
    config::load_config,
    error::AppError,
    ssh::{ensure_bin, SshSpec},
    vast::VastClient,
};

#[derive(Debug, Clone, Serialize)]
pub struct TermSessionInfo {
    pub id: String,
    pub title: String,
}

#[derive(Clone)]
struct TermHandle {
    title: String,
    master: Arc<Mutex<Box<dyn MasterPty + Send>>>,
    writer: Arc<Mutex<Box<dyn Write + Send>>>,
    child: Arc<Mutex<Box<dyn portable_pty::Child + Send + Sync>>>,
    /// Shared output buffer for command completion detection
    output_buffer: Arc<std::sync::RwLock<String>>,
    history: Arc<TermHistory>,
}

/// Maximum size of output buffer (1MB)
const OUTPUT_BUFFER_MAX_SIZE: usize = 1024 * 1024;
/// PTY read buffer size (larger reads reduce syscalls)
const READ_BUFFER_SIZE: usize = 64 * 1024;
/// tmux history limit for remote sessions (lines)
const TMUX_HISTORY_LIMIT: usize = 200000;

#[derive(Default)]
pub struct TerminalManager {
    sessions: AsyncMutex<HashMap<String, TermHandle>>,
}

#[derive(Debug, Clone, Serialize)]
struct TermDataEvent {
    id: String,
    data: String,
}

#[derive(Debug, Clone, Serialize)]
struct TermExitEvent {
    id: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TermHistoryInfo {
    pub size_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct TermHistoryChunk {
    pub offset: u64,
    pub data: String,
    pub eof: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TermHistoryStep {
    pub step_id: String,
    pub step_index: usize,
    pub start_offset: u64,
    pub end_offset: u64,
    pub started_at: u64,
    pub ended_at: u64,
    pub status: String,
    pub exit_code: Option<i32>,
}

struct StepStart {
    step_index: usize,
    start_offset: u64,
    started_at: u64,
}

pub(crate) struct TermHistory {
    log_path: PathBuf,
    steps_path: PathBuf,
    writer: Mutex<File>,
    steps_writer: Mutex<File>,
    bytes_written: AtomicU64,
    step_starts: Mutex<HashMap<String, StepStart>>,
}

const HISTORY_CHUNK_LIMIT: usize = 256 * 1024;

impl TermHistory {
    fn new(app: &tauri::AppHandle, id: &str) -> Result<Self, AppError> {
        let base_dir = app
            .path()
            .app_data_dir()
            .map_err(|e| AppError::io(format!("history app_data_dir failed: {e}")))?;
        let history_dir = base_dir.join("terminal_history");
        create_dir_all(&history_dir)
            .map_err(|e| AppError::io(format!("history create dir failed: {e}")))?;

        let log_path = history_dir.join(format!("{id}.log"));
        let steps_path = history_dir.join(format!("{id}.steps.jsonl"));
        let writer = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|e| AppError::io(format!("history open log failed: {e}")))?;
        let steps_writer = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&steps_path)
            .map_err(|e| AppError::io(format!("history open steps failed: {e}")))?;
        let size = writer
            .metadata()
            .map_err(|e| AppError::io(format!("history metadata failed: {e}")))?
            .len();

        Ok(Self {
            log_path,
            steps_path,
            writer: Mutex::new(writer),
            steps_writer: Mutex::new(steps_writer),
            bytes_written: AtomicU64::new(size),
            step_starts: Mutex::new(HashMap::new()),
        })
    }

    fn now_millis() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64
    }

    fn size(&self) -> u64 {
        self.bytes_written.load(Ordering::Relaxed)
    }

    fn append_output(&self, data: &str) -> Result<(), AppError> {
        if data.is_empty() {
            return Ok(());
        }
        let mut file = self
            .writer
            .lock()
            .map_err(|_| AppError::io("history writer lock poisoned"))?;
        file.write_all(data.as_bytes())
            .map_err(|e| AppError::io(format!("history write failed: {e}")))?;
        self.bytes_written
            .fetch_add(data.as_bytes().len() as u64, Ordering::Relaxed);
        Ok(())
    }

    fn record_step_start(&self, step_id: &str, step_index: usize) -> Result<(), AppError> {
        let start_offset = self.bytes_written.load(Ordering::Relaxed);
        let started_at = Self::now_millis();
        let mut map = self
            .step_starts
            .lock()
            .map_err(|_| AppError::io("history step lock poisoned"))?;
        map.insert(
            step_id.to_string(),
            StepStart {
                step_index,
                start_offset,
                started_at,
            },
        );
        Ok(())
    }

    fn record_step_end(
        &self,
        step_id: &str,
        step_index: usize,
        status: &str,
        exit_code: Option<i32>,
    ) -> Result<(), AppError> {
        let end_offset = self.bytes_written.load(Ordering::Relaxed);
        let ended_at = Self::now_millis();
        let mut map = self
            .step_starts
            .lock()
            .map_err(|_| AppError::io("history step lock poisoned"))?;
        let start = map.remove(step_id).unwrap_or(StepStart {
            step_index,
            start_offset: end_offset,
            started_at: ended_at,
        });
        let record = TermHistoryStep {
            step_id: step_id.to_string(),
            step_index: start.step_index,
            start_offset: start.start_offset,
            end_offset,
            started_at: start.started_at,
            ended_at,
            status: status.to_string(),
            exit_code,
        };
        let mut file = self
            .steps_writer
            .lock()
            .map_err(|_| AppError::io("history steps writer lock poisoned"))?;
        let line = serde_json::to_string(&record)
            .map_err(|e| AppError::io(format!("history steps serialize failed: {e}")))?;
        file.write_all(line.as_bytes())
            .map_err(|e| AppError::io(format!("history steps write failed: {e}")))?;
        file.write_all(b"\n")
            .map_err(|e| AppError::io(format!("history steps newline failed: {e}")))?;
        Ok(())
    }

    fn read_range(&self, offset: u64, limit: usize) -> Result<TermHistoryChunk, AppError> {
        if limit == 0 {
            return Ok(TermHistoryChunk {
                offset,
                data: String::new(),
                eof: true,
            });
        }
        let mut file = File::open(&self.log_path)
            .map_err(|e| AppError::io(format!("history open log failed: {e}")))?;
        let size = file
            .metadata()
            .map_err(|e| AppError::io(format!("history metadata failed: {e}")))?
            .len();
        if size == 0 {
            return Ok(TermHistoryChunk {
                offset: 0,
                data: String::new(),
                eof: true,
            });
        }
        let offset = offset.min(size);
        let limit = limit.min(HISTORY_CHUNK_LIMIT);
        let remaining = (size - offset) as usize;
        let to_read = limit.min(remaining);
        file.seek(SeekFrom::Start(offset))
            .map_err(|e| AppError::io(format!("history seek failed: {e}")))?;
        let mut buf = vec![0u8; to_read];
        let n = file
            .read(&mut buf)
            .map_err(|e| AppError::io(format!("history read failed: {e}")))?;
        let data = String::from_utf8_lossy(&buf[..n]).to_string();
        Ok(TermHistoryChunk {
            offset,
            data,
            eof: offset + n as u64 >= size,
        })
    }

    fn read_tail(&self, limit: usize) -> Result<TermHistoryChunk, AppError> {
        let size = self.size();
        let limit = limit.min(HISTORY_CHUNK_LIMIT);
        let start = size.saturating_sub(limit as u64);
        self.read_range(start, limit)
    }

    fn list_steps(&self) -> Result<Vec<TermHistoryStep>, AppError> {
        if !self.steps_path.exists() {
            return Ok(Vec::new());
        }
        let file = File::open(&self.steps_path)
            .map_err(|e| AppError::io(format!("history open steps failed: {e}")))?;
        let reader = BufReader::new(file);
        let mut steps = Vec::new();
        for line in reader.lines() {
            let line = match line {
                Ok(line) => line,
                Err(e) => {
                    eprintln!("[Terminal] history step read failed: {e}");
                    continue;
                }
            };
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            match serde_json::from_str::<TermHistoryStep>(trimmed) {
                Ok(step) => steps.push(step),
                Err(e) => eprintln!("[Terminal] history step parse failed: {e}"),
            }
        }
        steps.sort_by_key(|step| step.step_index);
        Ok(steps)
    }
}

fn append_output_buffer(buf: &mut String, chunk: &str) {
    buf.push_str(chunk);
    if buf.len() <= OUTPUT_BUFFER_MAX_SIZE {
        return;
    }

    let trim_at = buf.len() / 2;
    let trim_at = buf
        .char_indices()
        .find(|(i, _)| *i >= trim_at)
        .map(|(i, _)| i)
        .unwrap_or(buf.len());
    if trim_at > 0 {
        buf.drain(..trim_at);
    }
}

fn emit_chunk(
    app_handle: &tauri::AppHandle,
    id: &str,
    output_buf: &Arc<std::sync::RwLock<String>>,
    history: &TermHistory,
    chunk: String,
) {
    if let Ok(mut obuf) = output_buf.write() {
        append_output_buffer(&mut obuf, &chunk);
    }
    if let Err(e) = history.append_output(&chunk) {
        eprintln!("[Terminal] history append failed for {}: {}", id, e);
    }

    let _ = app_handle.emit(
        "term:data",
        TermDataEvent {
            id: id.to_string(),
            data: chunk,
        },
    );
}

fn spawn_pty_reader(
    mut reader: Box<dyn Read + Send>,
    app_handle: tauri::AppHandle,
    id_data: String,
    output_buf: Arc<std::sync::RwLock<String>>,
    history: Arc<TermHistory>,
    label: &'static str,
) {
    std::thread::spawn(move || {
        let mut buf = vec![0u8; READ_BUFFER_SIZE];

        loop {
            let n = match reader.read(&mut buf) {
                Ok(0) => {
                    eprintln!("[Terminal] {} PTY EOF for {}", label, id_data);
                    break;
                }
                Ok(n) => n,
                Err(e) => {
                    eprintln!("[Terminal] {} PTY read error for {}: {}", label, id_data, e);
                    break;
                }
            };

            // Emit immediately - no buffering or throttling for maximum responsiveness
            let chunk = String::from_utf8_lossy(&buf[..n]).to_string();
            emit_chunk(&app_handle, &id_data, &output_buf, &history, chunk);
        }

        eprintln!("[Terminal] Emitting term:exit for {}", id_data);
        let _ = app_handle.emit("term:exit", TermExitEvent { id: id_data });
    });
}

impl TerminalManager {
    pub async fn list(&self) -> Vec<TermSessionInfo> {
        let map = self.sessions.lock().await;
        map.iter()
            .map(|(id, h)| TermSessionInfo {
                id: id.clone(),
                title: h.title.clone(),
            })
            .collect()
    }

    async fn insert(&self, id: String, handle: TermHandle) {
        let mut map = self.sessions.lock().await;
        map.insert(id, handle);
    }

    async fn get(&self, id: &str) -> Option<TermHandle> {
        let map = self.sessions.lock().await;
        map.get(id).cloned()
    }

    pub(crate) async fn history(&self, id: &str) -> Option<Arc<TermHistory>> {
        let map = self.sessions.lock().await;
        map.get(id).map(|h| h.history.clone())
    }

    async fn remove(&self, id: &str) -> Option<TermHandle> {
        let mut map = self.sessions.lock().await;
        map.remove(id)
    }

    /// Get the current output buffer content
    pub async fn get_output(&self, id: &str) -> Option<String> {
        let map = self.sessions.lock().await;
        map.get(id)
            .and_then(|h| h.output_buffer.read().ok().map(|b| b.clone()))
    }

    /// Get the length of the output buffer
    pub async fn get_output_len(&self, id: &str) -> Option<usize> {
        let map = self.sessions.lock().await;
        map.get(id)
            .and_then(|h| h.output_buffer.read().ok().map(|b| b.len()))
    }
}

async fn history_for(mgr: &TerminalManager, id: &str) -> Result<Arc<TermHistory>, AppError> {
    mgr.history(id)
        .await
        .ok_or_else(|| AppError::invalid_input(format!("Unknown terminal session: {id}")))
}

pub(crate) async fn history_step_start(
    mgr: &TerminalManager,
    id: &str,
    step_id: &str,
    step_index: usize,
) -> Result<(), AppError> {
    let history = history_for(mgr, id).await?;
    history.record_step_start(step_id, step_index)
}

pub(crate) async fn history_step_end(
    mgr: &TerminalManager,
    id: &str,
    step_id: &str,
    step_index: usize,
    status: &str,
    exit_code: Option<i32>,
) -> Result<(), AppError> {
    let history = history_for(mgr, id).await?;
    history.record_step_end(step_id, step_index, status, exit_code)
}

pub(crate) async fn history_size_bytes(mgr: &TerminalManager, id: &str) -> Result<u64, AppError> {
    let history = history_for(mgr, id).await?;
    Ok(history.size())
}

pub(crate) async fn history_read_range(
    mgr: &TerminalManager,
    id: &str,
    offset: u64,
    limit: usize,
) -> Result<TermHistoryChunk, AppError> {
    let history = history_for(mgr, id).await?;
    tokio::task::spawn_blocking(move || history.read_range(offset, limit))
        .await
        .map_err(|e| AppError::io(e.to_string()))?
}

/// Simple wait for a marker string in terminal output
/// Waits indefinitely until marker is found at the start of a line
/// This avoids false positives from heredoc echo like "echo '___DOPPIO_DONE___'"
pub async fn wait_for_marker(mgr: &TerminalManager, term_id: &str, marker: &str) {
    let poll_interval = std::time::Duration::from_millis(100);

    // Get initial output length to only search new output
    let initial_len = mgr.get_output_len(term_id).await.unwrap_or(0);

    // Marker must appear at line start (after \n or \r\n) to distinguish
    // actual command output from heredoc echo like "echo '___DOPPIO_DONE___'"
    let marker_with_newline = format!("\n{}", marker);

    loop {
        tokio::time::sleep(poll_interval).await;

        // Check for marker in output
        if let Some(output) = mgr.get_output(term_id).await {
            if output.len() > initial_len {
                let new_output = &output[initial_len..];
                // Check for marker at line start (after newline)
                if new_output.contains(&marker_with_newline) {
                    return;
                }
                // Also check if new_output starts with marker (rare edge case)
                if new_output.starts_with(marker) {
                    return;
                }
            }
        }
    }
}

/// Wait for marker with exit code in format "MARKER:CODE"
/// Returns the exit code (0 if parsing fails)
pub async fn wait_for_marker_with_exit_code(
    mgr: &TerminalManager,
    term_id: &str,
    marker: &str,
) -> i32 {
    let poll_interval = std::time::Duration::from_millis(100);

    // Get initial output length to only search new output
    let initial_len = mgr.get_output_len(term_id).await.unwrap_or(0);

    // Pattern: MARKER:CODE (e.g., ___DOPPIO_DONE___:0)
    let marker_prefix = format!("{}:", marker);

    loop {
        tokio::time::sleep(poll_interval).await;

        // Check for marker in output
        if let Some(output) = mgr.get_output(term_id).await {
            if output.len() > initial_len {
                let new_output = &output[initial_len..];

                // Look for marker:code pattern
                for line in new_output.lines() {
                    let line = line.trim();
                    if line.starts_with(&marker_prefix) {
                        // Extract exit code
                        let code_str = &line[marker_prefix.len()..];
                        return code_str.parse().unwrap_or(0);
                    }
                }

                // Also check with \r\n line endings
                for line in new_output.split("\r\n") {
                    let line = line.trim();
                    if line.starts_with(&marker_prefix) {
                        let code_str = &line[marker_prefix.len()..];
                        return code_str.parse().unwrap_or(0);
                    }
                }
            }
        }
    }
}

/// Wait for OSC 133 D prompt marker which indicates command completion
/// The marker format is: ESC ] 133 ; D ; <exit_code> BEL
/// Returns (found, exit_code)
pub async fn wait_for_prompt_marker(
    mgr: &TerminalManager,
    term_id: &str,
    marker_prefix: &str, // "\x1b]133;D;"
    marker_suffix: &str, // "\x07"
    timeout: std::time::Duration,
) -> (bool, Option<i32>) {
    let start = std::time::Instant::now();
    let poll_interval = std::time::Duration::from_millis(50);

    // Get initial output length to only search new output
    let initial_len = mgr.get_output_len(term_id).await.unwrap_or(0);
    let mut last_searched_pos = initial_len;

    eprintln!(
        "[wait_for_prompt_marker] Starting wait for term_id={}, initial_len={}",
        term_id, initial_len
    );

    loop {
        if start.elapsed() > timeout {
            eprintln!(
                "[wait_for_prompt_marker] TIMEOUT after {:?} for term_id={}",
                timeout, term_id
            );
            return (false, None);
        }

        tokio::time::sleep(poll_interval).await;

        // Check for marker in new output
        if let Some(output) = mgr.get_output(term_id).await {
            if output.len() > last_searched_pos {
                let search_area = &output[last_searched_pos..];

                // Look for the marker prefix
                if let Some(prefix_pos) = search_area.find(marker_prefix) {
                    let after_prefix = &search_area[prefix_pos + marker_prefix.len()..];

                    // Look for the suffix to find the end of the marker
                    if let Some(suffix_pos) = after_prefix.find(marker_suffix) {
                        // Extract exit code between prefix and suffix
                        let exit_code_str = &after_prefix[..suffix_pos];
                        eprintln!(
                            "[wait_for_prompt_marker] Raw exit code string: '{}'",
                            exit_code_str
                        );
                        let exit_code = exit_code_str.trim().parse::<i32>().ok();
                        eprintln!(
                            "[wait_for_prompt_marker] FOUND marker for term_id={}, exit_code={:?}",
                            term_id, exit_code
                        );
                        return (true, exit_code);
                    }
                }

                // Update search position (but leave some overlap for partial markers)
                if output.len() > marker_prefix.len() + 10 {
                    last_searched_pos = output.len() - marker_prefix.len() - 10;
                }

                // Log every 5 seconds to show we're still waiting
                if start.elapsed().as_secs() % 5 == 0 && start.elapsed().as_millis() % 5000 < 100 {
                    eprintln!(
                        "[wait_for_prompt_marker] Still waiting... elapsed={:?}, output_len={}",
                        start.elapsed(),
                        output.len()
                    );
                }
            }
        } else {
            eprintln!(
                "[wait_for_prompt_marker] No output buffer found for term_id={}",
                term_id
            );
        }
    }
}

async fn open_ssh_tmux_inner(
    app: tauri::AppHandle,
    mgr: tauri::State<'_, TerminalManager>,
    ssh: SshSpec,
    tmux_session: String,
    title: Option<String>,
    cols: u16,
    rows: u16,
    env_vars: Option<HashMap<String, String>>,
) -> Result<TermSessionInfo, AppError> {
    ensure_bin("ssh").await?;
    ssh.validate()?;

    let session = tmux_session.trim().to_string();
    if session.is_empty() {
        return Err(AppError::invalid_input("tmux_session is required"));
    }

    let title = title
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| format!("{} · tmux:{}", ssh.host, session));

    let id = uuid::Uuid::new_v4().to_string();

    // Create PTY.
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::io(format!("openpty failed: {e}")))?;

    // Build the SSH command - use shell to handle ProxyCommand with spaces correctly
    let ssh_opts = ssh.interactive_ssh_options();
    let target = ssh.target();

    // Build environment exports and remote command
    let env_exports = if let Some(vars) = &env_vars {
        if vars.is_empty() {
            String::new()
        } else {
            vars.iter()
                .map(|(k, v)| format!("export {}='{}'", k, v.replace("'", "'\\''")))
                .collect::<Vec<_>>()
                .join("; ")
                + "; "
        }
    } else {
        String::new()
    };

    // Enable tmux mouse mode for scroll support, and set high history limit
    let remote_cmd = format!(
        "{}tmux start-server; \
     tmux set-option -g history-limit {}; \
     tmux set-option -g mouse on; \
     tmux set-option -t {} history-limit {} 2>/dev/null; \
     tmux new-session -A -s {}",
        env_exports, TMUX_HISTORY_LIMIT, session, TMUX_HISTORY_LIMIT, session
    );

    // Check if we have a ProxyCommand in extra_args (needs special handling)
    let has_proxy_cmd = ssh.extra_args.iter().any(|a| a.contains("ProxyCommand="));

    // Create a temporary shell script to handle complex quoting
    let script_content = if has_proxy_cmd {
        // For cloudflared/ProxyCommand: use shell to handle complex quoting
        let mut cmd_parts = vec!["exec ssh".to_string()];
        for opt in &ssh_opts {
            // Quote options that contain spaces
            if opt.contains(' ') {
                cmd_parts.push(format!("'{}'", opt.replace("'", "'\\''")));
            } else {
                cmd_parts.push(opt.clone());
            }
        }
        cmd_parts.push("-tt".to_string());
        cmd_parts.push(target.clone());
        cmd_parts.push(format!("'{}'", remote_cmd));
        cmd_parts.join(" ")
    } else {
        // For regular SSH: still use script for consistency
        let mut cmd_parts = vec!["exec ssh".to_string()];
        for opt in &ssh_opts {
            cmd_parts.push(opt.clone());
        }
        cmd_parts.push("-tt".to_string());
        cmd_parts.push(target.clone());
        cmd_parts.push(format!("'{}'", remote_cmd));
        cmd_parts.join(" ")
    };

    // Write script to temp file
    let script_path = std::env::temp_dir().join(format!("doppio_ssh_{}.sh", uuid::Uuid::new_v4()));
    std::fs::write(&script_path, format!("#!/bin/bash\n{}\n", script_content))
        .map_err(|e| AppError::io(format!("Failed to write SSH script: {}", e)))?;
    #[cfg(unix)]
    std::fs::set_permissions(&script_path, std::fs::Permissions::from_mode(0o755))
        .map_err(|e| AppError::io(format!("Failed to set script permissions: {}", e)))?;

    let mut cmd = CommandBuilder::new(&script_path);
    // Set TERM environment variable for proper terminal support
    cmd.env("TERM", "xterm-256color");
    cmd.env("LANG", "en_US.UTF-8");
    cmd.env("LC_ALL", "en_US.UTF-8");
    // Clean up script after a delay (the process will have started by then)
    let script_path_clone = script_path.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(5));
        let _ = std::fs::remove_file(script_path_clone);
    });

    // Spawn SSH inside the PTY.
    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| AppError::command(format!("spawn ssh failed: {e}")))?;

    let reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| AppError::io(format!("clone pty reader failed: {e}")))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| AppError::io(format!("take pty writer failed: {e}")))?;

    let master = Arc::new(Mutex::new(pair.master));
    let writer = Arc::new(Mutex::new(writer));
    let child = Arc::new(Mutex::new(child));
    let output_buffer = Arc::new(std::sync::RwLock::new(String::new()));
    let history = Arc::new(TermHistory::new(&app, &id)?);

    mgr.insert(
        id.clone(),
        TermHandle {
            title: title.clone(),
            master: master.clone(),
            writer: writer.clone(),
            child: child.clone(),
            output_buffer: output_buffer.clone(),
            history: history.clone(),
        },
    )
    .await;

    // Reader loop (blocking thread)
    let app_handle = app.clone();
    let id_data = id.clone();
    spawn_pty_reader(
        reader,
        app_handle,
        id_data,
        output_buffer.clone(),
        history.clone(),
        "SSH",
    );

    Ok(TermSessionInfo { id, title })
}

#[tauri::command]
pub async fn term_list(
    mgr: tauri::State<'_, TerminalManager>,
) -> Result<Vec<TermSessionInfo>, AppError> {
    Ok(mgr.list().await)
}

#[tauri::command]
pub async fn term_history_info(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
) -> Result<TermHistoryInfo, AppError> {
    let history = history_for(&mgr, &id).await?;
    Ok(TermHistoryInfo {
        size_bytes: history.size(),
    })
}

#[tauri::command]
pub async fn term_history_range(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
    offset: u64,
    limit: usize,
) -> Result<TermHistoryChunk, AppError> {
    let history = history_for(&mgr, &id).await?;
    tokio::task::spawn_blocking(move || history.read_range(offset, limit))
        .await
        .map_err(|e| AppError::io(e.to_string()))?
}

#[tauri::command]
pub async fn term_history_tail(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
    limit: usize,
) -> Result<TermHistoryChunk, AppError> {
    let history = history_for(&mgr, &id).await?;
    tokio::task::spawn_blocking(move || history.read_tail(limit))
        .await
        .map_err(|e| AppError::io(e.to_string()))?
}

#[tauri::command]
pub async fn term_history_steps(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
) -> Result<Vec<TermHistoryStep>, AppError> {
    let history = history_for(&mgr, &id).await?;
    tokio::task::spawn_blocking(move || history.list_steps())
        .await
        .map_err(|e| AppError::io(e.to_string()))?
}

#[tauri::command]
#[allow(non_snake_case)]
pub async fn term_open_ssh_tmux(
    app: tauri::AppHandle,
    mgr: tauri::State<'_, TerminalManager>,
    ssh: SshSpec,
    tmuxSession: String,
    title: Option<String>,
    cols: Option<u16>,
    rows: Option<u16>,
    envVars: Option<HashMap<String, String>>,
) -> Result<TermSessionInfo, AppError> {
    open_ssh_tmux_inner(
        app,
        mgr,
        ssh,
        tmuxSession,
        title,
        cols.unwrap_or(80),
        rows.unwrap_or(24),
        envVars,
    )
    .await
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TermOpenInstanceTmuxInput {
    pub instance_id: i64,
    pub tmux_session: String,
    pub title: Option<String>,
    pub cols: Option<u16>,
    pub rows: Option<u16>,
}

#[tauri::command]
pub async fn term_open_instance_tmux(
    app: tauri::AppHandle,
    mgr: tauri::State<'_, TerminalManager>,
    input: TermOpenInstanceTmuxInput,
) -> Result<TermSessionInfo, AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    let insts = client.list_instances().await?;
    let inst = insts
        .into_iter()
        .find(|x| x.id == input.instance_id)
        .ok_or_else(|| {
            AppError::invalid_input(format!("Instance not found: {}", input.instance_id))
        })?;

    let host = inst.ssh_host.clone().unwrap_or_default().trim().to_string();
    let port = inst.ssh_port.unwrap_or(0);
    if host.is_empty() || port <= 0 {
        return Err(AppError::invalid_input(
            "Instance does not have SSH info yet (is it running and provisioned?)",
        ));
    }

    let ssh = SshSpec {
        host,
        port,
        user: cfg.vast.ssh_user.clone(),
        key_path: cfg.vast.ssh_key_path.clone(),
        extra_args: vec![],
    };

    // Use default Vast environment variables
    let env_vars = crate::host::default_env_vars(&crate::host::HostType::Vast);

    open_ssh_tmux_inner(
        app,
        mgr,
        ssh,
        input.tmux_session,
        input.title,
        input.cols.unwrap_or(80),
        input.rows.unwrap_or(24),
        Some(env_vars),
    )
    .await
}

#[tauri::command]
pub async fn term_write(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
    data: String,
) -> Result<(), AppError> {
    let Some(h) = mgr.get(&id).await else {
        return Err(AppError::invalid_input(format!(
            "Unknown terminal session: {id}"
        )));
    };

    tokio::task::spawn_blocking(move || {
        let mut w = h
            .writer
            .lock()
            .map_err(|_| AppError::io("terminal writer lock poisoned"))?;
        w.write_all(data.as_bytes())
            .map_err(|e| AppError::io(e.to_string()))?;
        w.flush().ok();
        Ok::<(), AppError>(())
    })
    .await
    .map_err(|e| AppError::io(e.to_string()))??;
    Ok(())
}

#[tauri::command]
pub async fn term_resize(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
    cols: u16,
    rows: u16,
) -> Result<(), AppError> {
    let Some(h) = mgr.get(&id).await else {
        return Err(AppError::invalid_input(format!(
            "Unknown terminal session: {id}"
        )));
    };

    tokio::task::spawn_blocking(move || {
        let m = h
            .master
            .lock()
            .map_err(|_| AppError::io("terminal master lock poisoned"))?;
        m.resize(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::io(e.to_string()))?;
        Ok::<(), AppError>(())
    })
    .await
    .map_err(|e| AppError::io(e.to_string()))??;
    Ok(())
}

/// Open a local terminal session (spawns the user's default shell)
#[tauri::command]
pub async fn term_open_local(
    app: tauri::AppHandle,
    mgr: tauri::State<'_, TerminalManager>,
    title: Option<String>,
    cols: Option<u16>,
    rows: Option<u16>,
) -> Result<TermSessionInfo, AppError> {
    open_local_inner(app, &mgr, title, cols.unwrap_or(80), rows.unwrap_or(24)).await
}

/// Inner function for opening a local terminal (can be called without State wrapper)
pub async fn open_local_inner(
    app: tauri::AppHandle,
    mgr: &TerminalManager,
    title: Option<String>,
    cols: u16,
    rows: u16,
) -> Result<TermSessionInfo, AppError> {
    let title = title
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "Local".to_string());

    let id = uuid::Uuid::new_v4().to_string();

    // Create PTY
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::io(format!("openpty failed: {e}")))?;

    // Determine the user's shell
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".to_string());
    let home = home_dir().unwrap_or_else(|| std::path::PathBuf::from("~"));
    let histfile = std::env::var("HISTFILE")
        .unwrap_or_else(|_| home.join(".zsh_history").display().to_string());
    let hist_size = std::env::var("HISTSIZE").unwrap_or_else(|_| "50000".to_string());
    let save_hist = std::env::var("SAVEHIST").unwrap_or_else(|_| "10000".to_string());

    let mut cmd = CommandBuilder::new(&shell);
    cmd.arg("-l"); // Login shell
    cmd.env("TERM", "xterm-256color");
    cmd.env("LANG", "en_US.UTF-8");
    cmd.env("LC_ALL", "en_US.UTF-8");
    cmd.env("HISTFILE", histfile);
    cmd.env("HISTSIZE", hist_size);
    cmd.env("SAVEHIST", save_hist);

    // Spawn shell inside the PTY
    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| AppError::io(format!("spawn shell failed: {e}")))?;

    let reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| AppError::io(format!("clone pty reader failed: {e}")))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| AppError::io(format!("take pty writer failed: {e}")))?;

    let master = Arc::new(Mutex::new(pair.master));
    let writer = Arc::new(Mutex::new(writer));
    let child = Arc::new(Mutex::new(child));
    let output_buffer = Arc::new(std::sync::RwLock::new(String::new()));
    let history = Arc::new(TermHistory::new(&app, &id)?);

    mgr.insert(
        id.clone(),
        TermHandle {
            title: title.clone(),
            master: master.clone(),
            writer: writer.clone(),
            child: child.clone(),
            output_buffer: output_buffer.clone(),
            history: history.clone(),
        },
    )
    .await;

    // Reader loop (blocking thread)
    let app_handle = app.clone();
    let id_data = id.clone();
    spawn_pty_reader(
        reader,
        app_handle,
        id_data,
        output_buffer.clone(),
        history.clone(),
        "Local",
    );

    Ok(TermSessionInfo { id, title })
}

#[tauri::command]
pub async fn term_close(
    mgr: tauri::State<'_, TerminalManager>,
    id: String,
) -> Result<(), AppError> {
    let Some(h) = mgr.remove(&id).await else {
        return Ok(());
    };
    tokio::task::spawn_blocking(move || {
        let mut c = h
            .child
            .lock()
            .map_err(|_| AppError::io("terminal child lock poisoned"))?;
        c.kill().ok();
        Ok::<(), AppError>(())
    })
    .await
    .ok();
    Ok(())
}

/// Open SSH connection in native system terminal (iTerm2/Terminal.app on macOS)
/// This is the simplest way to get a full-featured terminal for debugging
#[tauri::command]
pub async fn term_open_native_ssh(
    ssh: SshSpec,
    tmux_session: Option<String>,
) -> Result<(), AppError> {
    ensure_bin("ssh").await?;
    ssh.validate()?;

    // Build SSH command
    let mut ssh_args = ssh.common_ssh_options();
    ssh_args.push(ssh.target());

    // If tmux session is specified, attach or create
    let ssh_cmd = if let Some(session) = tmux_session.filter(|s| !s.trim().is_empty()) {
        format!(
            "ssh {} 'tmux attach -t {} 2>/dev/null || tmux new -s {}'",
            ssh_args.join(" "),
            session,
            session
        )
    } else {
        format!("ssh {}", ssh_args.join(" "))
    };

    // Detect and open in native terminal
    #[cfg(target_os = "macos")]
    {
        // Try iTerm2 first, fall back to Terminal.app
        let iterm_script = format!(
            r#"
      tell application "iTerm"
        activate
        set newWindow to (create window with default profile)
        tell current session of newWindow
          write text "{}"
        end tell
      end tell
      "#,
            ssh_cmd.replace('"', r#"\""#).replace('\'', r#"'"'"'"#)
        );

        let iterm_result = tokio::process::Command::new("osascript")
            .arg("-e")
            .arg(&iterm_script)
            .output()
            .await;

        if iterm_result.is_err() || !iterm_result.as_ref().unwrap().status.success() {
            // Fall back to Terminal.app
            let terminal_script = format!(
                r#"
        tell application "Terminal"
          activate
          do script "{}"
        end tell
        "#,
                ssh_cmd.replace('"', r#"\""#).replace('\'', r#"'"'"'"#)
            );

            tokio::process::Command::new("osascript")
                .arg("-e")
                .arg(&terminal_script)
                .output()
                .await
                .map_err(|e| AppError::command(format!("Failed to open terminal: {}", e)))?;
        }
    }

    #[cfg(target_os = "linux")]
    {
        // Try common Linux terminals in order
        let terminals = ["gnome-terminal", "konsole", "xfce4-terminal", "xterm"];
        let mut opened = false;

        for term in terminals {
            let result = match term {
                "gnome-terminal" => tokio::process::Command::new(term)
                    .args(["--", "bash", "-c", &ssh_cmd])
                    .spawn(),
                "konsole" | "xfce4-terminal" => tokio::process::Command::new(term)
                    .args(["-e", &ssh_cmd])
                    .spawn(),
                _ => tokio::process::Command::new(term)
                    .args(["-e", &ssh_cmd])
                    .spawn(),
            };

            if result.is_ok() {
                opened = true;
                break;
            }
        }

        if !opened {
            return Err(AppError::command(
                "No supported terminal emulator found".to_string(),
            ));
        }
    }

    #[cfg(target_os = "windows")]
    {
        // Use Windows Terminal or cmd
        tokio::process::Command::new("cmd")
            .args(["/c", "start", "ssh", &ssh_args.join(" ")])
            .spawn()
            .map_err(|e| AppError::command(format!("Failed to open terminal: {}", e)))?;
    }

    Ok(())
}

/// Quick open SSH in native terminal by host ID
#[tauri::command]
pub async fn term_open_host(host_id: String, tmux_session: Option<String>) -> Result<(), AppError> {
    let host = crate::host::get_host(&host_id).await?;
    let ssh = host
        .ssh
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    term_open_native_ssh(ssh, tmux_session).await
}

// ============================================================
// Helper functions for recipe interactive execution
// ============================================================

/// Static version of open_ssh_tmux_inner that works with State reference
pub async fn open_ssh_tmux_inner_static(
    app: tauri::AppHandle,
    mgr: &TerminalManager,
    ssh: SshSpec,
    tmux_session: String,
    title: Option<String>,
    cols: u16,
    rows: u16,
    env_vars: Option<HashMap<String, String>>,
) -> Result<TermSessionInfo, AppError> {
    ensure_bin("ssh").await?;
    ssh.validate()?;

    let session = tmux_session.trim().to_string();
    if session.is_empty() {
        return Err(AppError::invalid_input("tmux_session is required"));
    }

    let title = title
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| format!("{} · tmux:{}", ssh.host, session));

    let id = uuid::Uuid::new_v4().to_string();

    // Create PTY.
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::io(format!("openpty failed: {e}")))?;

    // Build the SSH command - use shell to handle ProxyCommand with spaces correctly
    let ssh_opts = ssh.interactive_ssh_options();
    let target = ssh.target();

    // Build environment exports and remote command
    let env_exports = if let Some(vars) = &env_vars {
        if vars.is_empty() {
            String::new()
        } else {
            vars.iter()
                .map(|(k, v)| format!("export {}='{}'", k, v.replace("'", "'\\''")))
                .collect::<Vec<_>>()
                .join("; ")
                + "; "
        }
    } else {
        String::new()
    };

    // Enable tmux mouse mode for scroll support, and set high history limit
    let remote_cmd = format!(
        "{}tmux start-server; \
     tmux set-option -g history-limit {}; \
     tmux set-option -g mouse on; \
     tmux set-option -t {} history-limit {} 2>/dev/null; \
     tmux new-session -A -s {}",
        env_exports, TMUX_HISTORY_LIMIT, session, TMUX_HISTORY_LIMIT, session
    );

    // Check if we have a ProxyCommand in extra_args (needs special handling)
    let has_proxy_cmd = ssh.extra_args.iter().any(|a| a.contains("ProxyCommand="));

    // Create a temporary shell script to handle complex quoting
    let script_content = if has_proxy_cmd {
        // For cloudflared/ProxyCommand: use shell to handle complex quoting
        let mut cmd_parts = vec!["exec ssh".to_string()];
        for opt in &ssh_opts {
            // Quote options that contain spaces
            if opt.contains(' ') {
                cmd_parts.push(format!("'{}'", opt.replace("'", "'\\''")));
            } else {
                cmd_parts.push(opt.clone());
            }
        }
        cmd_parts.push("-tt".to_string());
        cmd_parts.push(target.clone());
        cmd_parts.push(format!("'{}'", remote_cmd));
        cmd_parts.join(" ")
    } else {
        // For regular SSH: still use script for consistency
        let mut cmd_parts = vec!["exec ssh".to_string()];
        for opt in &ssh_opts {
            cmd_parts.push(opt.clone());
        }
        cmd_parts.push("-tt".to_string());
        cmd_parts.push(target.clone());
        cmd_parts.push(format!("'{}'", remote_cmd));
        cmd_parts.join(" ")
    };

    // Write script to temp file
    let script_path = std::env::temp_dir().join(format!("doppio_ssh_{}.sh", uuid::Uuid::new_v4()));
    std::fs::write(&script_path, format!("#!/bin/bash\n{}\n", script_content))
        .map_err(|e| AppError::io(format!("Failed to write SSH script: {}", e)))?;
    #[cfg(unix)]
    std::fs::set_permissions(&script_path, std::fs::Permissions::from_mode(0o755))
        .map_err(|e| AppError::io(format!("Failed to set script permissions: {}", e)))?;

    let mut cmd = CommandBuilder::new(&script_path);
    // Set TERM environment variable for proper terminal support
    cmd.env("TERM", "xterm-256color");
    cmd.env("LANG", "en_US.UTF-8");
    cmd.env("LC_ALL", "en_US.UTF-8");
    // Clean up script after a delay (the process will have started by then)
    let script_path_clone = script_path.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(5));
        let _ = std::fs::remove_file(script_path_clone);
    });

    // Spawn SSH inside the PTY.
    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| AppError::command(format!("spawn ssh failed: {e}")))?;

    let reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| AppError::io(format!("clone pty reader failed: {e}")))?;
    let writer = pair
        .master
        .take_writer()
        .map_err(|e| AppError::io(format!("take pty writer failed: {e}")))?;

    let master = Arc::new(Mutex::new(pair.master));
    let writer = Arc::new(Mutex::new(writer));
    let child = Arc::new(Mutex::new(child));
    let output_buffer = Arc::new(std::sync::RwLock::new(String::new()));
    let history = Arc::new(TermHistory::new(&app, &id)?);

    mgr.insert(
        id.clone(),
        TermHandle {
            title: title.clone(),
            master: master.clone(),
            writer: writer.clone(),
            child: child.clone(),
            output_buffer: output_buffer.clone(),
            history: history.clone(),
        },
    )
    .await;

    // Reader loop (blocking thread)
    let app_handle = app.clone();
    let id_data = id.clone();
    spawn_pty_reader(
        reader,
        app_handle,
        id_data,
        output_buffer.clone(),
        history.clone(),
        "Vast",
    );

    Ok(TermSessionInfo { id, title })
}

/// Helper to write to a terminal session (non-Tauri command version)
pub async fn term_write_inner(mgr: &TerminalManager, id: &str, data: &str) -> Result<(), AppError> {
    let Some(h) = mgr.get(id).await else {
        return Err(AppError::invalid_input(format!(
            "Unknown terminal session: {id}"
        )));
    };

    let data = data.to_string();
    tokio::task::spawn_blocking(move || {
        let mut w = h
            .writer
            .lock()
            .map_err(|_| AppError::io("terminal writer lock poisoned"))?;
        w.write_all(data.as_bytes())
            .map_err(|e| AppError::io(e.to_string()))?;
        w.flush().ok();
        Ok::<(), AppError>(())
    })
    .await
    .map_err(|e| AppError::io(e.to_string()))??;
    Ok(())
}

/// Display data directly in xterm.js without sending to PTY/shell
/// This avoids the command being echoed back by the shell
pub(crate) fn term_display(
    app: &tauri::AppHandle,
    id: &str,
    data: &str,
    history: Option<&TermHistory>,
) {
    if let Some(history) = history {
        if let Err(e) = history.append_output(data) {
            eprintln!("[Terminal] history append failed for {}: {}", id, e);
        }
    }
    let _ = app.emit(
        "term:data",
        TermDataEvent {
            id: id.to_string(),
            data: data.to_string(),
        },
    );
}
