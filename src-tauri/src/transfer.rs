//! Transfer task management module
//!
//! Manages file transfer operations between storages with progress tracking.
//!
//! Uses rsync/scp for SSH-based endpoints (Host, Vast, Local) and rclone for
//! cloud storage backends (Google Drive, Cloudflare R2, GCS, SMB).

use std::collections::HashMap;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::sync::RwLock;

use crate::error::AppError;
use crate::host;
use crate::ssh::SshSpec;
use crate::storage::{Storage, StorageBackend, StorageStore};

// ============================================================
// Transfer Types
// ============================================================

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TransferOperation {
    /// Copy files (keep source)
    Copy,
    /// Move files (delete source after successful copy)
    Move,
    /// Sync with delete (mirror destination to source)
    Sync,
    /// Sync without delete
    SyncNoDelete,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TransferStatus {
    Queued,
    Running,
    Paused,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TransferProgress {
    pub files_total: u64,
    pub files_done: u64,
    pub bytes_total: u64,
    pub bytes_done: u64,
    pub speed_bps: u64,
    pub eta_seconds: Option<u64>,
    pub current_file: Option<String>,
    /// Status message describing the current transfer phase/method
    pub status_message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferTask {
    pub id: String,
    /// Legacy field for backwards compatibility
    pub source_storage_id: String,
    pub source_path: String,
    /// Legacy field for backwards compatibility
    pub dest_storage_id: String,
    pub dest_path: String,
    /// New unified endpoint fields
    #[serde(default)]
    pub source_endpoint: Option<TransferEndpoint>,
    #[serde(default)]
    pub dest_endpoint: Option<TransferEndpoint>,
    pub operation: TransferOperation,
    pub status: TransferStatus,
    pub progress: TransferProgress,
    pub created_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub error: Option<String>,
}

impl TransferTask {
    pub fn new(
        source_storage_id: String,
        source_path: String,
        dest_storage_id: String,
        dest_path: String,
        operation: TransferOperation,
    ) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            source_storage_id: source_storage_id.clone(),
            source_path,
            dest_storage_id: dest_storage_id.clone(),
            dest_path,
            source_endpoint: Some(TransferEndpoint::Storage { storage_id: source_storage_id }),
            dest_endpoint: Some(TransferEndpoint::Storage { storage_id: dest_storage_id }),
            operation,
            status: TransferStatus::Queued,
            progress: TransferProgress::default(),
            created_at: chrono::Utc::now().to_rfc3339(),
            started_at: None,
            completed_at: None,
            error: None,
        }
    }

    pub fn new_unified(
        source: TransferEndpoint,
        source_path: String,
        dest: TransferEndpoint,
        dest_path: String,
        operation: TransferOperation,
    ) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            // Legacy fields for compatibility
            source_storage_id: source.display_name(),
            source_path,
            dest_storage_id: dest.display_name(),
            dest_path,
            source_endpoint: Some(source),
            dest_endpoint: Some(dest),
            operation,
            status: TransferStatus::Queued,
            progress: TransferProgress::default(),
            created_at: chrono::Utc::now().to_rfc3339(),
            started_at: None,
            completed_at: None,
            error: None,
        }
    }

    /// Get the effective source endpoint (handles legacy tasks)
    pub fn get_source_endpoint(&self) -> TransferEndpoint {
        self.source_endpoint.clone().unwrap_or_else(|| {
            TransferEndpoint::Storage { storage_id: self.source_storage_id.clone() }
        })
    }

    /// Get the effective destination endpoint (handles legacy tasks)
    pub fn get_dest_endpoint(&self) -> TransferEndpoint {
        self.dest_endpoint.clone().unwrap_or_else(|| {
            TransferEndpoint::Storage { storage_id: self.dest_storage_id.clone() }
        })
    }
}

// ============================================================
// Transfer Create Input
// ============================================================

/// Unified endpoint for transfers - can be a storage, host, vast instance, or local filesystem
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum TransferEndpoint {
    /// A configured storage
    Storage { storage_id: String },
    /// A remote host via SSH/SFTP
    Host { host_id: String },
    /// A Vast.ai instance via SSH (when running) or Vast copy API
    Vast { instance_id: i64 },
    /// Local filesystem
    Local,
}

impl TransferEndpoint {
    pub fn display_name(&self) -> String {
        match self {
            Self::Storage { storage_id } => format!("storage:{}", storage_id),
            Self::Host { host_id } => format!("host:{}", host_id),
            Self::Vast { instance_id } => format!("vast:{}", instance_id),
            Self::Local => "local".to_string(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct TransferCreateInput {
    pub source_storage_id: String,
    pub source_paths: Vec<String>,
    pub dest_storage_id: String,
    pub dest_path: String,
    pub operation: TransferOperation,
}

/// Unified transfer input supporting any endpoint type
#[derive(Debug, Clone, Deserialize)]
pub struct UnifiedTransferInput {
    pub source: TransferEndpoint,
    pub source_paths: Vec<String>,
    pub dest: TransferEndpoint,
    pub dest_path: String,
    pub operation: TransferOperation,
}

// ============================================================
// Transfer Store
// ============================================================

pub struct TransferStore {
    tasks: RwLock<HashMap<String, TransferTask>>,
    /// Queue of task IDs waiting to run
    queue: RwLock<Vec<String>>,
    /// Currently running task ID (only one at a time for now)
    running: RwLock<Option<String>>,
    data_path: PathBuf,
}

impl TransferStore {
    pub fn new(data_dir: &std::path::Path) -> Self {
        let data_path = data_dir.join("transfers.json");
        let tasks = Self::load_from_file(&data_path).unwrap_or_default();
        Self {
            tasks: RwLock::new(tasks),
            queue: RwLock::new(Vec::new()),
            running: RwLock::new(None),
            data_path,
        }
    }

    fn load_from_file(path: &PathBuf) -> Option<HashMap<String, TransferTask>> {
        let content = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&content).ok()
    }

    async fn save_to_file(&self) -> Result<(), AppError> {
        // Clone data while holding lock, then release before I/O
        let content = {
            let tasks = self.tasks.read().await;
            serde_json::to_string_pretty(&*tasks)?
        };
        // Use async file write to avoid blocking
        tokio::fs::write(&self.data_path, content).await?;
        Ok(())
    }

    pub async fn list(&self) -> Vec<TransferTask> {
        let tasks = self.tasks.read().await;
        let mut list: Vec<_> = tasks.values().cloned().collect();
        // Sort by created_at descending (newest first)
        list.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        list
    }

    pub async fn get(&self, id: &str) -> Option<TransferTask> {
        let tasks = self.tasks.read().await;
        tasks.get(id).cloned()
    }

    pub async fn create(&self, input: TransferCreateInput) -> Result<Vec<TransferTask>, AppError> {
        let mut created = Vec::new();
        let mut tasks = self.tasks.write().await;
        let mut queue = self.queue.write().await;

        for source_path in input.source_paths {
            let task = TransferTask::new(
                input.source_storage_id.clone(),
                source_path,
                input.dest_storage_id.clone(),
                input.dest_path.clone(),
                input.operation,
            );
            let id = task.id.clone();
            tasks.insert(id.clone(), task.clone());
            queue.push(id);
            created.push(task);
        }

        drop(tasks);
        drop(queue);
        self.save_to_file().await?;
        Ok(created)
    }

    /// Create unified transfer tasks supporting any endpoint type
    pub async fn create_unified(&self, input: UnifiedTransferInput) -> Result<Vec<TransferTask>, AppError> {
        let mut created = Vec::new();
        let mut tasks = self.tasks.write().await;
        let mut queue = self.queue.write().await;

        for source_path in input.source_paths {
            let task = TransferTask::new_unified(
                input.source.clone(),
                source_path,
                input.dest.clone(),
                input.dest_path.clone(),
                input.operation,
            );
            let id = task.id.clone();
            tasks.insert(id.clone(), task.clone());
            queue.push(id);
            created.push(task);
        }

        drop(tasks);
        drop(queue);
        self.save_to_file().await?;
        Ok(created)
    }

    pub async fn update_status(&self, id: &str, status: TransferStatus) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        if let Some(task) = tasks.get_mut(id) {
            task.status = status;
            match status {
                TransferStatus::Running => {
                    task.started_at = Some(chrono::Utc::now().to_rfc3339());
                }
                TransferStatus::Completed | TransferStatus::Failed | TransferStatus::Cancelled => {
                    task.completed_at = Some(chrono::Utc::now().to_rfc3339());
                }
                _ => {}
            }
        }
        drop(tasks);
        self.save_to_file().await?;
        Ok(())
    }

    pub async fn update_progress(
        &self,
        id: &str,
        progress: TransferProgress,
    ) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        if let Some(task) = tasks.get_mut(id) {
            task.progress = progress;
        }
        Ok(())
    }

    pub async fn set_error(&self, id: &str, error: String) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        if let Some(task) = tasks.get_mut(id) {
            task.error = Some(error);
            task.status = TransferStatus::Failed;
            task.completed_at = Some(chrono::Utc::now().to_rfc3339());
        }
        drop(tasks);
        self.save_to_file().await?;
        Ok(())
    }

    pub async fn cancel(&self, id: &str) -> Result<(), AppError> {
        // Remove from queue if queued
        {
            let mut queue = self.queue.write().await;
            queue.retain(|qid| qid != id);
        }

        self.update_status(id, TransferStatus::Cancelled).await
    }

    pub async fn clear_completed(&self) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        tasks.retain(|_, task| {
            !matches!(
                task.status,
                TransferStatus::Completed | TransferStatus::Failed | TransferStatus::Cancelled
            )
        });
        drop(tasks);
        self.save_to_file().await
    }

    /// Get next queued task
    pub async fn next_queued(&self) -> Option<String> {
        let queue = self.queue.read().await;
        queue.first().cloned()
    }

    /// Pop task from queue
    pub async fn pop_queue(&self) -> Option<String> {
        let mut queue = self.queue.write().await;
        if queue.is_empty() {
            None
        } else {
            Some(queue.remove(0))
        }
    }

    /// Check if any task is running
    pub async fn is_running(&self) -> bool {
        self.running.read().await.is_some()
    }

    /// Set running task
    pub async fn set_running(&self, id: Option<String>) {
        *self.running.write().await = id;
    }
}

// ============================================================
// Transfer Execution - Rsync/SSH helpers
// ============================================================

/// Build a bash script that wraps SSH with the right options for rsync
fn build_rsync_ssh_wrapper(ssh: &SshSpec) -> Result<PathBuf, AppError> {
    let mut lines = vec![
        "#!/usr/bin/env bash".to_string(),
        "set -e".to_string(),
        "cmd=(ssh)".to_string(),
    ];

    for opt in ssh.common_ssh_options() {
        lines.push(format!("cmd+=({})", bash_quote(&opt)));
    }

    lines.push(r#"exec "${cmd[@]}" "$@""#.to_string());

    let script_path =
        std::env::temp_dir().join(format!("doppio_rsync_ssh_{}.sh", uuid::Uuid::new_v4()));
    std::fs::write(&script_path, format!("{}\n", lines.join("\n")))
        .map_err(|e| AppError::io(format!("Failed to write rsync ssh wrapper: {}", e)))?;
    #[cfg(unix)]
    std::fs::set_permissions(&script_path, std::fs::Permissions::from_mode(0o755)).map_err(
        |e| {
            AppError::io(format!(
                "Failed to set rsync ssh wrapper permissions: {}",
                e
            ))
        },
    )?;

    Ok(script_path)
}

fn bash_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

/// Escape a remote path for rsync (handles spaces and special characters)
/// For rsync over SSH, the remote path needs to be escaped for the remote shell
fn escape_rsync_remote_path(path: &str) -> String {
    // For rsync, we need to escape spaces and special chars with backslashes
    // This works because rsync passes the path to the remote shell
    path.chars()
        .map(|c| {
            if c == ' ' || c == '\'' || c == '"' || c == '\\' || c == '(' || c == ')'
               || c == '[' || c == ']' || c == '{' || c == '}' || c == '$' || c == '`'
               || c == '!' || c == '&' || c == ';' || c == '*' || c == '?' {
                format!("\\{}", c)
            } else {
                c.to_string()
            }
        })
        .collect()
}

/// Run rsync with SSH wrapper and emit progress events
async fn run_rsync_transfer(
    ssh_wrapper: &PathBuf,
    args: Vec<String>,
    task_id: &str,
    app: &AppHandle,
) -> Result<(), AppError> {
    use std::process::Stdio;

    eprintln!("[rsync] Starting with args: {:?}", args);

    let mut cmd = tokio::process::Command::new("rsync");
    cmd.args(&args);
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::command(format!("Failed to spawn rsync: {}", e)))?;

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    // Stream stdout for progress
    // rsync --info=progress2 output format:
    //   1,234,567  50%   10.00MB/s    0:00:30 (xfr#1, to-chk=10/100)
    let task_id_clone = task_id.to_string();
    let app_clone = app.clone();
    let stdout_handle = tokio::spawn(async move {
        if let Some(stdout) = stdout {
            let reader = BufReader::new(stdout);
            let mut lines = reader.lines();
            let mut last_progress = TransferProgress::default();

            while let Ok(Some(line)) = lines.next_line().await {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }

                eprintln!("[rsync stdout] {}", line);

                // Parse progress2 format: "1,234,567  50%   10.00MB/s    0:00:30"
                // Also handles: "1,234,567 100%   10.00MB/s    0:00:30 (xfr#1, to-chk=0/100)"
                if line.contains('%') {
                    let parts: Vec<&str> = line.split_whitespace().collect();

                    // Find bytes (first number with commas or just digits)
                    if let Some(bytes_str) = parts.first() {
                        let bytes_clean: String = bytes_str.chars().filter(|c| c.is_ascii_digit()).collect();
                        if let Ok(bytes) = bytes_clean.parse::<u64>() {
                            last_progress.bytes_done = bytes;
                        }
                    }

                    // Find percentage
                    if let Some(pct_str) = parts.iter().find(|s| s.ends_with('%')) {
                        if let Ok(pct) = pct_str.trim_end_matches('%').parse::<u64>() {
                            if pct > 0 && last_progress.bytes_done > 0 {
                                // Calculate total from percentage
                                last_progress.bytes_total = (last_progress.bytes_done * 100) / pct.max(1);
                            }
                        }
                    }

                    // Find speed (e.g., "10.00MB/s" or "1.23kB/s")
                    if let Some(speed_str) = parts.iter().find(|s| s.contains("/s")) {
                        last_progress.speed_bps = parse_rsync_speed(speed_str);
                    }

                    // Find ETA (e.g., "0:00:30" or "1:23:45")
                    if let Some(eta_str) = parts.iter().find(|s| s.contains(':') && !s.contains('/')) {
                        last_progress.eta_seconds = parse_rsync_eta(eta_str);
                    }

                    // Find file counts from (xfr#N, to-chk=M/T)
                    if let Some(xfr_part) = parts.iter().find(|s| s.starts_with("(xfr#")) {
                        // Parse xfr#N for files done
                        if let Some(n_str) = xfr_part.strip_prefix("(xfr#") {
                            if let Some(n_end) = n_str.find(',') {
                                if let Ok(n) = n_str[..n_end].parse::<u64>() {
                                    last_progress.files_done = n;
                                }
                            }
                        }
                    }
                    if let Some(chk_part) = parts.iter().find(|s| s.starts_with("to-chk=") || s.contains("to-chk=")) {
                        // Parse to-chk=M/T for remaining/total
                        if let Some(eq_pos) = chk_part.find("to-chk=") {
                            let after_eq = &chk_part[eq_pos + 7..];
                            let clean: String = after_eq.chars().filter(|c| c.is_ascii_digit() || *c == '/').collect();
                            let nums: Vec<&str> = clean.split('/').collect();
                            if nums.len() == 2 {
                                if let (Ok(remaining), Ok(total)) = (nums[0].parse::<u64>(), nums[1].parse::<u64>()) {
                                    last_progress.files_total = total;
                                    last_progress.files_done = total.saturating_sub(remaining);
                                }
                            }
                        }
                    }

                    last_progress.current_file = Some(line.to_string());
                    emit_transfer_progress(&app_clone, &task_id_clone, last_progress.clone());
                } else if !line.starts_with("sending") && !line.starts_with("receiving")
                    && !line.starts_with("total") && !line.starts_with("sent ")
                    && !line.contains("bytes/sec") {
                    // This is likely a filename being transferred
                    last_progress.current_file = Some(line.to_string());
                    emit_transfer_progress(&app_clone, &task_id_clone, last_progress.clone());
                }
            }
        }
    });

    // Stream stderr
    let stderr_output = Arc::new(tokio::sync::Mutex::new(Vec::new()));
    let stderr_output_clone = stderr_output.clone();
    let stderr_handle = tokio::spawn(async move {
        if let Some(stderr) = stderr {
            let reader = BufReader::new(stderr);
            let mut lines = reader.lines();
            while let Ok(Some(line)) = lines.next_line().await {
                eprintln!("[rsync stderr] {}", line);
                stderr_output_clone.lock().await.push(line);
            }
        }
    });

    // Wait for the process to complete
    let status = child
        .wait()
        .await
        .map_err(|e| AppError::command(format!("Failed to wait for rsync: {}", e)))?;

    eprintln!("[rsync] Process exited with status: {:?}", status);

    // Clean up SSH wrapper
    let _ = std::fs::remove_file(ssh_wrapper);

    // Wait for output streams to finish
    let _ = stdout_handle.await;
    let _ = stderr_handle.await;

    if !status.success() {
        let stderr_lines = stderr_output.lock().await;
        let stderr_str = stderr_lines.join("\n");
        return Err(AppError::command(format!(
            "rsync failed (code={:?}): {}",
            status.code(),
            if stderr_str.is_empty() {
                "(no output)".to_string()
            } else {
                stderr_str
            }
        )));
    }

    Ok(())
}

/// Parse rsync speed string like "10.00MB/s" or "1.23kB/s" to bytes per second
fn parse_rsync_speed(s: &str) -> u64 {
    let s = s.trim();
    // Find where the number ends
    let num_end = s.find(|c: char| !c.is_ascii_digit() && c != '.').unwrap_or(s.len());
    let num_str = &s[..num_end];
    let unit_str = &s[num_end..].to_lowercase();

    let num: f64 = num_str.parse().unwrap_or(0.0);

    let multiplier = if unit_str.contains("gb") {
        1024.0 * 1024.0 * 1024.0
    } else if unit_str.contains("mb") {
        1024.0 * 1024.0
    } else if unit_str.contains("kb") {
        1024.0
    } else {
        1.0
    };

    (num * multiplier) as u64
}

/// Parse rsync ETA string like "0:00:30" or "1:23:45" to seconds
fn parse_rsync_eta(s: &str) -> Option<u64> {
    let parts: Vec<&str> = s.split(':').collect();
    match parts.len() {
        2 => {
            // MM:SS
            let mins: u64 = parts[0].parse().ok()?;
            let secs: u64 = parts[1].parse().ok()?;
            Some(mins * 60 + secs)
        }
        3 => {
            // HH:MM:SS
            let hours: u64 = parts[0].parse().ok()?;
            let mins: u64 = parts[1].parse().ok()?;
            let secs: u64 = parts[2].parse().ok()?;
            Some(hours * 3600 + mins * 60 + secs)
        }
        _ => None,
    }
}

/// Get SshSpec for an endpoint (Host or Vast)
async fn get_endpoint_ssh_spec(endpoint: &TransferEndpoint) -> Result<SshSpec, AppError> {
    match endpoint {
        TransferEndpoint::Host { host_id } => {
            let host_info = host::get_host(host_id).await?;
            host_info.ssh.ok_or_else(|| {
                AppError::invalid_input(format!("Host {} has no SSH configuration", host_id))
            })
        }
        TransferEndpoint::Vast { instance_id } => {
            let cfg = crate::config::load_config().await?;
            let client = crate::vast::VastClient::from_cfg(&cfg)?;
            let inst = client.get_instance(*instance_id).await?;

            let host = inst.ssh_host.clone().unwrap_or_default().trim().to_string();
            let port = inst.ssh_port.unwrap_or(0);
            if host.is_empty() || port <= 0 {
                return Err(AppError::invalid_input(
                    "Vast instance does not have SSH info yet (is it running and provisioned?)",
                ));
            }

            Ok(SshSpec {
                host,
                port,
                user: {
                    let u = cfg.vast.ssh_user.trim();
                    if u.is_empty() {
                        "root".to_string()
                    } else {
                        u.to_string()
                    }
                },
                key_path: match cfg
                    .vast
                    .ssh_key_path
                    .clone()
                    .filter(|s| !s.trim().is_empty())
                {
                    Some(s) => {
                        let p = crate::ssh_keys::materialize_private_key_path(&s).await?;
                        Some(p.to_string_lossy().to_string())
                    }
                    None => None,
                },
                extra_args: vec![],
            })
        }
        _ => Err(AppError::invalid_input("Endpoint is not SSH-based")),
    }
}

/// Check if an endpoint is SSH-based (Host, Vast) - not cloud storage
fn is_ssh_endpoint(endpoint: &TransferEndpoint) -> bool {
    matches!(endpoint, TransferEndpoint::Host { .. } | TransferEndpoint::Vast { .. })
}

/// Check if an endpoint is local filesystem
fn is_local_endpoint(endpoint: &TransferEndpoint) -> bool {
    matches!(endpoint, TransferEndpoint::Local)
}

/// Check if transfer should use rsync (both endpoints are SSH-based or local)
fn should_use_rsync(source: &TransferEndpoint, dest: &TransferEndpoint) -> bool {
    let src_rsync = is_ssh_endpoint(source) || is_local_endpoint(source);
    let dst_rsync = is_ssh_endpoint(dest) || is_local_endpoint(dest);
    src_rsync && dst_rsync
}

/// Expand local path (handle ~ and /)
fn expand_local_path(path: &str) -> String {
    if path == "/" || path.is_empty() {
        dirs::home_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "/".to_string())
    } else if path == "~" {
        dirs::home_dir()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "/".to_string())
    } else if let Some(rest) = path.strip_prefix("~/") {
        dirs::home_dir()
            .map(|p| p.join(rest).to_string_lossy().to_string())
            .unwrap_or_else(|| format!("/{}", rest))
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{}", path)
    }
}

/// Execute rsync transfer between two SSH-based or local endpoints
async fn execute_rsync_transfer(
    task: &TransferTask,
    app: &AppHandle,
) -> Result<(), AppError> {
    let source_endpoint = task.get_source_endpoint();
    let dest_endpoint = task.get_dest_endpoint();

    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Starting rsync transfer...".to_string()),
            ..Default::default()
        },
    );

    // Determine the rsync source and destination specs
    let (src_spec, src_path) = match &source_endpoint {
        TransferEndpoint::Local => {
            (None, expand_local_path(&task.source_path))
        }
        TransferEndpoint::Host { .. } | TransferEndpoint::Vast { .. } => {
            let ssh = get_endpoint_ssh_spec(&source_endpoint).await?;
            let path = if task.source_path.starts_with('/') || task.source_path.starts_with('~') {
                task.source_path.clone()
            } else {
                format!("~/{}", task.source_path)
            };
            (Some(ssh), path)
        }
        _ => return Err(AppError::invalid_input("Source endpoint not supported for rsync")),
    };

    let (dst_spec, dst_path) = match &dest_endpoint {
        TransferEndpoint::Local => {
            (None, expand_local_path(&task.dest_path))
        }
        TransferEndpoint::Host { .. } | TransferEndpoint::Vast { .. } => {
            let ssh = get_endpoint_ssh_spec(&dest_endpoint).await?;
            let path = if task.dest_path.starts_with('/') || task.dest_path.starts_with('~') {
                task.dest_path.clone()
            } else {
                format!("~/{}", task.dest_path)
            };
            (Some(ssh), path)
        }
        _ => return Err(AppError::invalid_input("Destination endpoint not supported for rsync")),
    };

    // Get source filename for destination path construction
    let source_name = std::path::Path::new(&task.source_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();

    // Construct final destination path
    let final_dst_path = if !source_name.is_empty() && !source_name.starts_with('.') {
        if dst_path.ends_with('/') {
            format!("{}{}", dst_path, source_name)
        } else {
            format!("{}/{}", dst_path, source_name)
        }
    } else {
        dst_path.clone()
    };

    // Build rsync args based on source/dest combination
    match (&src_spec, &dst_spec) {
        // Local to Local
        (None, None) => {
            // Create destination directory if needed
            if let Some(parent) = std::path::Path::new(&final_dst_path).parent() {
                tokio::fs::create_dir_all(parent).await.ok();
            }

            let args = vec![
                "-avz".to_string(),
                "--info=progress2".to_string(),
                src_path,
                final_dst_path,
            ];

            // For local-to-local, we don't need SSH wrapper
            let dummy_wrapper = std::env::temp_dir().join("dummy");
            run_rsync_transfer(&dummy_wrapper, args, &task.id, app).await?;
        }

        // Local to Remote
        (None, Some(dst_ssh)) => {
            let ssh_wrapper = build_rsync_ssh_wrapper(dst_ssh)?;
            let remote = format!("{}@{}:{}", dst_ssh.user, dst_ssh.host, escape_rsync_remote_path(&final_dst_path));

            // Ensure destination directory exists
            let mkdir_cmd = format!(
                r#"mkdir -p "$(dirname '{}')""#,
                final_dst_path.replace('\'', "'\\''")
            );
            let mut ssh_cmd = tokio::process::Command::new("ssh");
            for arg in dst_ssh.common_ssh_options() {
                ssh_cmd.arg(arg);
            }
            ssh_cmd.arg(dst_ssh.target());
            ssh_cmd.arg(&mkdir_cmd);
            let _ = ssh_cmd.output().await;

            let mut args = vec![
                "-avz".to_string(),
                "--info=progress2".to_string(),
                "-e".to_string(),
                ssh_wrapper.to_string_lossy().to_string(),
            ];

            if task.operation == TransferOperation::Sync {
                args.push("--delete".to_string());
            }

            args.push(src_path);
            args.push(remote);

            run_rsync_transfer(&ssh_wrapper, args, &task.id, app).await?;
        }

        // Remote to Local
        (Some(src_ssh), None) => {
            let ssh_wrapper = build_rsync_ssh_wrapper(src_ssh)?;
            let remote = format!("{}@{}:{}", src_ssh.user, src_ssh.host, escape_rsync_remote_path(&src_path));

            // Create local directory if needed
            if let Some(parent) = std::path::Path::new(&final_dst_path).parent() {
                tokio::fs::create_dir_all(parent).await.ok();
            }

            let mut args = vec![
                "-avz".to_string(),
                "--info=progress2".to_string(),
                "-e".to_string(),
                ssh_wrapper.to_string_lossy().to_string(),
            ];

            args.push(remote);
            args.push(final_dst_path);

            run_rsync_transfer(&ssh_wrapper, args, &task.id, app).await?;
        }

        // Remote to Remote (via local staging)
        (Some(src_ssh), Some(dst_ssh)) => {
            // Create temp staging directory
            let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
            tokio::fs::create_dir_all(&temp_dir).await
                .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;

            emit_transfer_progress(
                app,
                &task.id,
                TransferProgress {
                    current_file: Some(format!("Downloading from source...")),
                    ..Default::default()
                },
            );

            // Download from source to temp
            let src_wrapper = build_rsync_ssh_wrapper(src_ssh)?;
            let remote_src = format!("{}@{}:{}", src_ssh.user, src_ssh.host, escape_rsync_remote_path(&src_path));
            let temp_path = temp_dir.to_string_lossy().to_string();

            let download_args = vec![
                "-avz".to_string(),
                "--info=progress2".to_string(),
                "-e".to_string(),
                src_wrapper.to_string_lossy().to_string(),
                remote_src,
                temp_path.clone(),
            ];

            run_rsync_transfer(&src_wrapper, download_args, &task.id, app).await?;

            emit_transfer_progress(
                app,
                &task.id,
                TransferProgress {
                    current_file: Some(format!("Uploading to destination...")),
                    ..Default::default()
                },
            );

            // Upload from temp to destination
            let dst_wrapper = build_rsync_ssh_wrapper(dst_ssh)?;
            let remote_dst = format!("{}@{}:{}", dst_ssh.user, dst_ssh.host, escape_rsync_remote_path(&final_dst_path));

            // Ensure destination directory exists
            let mkdir_cmd = format!(
                r#"mkdir -p "$(dirname '{}')""#,
                final_dst_path.replace('\'', "'\\''")
            );
            let mut ssh_cmd = tokio::process::Command::new("ssh");
            for arg in dst_ssh.common_ssh_options() {
                ssh_cmd.arg(arg);
            }
            ssh_cmd.arg(dst_ssh.target());
            ssh_cmd.arg(&mkdir_cmd);
            let _ = ssh_cmd.output().await;

            // Determine upload source path
            let upload_src = if source_name.is_empty() || source_name.starts_with('.') {
                format!("{}/", temp_path.trim_end_matches('/'))
            } else {
                let staged = temp_dir.join(&source_name);
                if staged.exists() {
                    staged.to_string_lossy().to_string()
                } else {
                    format!("{}/", temp_path.trim_end_matches('/'))
                }
            };

            let mut upload_args = vec![
                "-avz".to_string(),
                "--info=progress2".to_string(),
                "-e".to_string(),
                dst_wrapper.to_string_lossy().to_string(),
            ];

            if task.operation == TransferOperation::Sync {
                upload_args.push("--delete".to_string());
            }

            upload_args.push(upload_src);
            upload_args.push(remote_dst);

            let result = run_rsync_transfer(&dst_wrapper, upload_args, &task.id, app).await;

            // Cleanup temp directory
            let _ = tokio::fs::remove_dir_all(&temp_dir).await;

            result?;
        }
    }

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            bytes_done: 1,
            bytes_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

// ============================================================
// Transfer Execution - Rclone (for cloud storage)
// ============================================================

/// Execute a transfer task using rclone (legacy, for storage backends)
pub async fn execute_transfer(
    task: &TransferTask,
    source_storage: &Storage,
    dest_storage: &Storage,
    app: &AppHandle,
) -> Result<(), AppError> {
    // Build rclone command based on operation type
    let rpc_method = match task.operation {
        TransferOperation::Copy | TransferOperation::Move => "sync/copy",
        TransferOperation::Sync => "sync/sync",
        TransferOperation::SyncNoDelete => "sync/copy",
    };

    // Build source and destination paths (use async version for SSH support)
    let (src_remote, src_path) = build_remote_spec_async(source_storage, &task.source_path).await?;
    let (dst_remote, dst_path) = build_remote_spec_async(dest_storage, &task.dest_path).await?;

    // Create temporary remotes if needed
    let src_remote_name = if let Some(config) = src_remote {
        Some(create_temp_remote("src", &config)?)
    } else {
        None
    };

    let dst_remote_name = if let Some(config) = dst_remote {
        Some(create_temp_remote("dst", &config)?)
    } else {
        None
    };

    let src_fs = match &src_remote_name {
        Some(name) => format!("{}:{}", name, src_path),
        None => src_path.clone(),
    };

    let dst_fs = match &dst_remote_name {
        Some(name) => format!("{}:{}", name, dst_path),
        None => dst_path.clone(),
    };

    // Build sync options
    let mut sync_opts = serde_json::json!({
        "srcFs": src_fs,
        "dstFs": dst_fs,
        "_async": false,
        "copyLinks": true,
    });

    if task.operation == TransferOperation::Sync {
        sync_opts["deleteMode"] = serde_json::json!("sync");
    }

    // Emit starting progress
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Starting transfer...".to_string()),
            ..Default::default()
        },
    );

    // Execute the operation
    let result = librclone::rpc(rpc_method, &sync_opts.to_string());

    // Clean up temporary remotes
    if let Some(name) = src_remote_name {
        delete_temp_remote(&name);
    }
    if let Some(name) = dst_remote_name {
        delete_temp_remote(&name);
    }

    // Handle move operation (delete source after successful copy)
    if task.operation == TransferOperation::Move && result.is_ok() {
        // Delete source
        // This would need the source storage to be writable
        // For now, we skip this and document it as a limitation
    }

    result.map_err(|e| AppError::command(format!("Transfer failed: {}", e)))?;

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

fn build_remote_spec(
    storage: &Storage,
    path: &str,
) -> Result<(Option<serde_json::Value>, String), AppError> {
    match &storage.backend {
        StorageBackend::Local { root_path } => {
            let full_path = PathBuf::from(root_path)
                .join(path.trim_start_matches('/'))
                .to_string_lossy()
                .to_string();
            Ok((None, full_path))
        }
        StorageBackend::CloudflareR2 {
            account_id,
            access_key_id,
            secret_access_key,
            bucket,
            endpoint,
        } => {
            let endpoint = endpoint
                .clone()
                .unwrap_or_else(|| format!("https://{}.r2.cloudflarestorage.com", account_id));
            let config = serde_json::json!({
                "type": "s3",
                "provider": "Cloudflare",
                "access_key_id": access_key_id,
                "secret_access_key": secret_access_key,
                "endpoint": endpoint,
                "acl": "private",
            });
            let full_path = format!("{}/{}", bucket, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
        StorageBackend::GoogleDrive {
            token,
            root_folder_id,
            ..
        } => {
            let mut config = serde_json::json!({
                "type": "drive",
                "scope": "drive",
            });
            if let Some(t) = token {
                config["token"] = serde_json::json!(t);
            }
            if let Some(folder_id) = root_folder_id {
                config["root_folder_id"] = serde_json::json!(folder_id);
            }
            Ok((Some(config), path.trim_start_matches('/').to_string()))
        }
        StorageBackend::GoogleCloudStorage {
            project_id,
            service_account_json,
            bucket,
        } => {
            let mut config = serde_json::json!({
                "type": "gcs",
                "project_number": project_id,
            });
            if let Some(sa) = service_account_json {
                config["service_account_credentials"] = serde_json::json!(sa);
            }
            let full_path = format!("{}/{}", bucket, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
        StorageBackend::Smb {
            host,
            share,
            user,
            password,
            domain,
        } => {
            let mut config = serde_json::json!({
                "type": "smb",
                "host": host,
            });
            if let Some(u) = user {
                config["user"] = serde_json::json!(u);
            }
            if let Some(p) = password {
                config["pass"] = serde_json::json!(p);
            }
            if let Some(d) = domain {
                config["domain"] = serde_json::json!(d);
            }
            let full_path = format!("{}/{}", share, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
        StorageBackend::SshRemote {
            host_id,
            root_path: _,
        } => {
            // SSH remotes use SFTP via rclone - need async resolution
            Err(AppError::invalid_input(format!(
                "SSH remote {} requires async resolution - use build_remote_spec_async",
                host_id
            )))
        }
    }
}

/// Async version that can resolve storage backends
/// Note: SSH remote storage should use Host endpoint for rsync transfers
async fn build_remote_spec_async(
    storage: &Storage,
    path: &str,
) -> Result<(Option<serde_json::Value>, String), AppError> {
    match &storage.backend {
        StorageBackend::SshRemote { host_id, root_path: _ } => {
            // SSH remote storage should use Host endpoint with rsync instead
            Err(AppError::invalid_input(format!(
                "SSH remote storage '{}' should use Host endpoint (host_id={}) for transfers. \
                 Rsync is more reliable than rclone SFTP for SSH transfers.",
                storage.id, host_id
            )))
        }
        _ => build_remote_spec(storage, path),
    }
}

/// Build remote spec from a unified endpoint (for rclone transfers)
/// Note: Host and Vast endpoints are handled by rsync, not rclone
async fn build_endpoint_spec(
    endpoint: &TransferEndpoint,
    path: &str,
    storage_store: &StorageStore,
) -> Result<(Option<serde_json::Value>, String), AppError> {
    match endpoint {
        TransferEndpoint::Local => {
            // Local filesystem - no remote config needed
            let full_path = expand_local_path(path);
            Ok((None, full_path))
        }
        TransferEndpoint::Host { host_id } => {
            // Host endpoints should use rsync, not rclone
            // This path is only reached for mixed transfers (Host <-> Storage)
            // In that case, we stage through local temp directory
            Err(AppError::invalid_input(format!(
                "Host {} transfers to/from cloud storage should use local staging. Use rsync for SSH-based transfers.",
                host_id
            )))
        }
        TransferEndpoint::Vast { instance_id } => {
            // Vast endpoints should use rsync, not rclone
            Err(AppError::invalid_input(format!(
                "Vast instance {} transfers to/from cloud storage should use local staging. Use rsync for SSH-based transfers.",
                instance_id
            )))
        }
        TransferEndpoint::Storage { storage_id } => {
            // Get storage and build spec
            let storage = storage_store.get(storage_id).await.ok_or_else(|| {
                AppError::not_found(format!("Storage not found: {}", storage_id))
            })?;
            build_remote_spec_async(&storage, path).await
        }
    }
}

fn create_temp_remote(prefix: &str, config: &serde_json::Value) -> Result<String, AppError> {
    let remote_name = format!(
        "{}_{}",
        prefix,
        uuid::Uuid::new_v4().to_string().replace("-", "")[..8].to_string()
    );

    let remote_type = config
        .get("type")
        .and_then(|v| v.as_str())
        .unwrap_or("local");

    // For Google Drive, use a different approach - create the remote without OAuth validation
    if remote_type == "drive" {
        // First create empty remote
        let create_params = serde_json::json!({
            "name": remote_name,
            "type": "drive",
            "parameters": {},
            "opt": {
                "nonInteractive": true,
                "obscure": false,
                "noAutocomplete": true,
            }
        });

        eprintln!("Creating Google Drive remote: {}", remote_name);
        librclone::rpc("config/create", &create_params.to_string())
            .map_err(|e| AppError::command(format!("Failed to create drive remote: {}", e)))?;

        // Then set parameters one by one using config/update
        if let Some(client_id) = config.get("client_id").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "client_id": client_id },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        if let Some(client_secret) = config.get("client_secret").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "client_secret": client_secret },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        if let Some(token) = config.get("token").and_then(|v| v.as_str()) {
            eprintln!("Setting token for {}", remote_name);
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "token": token },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        if let Some(scope) = config.get("scope").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "scope": scope },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }

        return Ok(remote_name);
    }

    // For other backends, use standard config/create
    // Note: We need to remove the "type" field from parameters since it's specified separately
    let mut parameters = config.clone();
    if parameters.is_object() {
        parameters.as_object_mut().unwrap().remove("type");
    }

    let create_params = serde_json::json!({
        "name": remote_name,
        "type": remote_type,
        "parameters": parameters,
        "opt": {
            "nonInteractive": true,
            "obscure": false,
        }
    });

    // Debug log for SFTP remotes (hide sensitive data)
    if remote_type == "sftp" {
        let mut debug_params = parameters.clone();
        if debug_params.get("key_file").is_some() {
            debug_params["key_file"] = serde_json::json!("[REDACTED]");
        }
        eprintln!("[transfer] Creating SFTP remote {} with params: {}", remote_name, debug_params);
    }

    librclone::rpc("config/create", &create_params.to_string())
        .map_err(|e| AppError::command(format!("Failed to create rclone remote: {}", e)))?;

    Ok(remote_name)
}

fn delete_temp_remote(remote_name: &str) {
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());
}

fn emit_transfer_progress(app: &AppHandle, task_id: &str, progress: TransferProgress) {
    let _ = app.emit(&format!("transfer-progress-{}", task_id), &progress);
    let _ = app.emit(
        "transfer-progress",
        serde_json::json!({
            "task_id": task_id,
            "progress": progress,
        }),
    );
}

/// Check if a Vast instance is running (has SSH access)
async fn is_vast_instance_running(instance_id: i64) -> Result<bool, AppError> {
    let cfg = crate::config::load_config().await?;
    let client = crate::vast::VastClient::from_cfg(&cfg)?;
    let inst = client.get_instance(instance_id).await?;
    let status = inst.actual_status.clone().unwrap_or_default().to_lowercase();
    Ok(status == "running")
}

/// Execute SSH -> Storage transfer (via local staging)
async fn execute_ssh_to_storage_transfer(
    task: &TransferTask,
    storage_store: &StorageStore,
    app: &AppHandle,
) -> Result<(), AppError> {
    let source_endpoint = task.get_source_endpoint();
    let dest_endpoint = task.get_dest_endpoint();

    // Create temp staging directory
    let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&temp_dir).await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;

    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Downloading from SSH host...".to_string()),
            ..Default::default()
        },
    );

    // Step 1: Download from SSH to local temp using rsync
    let ssh = get_endpoint_ssh_spec(&source_endpoint).await?;
    let ssh_wrapper = build_rsync_ssh_wrapper(&ssh)?;

    let src_path = if task.source_path.starts_with('/') || task.source_path.starts_with('~') {
        task.source_path.clone()
    } else {
        format!("~/{}", task.source_path)
    };
    let remote_src = format!("{}@{}:{}", ssh.user, ssh.host, escape_rsync_remote_path(&src_path));
    let temp_path = temp_dir.to_string_lossy().to_string();

    let download_args = vec![
        "-avz".to_string(),
        "--info=progress2".to_string(),
        "-e".to_string(),
        ssh_wrapper.to_string_lossy().to_string(),
        remote_src,
        temp_path.clone(),
    ];

    run_rsync_transfer(&ssh_wrapper, download_args, &task.id, app).await?;

    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Uploading to cloud storage...".to_string()),
            ..Default::default()
        },
    );

    // Step 2: Upload from temp to storage using rclone
    let storage_id = match &dest_endpoint {
        TransferEndpoint::Storage { storage_id } => storage_id.clone(),
        _ => return Err(AppError::invalid_input("Destination is not a storage")),
    };

    let storage = storage_store.get(&storage_id).await.ok_or_else(|| {
        AppError::not_found(format!("Storage not found: {}", storage_id))
    })?;

    let (dst_remote, dst_full_path) = build_remote_spec_async(&storage, &task.dest_path).await?;

    // Get source filename
    let source_name = std::path::Path::new(&task.source_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();

    // Determine the actual file/folder path in temp
    let upload_src = if source_name.is_empty() || source_name.starts_with('.') {
        temp_path.clone()
    } else {
        let staged = temp_dir.join(&source_name);
        if staged.exists() {
            staged.to_string_lossy().to_string()
        } else {
            temp_path.clone()
        }
    };

    // Create rclone remote and upload
    if let Some(config) = dst_remote {
        let remote_name = create_temp_remote("dst", &config)?;

        // Construct destination path with source name
        let final_dst = if !source_name.is_empty() && !source_name.starts_with('.') {
            if dst_full_path.ends_with('/') {
                format!("{}{}", dst_full_path, source_name)
            } else {
                format!("{}/{}", dst_full_path, source_name)
            }
        } else {
            dst_full_path
        };

        let dst_fs = format!("{}:{}", remote_name, final_dst);

        let result = librclone::rpc(
            "sync/copy",
            &serde_json::json!({
                "srcFs": upload_src,
                "dstFs": dst_fs,
                "_async": false,
            })
            .to_string(),
        );

        delete_temp_remote(&remote_name);

        // Cleanup temp
        let _ = tokio::fs::remove_dir_all(&temp_dir).await;

        result.map_err(|e| AppError::command(format!("Upload to storage failed: {}", e)))?;
    } else {
        // Local storage - just copy
        let final_dst = if !source_name.is_empty() && !source_name.starts_with('.') {
            format!("{}/{}", dst_full_path.trim_end_matches('/'), source_name)
        } else {
            dst_full_path
        };

        let status = tokio::process::Command::new("rsync")
            .args(["-av", &upload_src, &final_dst])
            .status()
            .await
            .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;

        let _ = tokio::fs::remove_dir_all(&temp_dir).await;

        if !status.success() {
            return Err(AppError::command("Copy to local storage failed"));
        }
    }

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            bytes_done: 1,
            bytes_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

/// Execute Storage -> SSH transfer (via local staging)
async fn execute_storage_to_ssh_transfer(
    task: &TransferTask,
    storage_store: &StorageStore,
    app: &AppHandle,
) -> Result<(), AppError> {
    let source_endpoint = task.get_source_endpoint();
    let dest_endpoint = task.get_dest_endpoint();

    // Create temp staging directory
    let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&temp_dir).await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;

    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Downloading from cloud storage...".to_string()),
            ..Default::default()
        },
    );

    // Step 1: Download from storage to local temp using rclone
    let storage_id = match &source_endpoint {
        TransferEndpoint::Storage { storage_id } => storage_id.clone(),
        _ => return Err(AppError::invalid_input("Source is not a storage")),
    };

    let storage = storage_store.get(&storage_id).await.ok_or_else(|| {
        AppError::not_found(format!("Storage not found: {}", storage_id))
    })?;

    let (src_remote, src_full_path) = build_remote_spec_async(&storage, &task.source_path).await?;
    let temp_path = temp_dir.to_string_lossy().to_string();

    if let Some(config) = src_remote {
        let remote_name = create_temp_remote("src", &config)?;
        let src_fs = format!("{}:{}", remote_name, src_full_path);

        let result = librclone::rpc(
            "sync/copy",
            &serde_json::json!({
                "srcFs": src_fs,
                "dstFs": temp_path,
                "_async": false,
            })
            .to_string(),
        );

        delete_temp_remote(&remote_name);
        result.map_err(|e| AppError::command(format!("Download from storage failed: {}", e)))?;
    } else {
        // Local storage - just copy
        let status = tokio::process::Command::new("rsync")
            .args(["-av", &src_full_path, &temp_path])
            .status()
            .await
            .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;

        if !status.success() {
            let _ = tokio::fs::remove_dir_all(&temp_dir).await;
            return Err(AppError::command("Copy from local storage failed"));
        }
    }

    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Uploading to SSH host...".to_string()),
            ..Default::default()
        },
    );

    // Step 2: Upload from temp to SSH using rsync
    let ssh = get_endpoint_ssh_spec(&dest_endpoint).await?;
    let ssh_wrapper = build_rsync_ssh_wrapper(&ssh)?;

    let dst_path = if task.dest_path.starts_with('/') || task.dest_path.starts_with('~') {
        task.dest_path.clone()
    } else {
        format!("~/{}", task.dest_path)
    };

    // Get source filename
    let source_name = std::path::Path::new(&task.source_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();

    // Construct final destination path
    let final_dst_path = if !source_name.is_empty() && !source_name.starts_with('.') {
        if dst_path.ends_with('/') {
            format!("{}{}", dst_path, source_name)
        } else {
            format!("{}/{}", dst_path, source_name)
        }
    } else {
        dst_path
    };

    // Ensure destination directory exists
    let mkdir_cmd = format!(
        r#"mkdir -p "$(dirname '{}')""#,
        final_dst_path.replace('\'', "'\\''")
    );
    let mut ssh_cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        ssh_cmd.arg(arg);
    }
    ssh_cmd.arg(ssh.target());
    ssh_cmd.arg(&mkdir_cmd);
    let _ = ssh_cmd.output().await;

    // Determine upload source
    let upload_src = if source_name.is_empty() || source_name.starts_with('.') {
        format!("{}/", temp_path.trim_end_matches('/'))
    } else {
        let staged = temp_dir.join(&source_name);
        if staged.exists() {
            staged.to_string_lossy().to_string()
        } else {
            format!("{}/", temp_path.trim_end_matches('/'))
        }
    };

    let remote_dst = format!("{}@{}:{}", ssh.user, ssh.host, escape_rsync_remote_path(&final_dst_path));

    let mut upload_args = vec![
        "-avz".to_string(),
        "--info=progress2".to_string(),
        "-e".to_string(),
        ssh_wrapper.to_string_lossy().to_string(),
    ];

    if task.operation == TransferOperation::Sync {
        upload_args.push("--delete".to_string());
    }

    upload_args.push(upload_src);
    upload_args.push(remote_dst);

    let result = run_rsync_transfer(&ssh_wrapper, upload_args, &task.id, app).await;

    // Cleanup temp
    let _ = tokio::fs::remove_dir_all(&temp_dir).await;

    result?;

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            bytes_done: 1,
            bytes_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

/// Execute a unified transfer using endpoints
///
/// Uses rsync for SSH-based endpoints (Host, Vast, Local) and rclone for
/// cloud storage backends (Google Drive, Cloudflare R2, GCS, SMB).
pub async fn execute_unified_transfer(
    task: &TransferTask,
    storage_store: &StorageStore,
    app: &AppHandle,
) -> Result<(), AppError> {
    let source_endpoint = task.get_source_endpoint();
    let dest_endpoint = task.get_dest_endpoint();

    // For Vast instances, require them to be running
    match &source_endpoint {
        TransferEndpoint::Vast { instance_id } => {
            if !is_vast_instance_running(*instance_id).await.unwrap_or(false) {
                return Err(AppError::invalid_input(format!(
                    "Vast instance {} is not running. Please start the instance first.",
                    instance_id
                )));
            }
        }
        _ => {}
    }
    match &dest_endpoint {
        TransferEndpoint::Vast { instance_id } => {
            if !is_vast_instance_running(*instance_id).await.unwrap_or(false) {
                return Err(AppError::invalid_input(format!(
                    "Vast instance {} is not running. Please start the instance first.",
                    instance_id
                )));
            }
        }
        _ => {}
    }

    // Decide which transfer method to use:
    // - If both endpoints are SSH-based (Host, Vast) or Local, use rsync
    // - If either endpoint is cloud Storage, use rclone (possibly with local staging)
    if should_use_rsync(&source_endpoint, &dest_endpoint) {
        eprintln!("[transfer] Using rsync for SSH/local transfer");
        emit_transfer_progress(
            app,
            &task.id,
            TransferProgress {
                status_message: Some("Using rsync for SSH/local transfer".to_string()),
                ..Default::default()
            },
        );
        return execute_rsync_transfer(task, app).await;
    }

    // Check for mixed transfers: SSH-based endpoint <-> Storage
    // These need to stage through local temp directory
    let src_is_ssh = is_ssh_endpoint(&source_endpoint);
    let dst_is_ssh = is_ssh_endpoint(&dest_endpoint);
    let src_is_storage = matches!(&source_endpoint, TransferEndpoint::Storage { .. });
    let dst_is_storage = matches!(&dest_endpoint, TransferEndpoint::Storage { .. });

    if src_is_ssh && dst_is_storage {
        // SSH -> Storage: download from SSH to temp, then upload to storage via rclone
        eprintln!("[transfer] Mixed transfer: SSH -> Storage (staging through local)");
        emit_transfer_progress(
            app,
            &task.id,
            TransferProgress {
                status_message: Some("SSH → Storage (staging through local)".to_string()),
                ..Default::default()
            },
        );
        return execute_ssh_to_storage_transfer(task, storage_store, app).await;
    }

    if src_is_storage && dst_is_ssh {
        // Storage -> SSH: download from storage to temp via rclone, then upload to SSH
        eprintln!("[transfer] Mixed transfer: Storage -> SSH (staging through local)");
        emit_transfer_progress(
            app,
            &task.id,
            TransferProgress {
                status_message: Some("Storage → SSH (staging through local)".to_string()),
                ..Default::default()
            },
        );
        return execute_storage_to_ssh_transfer(task, storage_store, app).await;
    }

    // Otherwise, use rclone for Local <-> Storage or Storage <-> Storage transfers
    eprintln!("[transfer] Using rclone for cloud storage transfer");
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            status_message: Some("Using rclone for cloud storage transfer".to_string()),
            ..Default::default()
        },
    );

    // Build source and destination paths
    let (src_remote, src_path) = build_endpoint_spec(&source_endpoint, &task.source_path, storage_store).await?;
    let (dst_remote, dst_path) = build_endpoint_spec(&dest_endpoint, &task.dest_path, storage_store).await?;

    // Get source name for destination path construction
    let source_name = std::path::Path::new(&task.source_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();

    // Create temporary remotes if needed
    let src_remote_name = if let Some(config) = src_remote {
        Some(create_temp_remote("src", &config)?)
    } else {
        None
    };

    let dst_remote_name = if let Some(config) = dst_remote {
        Some(create_temp_remote("dst", &config)?)
    } else {
        None
    };

    // Emit starting progress
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Starting transfer...".to_string()),
            ..Default::default()
        },
    );

    // Detect if source path looks like a file (has an extension and doesn't end with /)
    // This heuristic helps us choose between sync/copy (for directories) and
    // operations/copyfile (for single files)
    let source_looks_like_file = {
        let path = std::path::Path::new(&task.source_path);
        !task.source_path.ends_with('/')
            && path.extension().is_some()
            && !source_name.is_empty()
    };

    // For file-to-file transfers, destination should already specify the file
    // For directory transfers, we need to append the source folder name
    let final_dst_path = if source_looks_like_file {
        // File transfer: check if destination already ends with filename
        let dst_ends_with_source_name = dst_path.ends_with(&source_name)
            || dst_path.ends_with(&format!("/{}", source_name));

        if dst_ends_with_source_name {
            // Destination already specifies the target file
            dst_path.clone()
        } else if dst_path.ends_with('/') {
            // Destination is a directory, append filename
            format!("{}{}", dst_path, source_name)
        } else {
            // Destination doesn't have filename, append it
            format!("{}/{}", dst_path, source_name)
        }
    } else {
        // Directory transfer: append source folder name to destination
        if !source_name.is_empty() && !source_name.starts_with('.') {
            if dst_path.ends_with('/') {
                format!("{}{}", dst_path, source_name)
            } else {
                format!("{}/{}", dst_path, source_name)
            }
        } else {
            dst_path.clone()
        }
    };

    let src_fs = match &src_remote_name {
        Some(name) => format!("{}:{}", name, src_path),
        None => src_path.clone(),
    };

    let dst_fs = match &dst_remote_name {
        Some(name) => format!("{}:{}", name, final_dst_path),
        None => final_dst_path.clone(),
    };

    eprintln!("[transfer] src_fs: {}, dst_fs: {}, is_file: {}", src_fs, dst_fs, source_looks_like_file);

    // Choose the appropriate rclone method based on whether source is a file or directory
    let (rpc_method, sync_opts) = if source_looks_like_file {
        // For single file transfers, use sync/copy with the parent directory as source
        // and a filter to only copy the specific file.
        // The destination is also the parent directory (file will be copied with same name)
        let src_parent = std::path::Path::new(&src_path)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "/".to_string());

        let dst_parent = std::path::Path::new(&final_dst_path)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "/".to_string());

        // Handle empty parent paths
        let src_parent = if src_parent.is_empty() { "/".to_string() } else { src_parent };
        let dst_parent = if dst_parent.is_empty() { "/".to_string() } else { dst_parent };

        let src_fs_dir = match &src_remote_name {
            Some(name) => format!("{}:{}", name, src_parent),
            None => src_parent,
        };

        let dst_fs_dir = match &dst_remote_name {
            Some(name) => format!("{}:{}", name, dst_parent),
            None => dst_parent,
        };

        eprintln!("[transfer] file copy: src_dir={}, dst_dir={}, file={}", src_fs_dir, dst_fs_dir, source_name);

        // Use IncludeRule with the exact filename to filter
        let opts = serde_json::json!({
            "srcFs": src_fs_dir,
            "dstFs": dst_fs_dir,
            "_async": true,
            "copyLinks": true,
            "_filter": {
                "IncludeRule": [format!("/{}", source_name)],
                "ExcludeRule": ["*"]
            }
        });
        ("sync/copy", opts)
    } else {
        // Use sync/copy for directory transfers
        let rpc = match task.operation {
            TransferOperation::Copy | TransferOperation::Move => "sync/copy",
            TransferOperation::Sync => "sync/sync",
            TransferOperation::SyncNoDelete => "sync/copy",
        };

        let mut opts = serde_json::json!({
            "srcFs": src_fs,
            "dstFs": dst_fs,
            "_async": true,
            "copyLinks": true,
        });

        if task.operation == TransferOperation::Sync {
            opts["deleteMode"] = serde_json::json!("sync");
        }
        (rpc, opts)
    };

    let result = librclone::rpc(rpc_method, &sync_opts.to_string());

    let job_id = match result {
        Ok(response) => {
            eprintln!("[transfer] rclone response: {}", response);
            // Parse job ID from response
            let parsed: serde_json::Value = serde_json::from_str(&response)
                .map_err(|e| AppError::command(format!("Failed to parse rclone response: {}", e)))?;
            let jid = parsed["jobid"].as_i64().unwrap_or(0);
            eprintln!("[transfer] job_id: {}", jid);
            jid
        }
        Err(e) => {
            eprintln!("[transfer] rclone error: {}", e);
            // Clean up remotes on error
            if let Some(name) = &src_remote_name {
                delete_temp_remote(name);
            }
            if let Some(name) = &dst_remote_name {
                delete_temp_remote(name);
            }
            return Err(AppError::command(format!("Transfer failed: {}", e)));
        }
    };

    // Poll for progress until job completes
    loop {
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;

        // Get job status
        let status_result = librclone::rpc(
            "job/status",
            &serde_json::json!({ "jobid": job_id }).to_string(),
        );

        match status_result {
            Ok(status_str) => {
                let status: serde_json::Value = serde_json::from_str(&status_str).unwrap_or_default();
                eprintln!("[transfer] job status: {}", status);

                let finished = status["finished"].as_bool().unwrap_or(false);
                let success = status["success"].as_bool().unwrap_or(false);
                let error_str = status["error"].as_str().unwrap_or("");

                // Extract progress info
                let bytes_done = status["bytes"].as_u64().unwrap_or(0);
                let bytes_total = status["totalBytes"].as_u64().unwrap_or(0);
                let speed = status["speed"].as_f64().unwrap_or(0.0) as u64;
                let eta = status["eta"].as_f64().map(|e| e as u64);

                // Get current file being transferred
                let current_file = status["transferring"]
                    .as_array()
                    .and_then(|arr| arr.first())
                    .and_then(|t| t["name"].as_str())
                    .map(|s| s.to_string());

                // Calculate files progress
                let transfers = status["transfers"].as_u64().unwrap_or(0);
                let checks = status["checks"].as_u64().unwrap_or(0);
                let files_done = transfers + checks;
                let files_total = status["totalTransfers"].as_u64().unwrap_or(0)
                    + status["totalChecks"].as_u64().unwrap_or(0);

                // Emit progress
                emit_transfer_progress(
                    app,
                    &task.id,
                    TransferProgress {
                        files_total: if files_total > 0 { files_total } else { 1 },
                        files_done,
                        bytes_total,
                        bytes_done,
                        speed_bps: speed,
                        eta_seconds: eta,
                        current_file,
                        ..Default::default()
                    },
                );

                if finished {
                    if !success && !error_str.is_empty() {
                        // Clean up remotes
                        if let Some(name) = &src_remote_name {
                            delete_temp_remote(name);
                        }
                        if let Some(name) = &dst_remote_name {
                            delete_temp_remote(name);
                        }
                        return Err(AppError::command(format!("Transfer failed: {}", error_str)));
                    }
                    break;
                }
            }
            Err(e) => {
                // Job might have completed, check if it's just not found
                eprintln!("[transfer] Error getting job status: {}", e);
                break;
            }
        }
    }

    // Clean up temporary remotes
    if let Some(name) = src_remote_name {
        delete_temp_remote(&name);
    }
    if let Some(name) = dst_remote_name {
        delete_temp_remote(&name);
    }

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            bytes_done: 1,
            bytes_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

// ============================================================
// Tauri Commands
// ============================================================

#[tauri::command]
pub async fn transfer_list(app: AppHandle) -> Result<Vec<TransferTask>, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    Ok(store.list().await)
}

#[tauri::command]
pub async fn transfer_get(app: AppHandle, id: String) -> Result<TransferTask, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    store
        .get(&id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Transfer not found: {}", id)))
}

#[tauri::command]
pub async fn transfer_create(
    app: AppHandle,
    input: TransferCreateInput,
) -> Result<Vec<TransferTask>, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    let tasks = store.create(input).await?;

    // Try to start the queue processor
    let app_clone = app.clone();
    tokio::spawn(async move {
        process_transfer_queue(app_clone).await;
    });

    Ok(tasks)
}

#[tauri::command]
pub async fn transfer_cancel(app: AppHandle, id: String) -> Result<(), AppError> {
    let store = app.state::<Arc<TransferStore>>();
    store.cancel(&id).await
}

#[tauri::command]
pub async fn transfer_clear_completed(app: AppHandle) -> Result<(), AppError> {
    let store = app.state::<Arc<TransferStore>>();
    store.clear_completed().await
}

/// Create a unified transfer supporting any endpoint type
#[tauri::command]
pub async fn transfer_create_unified(
    app: AppHandle,
    input: UnifiedTransferInput,
) -> Result<Vec<TransferTask>, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    let tasks = store.create_unified(input).await?;

    // Try to start the queue processor
    let app_clone = app.clone();
    tokio::spawn(async move {
        process_transfer_queue(app_clone).await;
    });

    Ok(tasks)
}

/// Process the transfer queue (runs one task at a time)
async fn process_transfer_queue(app: AppHandle) {
    let transfer_store = app.state::<Arc<TransferStore>>();
    let storage_store = app.state::<Arc<StorageStore>>();

    // Check if already running
    if transfer_store.is_running().await {
        return;
    }

    loop {
        // Get next queued task
        let task_id = match transfer_store.pop_queue().await {
            Some(id) => id,
            None => break, // No more tasks
        };

        // Mark as running
        transfer_store.set_running(Some(task_id.clone())).await;
        let _ = transfer_store
            .update_status(&task_id, TransferStatus::Running)
            .await;

        // Get task details
        let task = match transfer_store.get(&task_id).await {
            Some(t) => t,
            None => continue,
        };

        // Use unified transfer execution if we have endpoint info
        let result = if task.source_endpoint.is_some() || task.dest_endpoint.is_some() {
            // New unified execution
            execute_unified_transfer(&task, &storage_store, &app).await
        } else {
            // Legacy execution - get storages
            let source = match storage_store.get(&task.source_storage_id).await {
                Some(s) => s,
                None => {
                    let _ = transfer_store
                        .set_error(&task_id, "Source storage not found".to_string())
                        .await;
                    transfer_store.set_running(None).await;
                    continue;
                }
            };

            let dest = match storage_store.get(&task.dest_storage_id).await {
                Some(s) => s,
                None => {
                    let _ = transfer_store
                        .set_error(&task_id, "Destination storage not found".to_string())
                        .await;
                    transfer_store.set_running(None).await;
                    continue;
                }
            };

            execute_transfer(&task, &source, &dest, &app).await
        };

        match result {
            Ok(()) => {
                let _ = transfer_store
                    .update_status(&task_id, TransferStatus::Completed)
                    .await;
            }
            Err(e) => {
                let _ = transfer_store.set_error(&task_id, e.to_string()).await;
            }
        }

        // Clear running
        transfer_store.set_running(None).await;
    }
}
