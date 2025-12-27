use std::collections::HashMap;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};
use tokio::process::Command;
use tokio::sync::{mpsc, RwLock};
use tokio::task::JoinHandle;

use crate::config::doppio_data_dir;
use crate::error::AppError;
use crate::ssh::SshSpec;

// ============================================================
// Types
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
  pub session_id: String,
  pub timestamp: String,
  pub content: String,
  /// Total lines captured so far
  pub total_lines: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogSnapshot {
  pub session_id: String,
  pub lines: Vec<String>,
  pub captured_at: String,
  /// Whether the tmux session is still alive
  pub is_alive: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogStreamStatus {
  pub session_id: String,
  pub is_streaming: bool,
  pub lines_captured: u64,
  pub last_capture_at: Option<String>,
  pub error: Option<String>,
}

// ============================================================
// Local Log Storage
// ============================================================

fn logs_dir() -> PathBuf {
  doppio_data_dir().join("logs")
}

fn session_log_file(session_id: &str) -> PathBuf {
  logs_dir().join(format!("{}.log", session_id))
}

/// Save captured logs to local storage
pub fn save_logs_locally(session_id: &str, lines: &[String]) -> Result<(), AppError> {
  let dir = logs_dir();
  std::fs::create_dir_all(&dir)
    .map_err(|e| AppError::io(format!("Failed to create log dir: {}", e)))?;

  let file_path = session_log_file(session_id);
  let mut file = std::fs::File::create(&file_path)
    .map_err(|e| AppError::io(format!("Failed to create log file: {}", e)))?;

  for line in lines {
    writeln!(file, "{}", line)
      .map_err(|e| AppError::io(format!("Failed to write log: {}", e)))?;
  }

  Ok(())
}

/// Read logs from local storage
pub fn read_local_logs(session_id: &str) -> Result<Vec<String>, AppError> {
  let file_path = session_log_file(session_id);
  if !file_path.exists() {
    return Ok(vec![]);
  }

  let content = std::fs::read_to_string(&file_path)
    .map_err(|e| AppError::io(format!("Failed to read log file: {}", e)))?;

  Ok(content.lines().map(|s| s.to_string()).collect())
}

/// Clear local logs for a session
pub fn clear_local_logs(session_id: &str) -> Result<(), AppError> {
  let file_path = session_log_file(session_id);
  if file_path.exists() {
    std::fs::remove_file(&file_path)
      .map_err(|e| AppError::io(format!("Failed to clear logs: {}", e)))?;
  }
  Ok(())
}

// ============================================================
// tmux capture-pane
// ============================================================

/// Capture tmux pane output via SSH
/// 
/// Arguments:
/// - `ssh`: SSH connection spec
/// - `tmux_session`: Name of the tmux session (e.g., "doppio-abc123")
/// - `start_line`: Start line (-S), use negative for history, None for all (-S -)
/// - `strip_ansi`: Whether to strip ANSI escape codes
pub async fn capture_tmux_pane(
  ssh: &SshSpec,
  tmux_session: &str,
  start_line: Option<i64>,
  strip_ansi: bool,
) -> Result<LogSnapshot, AppError> {
  let start_arg = match start_line {
    Some(n) => format!("-S {}", n),
    None => "-S -".to_string(), // From the very beginning
  };

  // -p: print to stdout
  // -e: include escape sequences (or not with -J for joining wrapped lines)
  // -t: target session
  let escape_flag = if strip_ansi { "" } else { "-e" };
  
  let cmd_str = format!(
    "tmux capture-pane -t {} -p {} {} 2>/dev/null || echo '<<<TMUX_SESSION_DEAD>>>'",
    tmux_session, escape_flag, start_arg
  );

  let mut cmd = Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg(&cmd_str);

  let output = cmd.output().await
    .map_err(|e| AppError::command(format!("SSH capture-pane failed: {}", e)))?;

  let stdout = String::from_utf8_lossy(&output.stdout);
  let lines: Vec<String> = stdout.lines().map(|s| s.to_string()).collect();

  // Check if session is dead
  let is_alive = !lines.iter().any(|l| l.contains("<<<TMUX_SESSION_DEAD>>>"));
  let lines: Vec<String> = lines.into_iter()
    .filter(|l| !l.contains("<<<TMUX_SESSION_DEAD>>>"))
    .collect();

  Ok(LogSnapshot {
    session_id: tmux_session.to_string(),
    lines,
    captured_at: Utc::now().to_rfc3339(),
    is_alive,
  })
}

/// Check if tmux session exists
pub async fn tmux_session_exists(ssh: &SshSpec, tmux_session: &str) -> Result<bool, AppError> {
  let cmd_str = format!("tmux has-session -t {} 2>/dev/null && echo 'yes' || echo 'no'", tmux_session);

  let mut cmd = Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg(&cmd_str);

  let output = cmd.output().await
    .map_err(|e| AppError::command(format!("SSH failed: {}", e)))?;

  let stdout = String::from_utf8_lossy(&output.stdout);
  Ok(stdout.trim() == "yes")
}

/// Get tmux pane dimensions
pub async fn get_tmux_pane_info(ssh: &SshSpec, tmux_session: &str) -> Result<(u32, u32), AppError> {
  let cmd_str = format!(
    "tmux display-message -t {} -p '#{{{}}},#{{{}}}' 2>/dev/null || echo '0,0'",
    tmux_session, "pane_width", "pane_height"
  );

  let mut cmd = Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg(&cmd_str);

  let output = cmd.output().await
    .map_err(|e| AppError::command(format!("SSH failed: {}", e)))?;

  let stdout = String::from_utf8_lossy(&output.stdout);
  let parts: Vec<&str> = stdout.trim().split(',').collect();
  if parts.len() == 2 {
    let width = parts[0].parse().unwrap_or(0);
    let height = parts[1].parse().unwrap_or(0);
    Ok((width, height))
  } else {
    Ok((0, 0))
  }
}

// ============================================================
// Log Streaming (polling capture-pane)
// ============================================================

struct LogStream {
  session_id: String,
  handle: JoinHandle<()>,
  cancel_tx: mpsc::Sender<()>,
  lines_captured: Arc<RwLock<u64>>,
  last_capture_at: Arc<RwLock<Option<DateTime<Utc>>>>,
  last_error: Arc<RwLock<Option<String>>>,
}

/// Global log stream manager using tmux capture-pane polling
pub struct LogManager {
  streams: RwLock<HashMap<String, LogStream>>,
}

impl LogManager {
  pub fn new() -> Self {
    Self {
      streams: RwLock::new(HashMap::new()),
    }
  }

  /// Start streaming logs for a session using periodic capture-pane
  pub async fn start_stream(
    &self,
    session_id: String,
    ssh: SshSpec,
    tmux_session: String,
    app: AppHandle,
    poll_interval_ms: u64,
  ) -> Result<(), AppError> {
    // Check if already streaming
    {
      let streams = self.streams.read().await;
      if streams.contains_key(&session_id) {
        return Ok(()); // Already streaming
      }
    }

    let (cancel_tx, mut cancel_rx) = mpsc::channel::<()>(1);
    let lines_captured = Arc::new(RwLock::new(0u64));
    let last_capture_at = Arc::new(RwLock::new(None::<DateTime<Utc>>));
    let last_error = Arc::new(RwLock::new(None::<String>));

    let lines_clone = lines_captured.clone();
    let last_clone = last_capture_at.clone();
    let error_clone = last_error.clone();
    let session_id_clone = session_id.clone();

    let handle = tokio::spawn(async move {
      let mut last_line_count = 0usize;
      let poll_duration = tokio::time::Duration::from_millis(poll_interval_ms);

      loop {
        tokio::select! {
          _ = cancel_rx.recv() => {
            break;
          }
          _ = tokio::time::sleep(poll_duration) => {
            // Capture pane
            match capture_tmux_pane(&ssh, &tmux_session, None, true).await {
              Ok(snapshot) => {
                let now = Utc::now();
                let current_count = snapshot.lines.len();

                // Update metadata
                {
                  let mut count = lines_clone.write().await;
                  *count = current_count as u64;
                }
                {
                  let mut last = last_clone.write().await;
                  *last = Some(now);
                }
                {
                  let mut err = error_clone.write().await;
                  *err = None;
                }

                // Emit new lines only
                if current_count > last_line_count {
                  let new_lines: Vec<String> = snapshot.lines[last_line_count..].to_vec();
                  
                  // Emit batch of new lines
                  let entry = LogEntry {
                    session_id: session_id_clone.clone(),
                    timestamp: now.to_rfc3339(),
                    content: new_lines.join("\n"),
                    total_lines: current_count as u64,
                  };
                  let _ = app.emit(&format!("session-log-{}", session_id_clone), &entry);
                  let _ = app.emit("session-log", &entry);

                  last_line_count = current_count;
                }

                // Save to local storage periodically (every capture)
                let _ = save_logs_locally(&session_id_clone, &snapshot.lines);

                // Check if session died
                if !snapshot.is_alive {
                  let entry = LogEntry {
                    session_id: session_id_clone.clone(),
                    timestamp: now.to_rfc3339(),
                    content: "<<< tmux session ended >>>".to_string(),
                    total_lines: current_count as u64,
                  };
                  let _ = app.emit(&format!("session-log-{}", session_id_clone), &entry);
                  break;
                }
              }
              Err(e) => {
                let mut err = error_clone.write().await;
                *err = Some(e.to_string());
                // Continue trying
              }
            }
          }
        }
      }
    });

    // Store stream
    {
      let mut streams = self.streams.write().await;
      streams.insert(session_id.clone(), LogStream {
        session_id,
        handle,
        cancel_tx,
        lines_captured,
        last_capture_at,
        last_error,
      });
    }

    Ok(())
  }

  /// Stop streaming logs for a session
  pub async fn stop_stream(&self, session_id: &str) -> Result<(), AppError> {
    let stream = {
      let mut streams = self.streams.write().await;
      streams.remove(session_id)
    };

    if let Some(stream) = stream {
      let _ = stream.cancel_tx.send(()).await;
      stream.handle.abort();
    }

    Ok(())
  }

  /// Get status of a log stream
  pub async fn get_status(&self, session_id: &str) -> LogStreamStatus {
    let streams = self.streams.read().await;
    if let Some(stream) = streams.get(session_id) {
      let lines = *stream.lines_captured.read().await;
      let last = stream.last_capture_at.read().await.map(|dt| dt.to_rfc3339());
      let error = stream.last_error.read().await.clone();
      LogStreamStatus {
        session_id: session_id.to_string(),
        is_streaming: true,
        lines_captured: lines,
        last_capture_at: last,
        error,
      }
    } else {
      LogStreamStatus {
        session_id: session_id.to_string(),
        is_streaming: false,
        lines_captured: 0,
        last_capture_at: None,
        error: None,
      }
    }
  }

  /// Stop all streams
  pub async fn stop_all(&self) {
    let streams: Vec<_> = {
      let mut streams = self.streams.write().await;
      streams.drain().collect()
    };

    for (_, stream) in streams {
      let _ = stream.cancel_tx.send(()).await;
      stream.handle.abort();
    }
  }
}

impl Default for LogManager {
  fn default() -> Self {
    Self::new()
  }
}

// ============================================================
// One-time capture (for manual refresh)
// ============================================================

/// Fetch all logs from tmux session (one-time capture)
pub async fn fetch_session_logs(
  ssh: &SshSpec,
  tmux_session: &str,
  tail_lines: Option<i64>,
) -> Result<Vec<String>, AppError> {
  // If tail_lines is specified, use negative start line
  let start_line = tail_lines.map(|n| -(n.abs()));
  
  let snapshot = capture_tmux_pane(ssh, tmux_session, start_line, true).await?;
  Ok(snapshot.lines)
}
