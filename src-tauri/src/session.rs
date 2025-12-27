use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use tauri::AppHandle;
use uuid::Uuid;

use crate::config::doppio_data_dir;
use crate::error::AppError;
use crate::host::{get_host, HostStatus};
use crate::sync::{self, SyncConfig};

// ============================================================
// Types
// ============================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionStatus {
  Created,
  Uploading,
  Running,
  Completed,
  Failed,
  Stopped,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SyncMode {
  Rsync,
  Full,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SourceConfig {
  pub local_path: String,
  pub use_gitignore: bool,
  pub extra_excludes: Vec<String>,
  pub sync_mode: SyncMode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DataConfig {
  pub enabled: bool,
  pub local_path: Option<String>,
  pub remote_path: Option<String>,
  pub skip_existing: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EnvConfig {
  pub requirements_txt: Option<String>,
  pub conda_env: Option<String>,
  pub env_vars: std::collections::HashMap<String, String>,
  pub setup_commands: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunConfig {
  pub command: String,
  pub workdir: Option<String>,
  pub tmux_session: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputConfig {
  pub model_path: Option<String>,
  pub log_path: Option<String>,
  pub auto_download: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MonitorConfig {
  pub parse_stdout: bool,
  pub tensorboard_dir: Option<String>,
  pub auto_shutdown_timeout: Option<i64>,
  pub completion_patterns: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionConfig {
  pub name: String,
  pub host_id: String,
  pub source: SourceConfig,
  pub data: DataConfig,
  pub env: EnvConfig,
  pub run: RunConfig,
  pub output: OutputConfig,
  pub monitor: MonitorConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Session {
  pub id: String,
  pub name: String,
  pub host_id: String,
  pub host_name: String,
  pub status: SessionStatus,
  pub config: SessionConfig,
  // Runtime info
  pub remote_workdir: Option<String>,
  pub remote_job_dir: Option<String>,
  pub remote_log_path: Option<String>,
  pub tmux_session: Option<String>,
  // Timestamps
  pub created_at: String,
  pub started_at: Option<String>,
  pub completed_at: Option<String>,
  // Exit info
  pub exit_code: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuMetrics {
  pub index: i32,
  pub name: String,
  pub utilization: f64,
  pub memory_used: f64,
  pub memory_total: f64,
  pub temperature: f64,
  pub power: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrainingMetrics {
  pub step: Option<i64>,
  pub total_steps: Option<i64>,
  pub loss: Option<f64>,
  pub learning_rate: Option<f64>,
  pub epoch: Option<i64>,
  pub samples_per_second: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionMetrics {
  pub gpu: Vec<GpuMetrics>,
  pub training: Option<TrainingMetrics>,
  pub timestamp: String,
}

// ============================================================
// Storage
// ============================================================

fn sessions_dir() -> PathBuf {
  doppio_data_dir().join("sessions")
}

fn session_path(id: &str) -> PathBuf {
  sessions_dir().join(format!("{}.json", id))
}

pub async fn list_sessions() -> Result<Vec<Session>, AppError> {
  let dir = sessions_dir();
  if !dir.exists() {
    return Ok(vec![]);
  }

  let mut sessions = vec![];
  let mut entries = tokio::fs::read_dir(&dir).await?;
  while let Some(entry) = entries.next_entry().await? {
    let path = entry.path();
    if path.extension().map_or(false, |e| e == "json") {
      let data = tokio::fs::read_to_string(&path).await?;
      if let Ok(session) = serde_json::from_str::<Session>(&data) {
        sessions.push(session);
      }
    }
  }

  // Sort by created_at descending
  sessions.sort_by(|a, b| b.created_at.cmp(&a.created_at));
  Ok(sessions)
}

pub async fn get_session(id: &str) -> Result<Session, AppError> {
  let path = session_path(id);
  if !path.exists() {
    return Err(AppError::not_found(format!("Session not found: {}", id)));
  }
  let data = tokio::fs::read_to_string(&path).await?;
  let session: Session = serde_json::from_str(&data)
    .map_err(|e| AppError::io(format!("Invalid session JSON: {}", e)))?;
  Ok(session)
}

pub async fn save_session(session: &Session) -> Result<(), AppError> {
  let dir = sessions_dir();
  tokio::fs::create_dir_all(&dir).await?;
  let path = session_path(&session.id);
  let data = serde_json::to_string_pretty(session)
    .map_err(|e| AppError::io(format!("Failed to serialize session: {}", e)))?;
  tokio::fs::write(&path, format!("{}\n", data)).await?;
  Ok(())
}

pub async fn delete_session(id: &str) -> Result<(), AppError> {
  let path = session_path(id);
  if path.exists() {
    tokio::fs::remove_file(&path).await?;
  }
  Ok(())
}

// ============================================================
// Operations
// ============================================================

pub async fn create_session(config: SessionConfig) -> Result<Session, AppError> {
  let host = get_host(&config.host_id).await?;
  let now = chrono::Utc::now().to_rfc3339();
  let id = Uuid::new_v4().to_string();

  let tmux_session = config.run.tmux_session.clone()
    .unwrap_or_else(|| format!("doppio-{}", &id[..8]));

  let session = Session {
    id,
    name: config.name.clone(),
    host_id: config.host_id.clone(),
    host_name: host.name.clone(),
    status: SessionStatus::Created,
    config,
    remote_workdir: None,
    remote_job_dir: None,
    remote_log_path: None,
    tmux_session: Some(tmux_session),
    created_at: now,
    started_at: None,
    completed_at: None,
    exit_code: None,
  };

  save_session(&session).await?;
  Ok(session)
}

pub async fn sync_session(id: &str, app: Option<&AppHandle>) -> Result<Session, AppError> {
  let mut session = get_session(id).await?;
  let host = get_host(&session.host_id).await?;

  if host.status != HostStatus::Online {
    return Err(AppError::invalid_input("Host is not online"));
  }

  let ssh = host.ssh.as_ref()
    .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;

  session.status = SessionStatus::Uploading;
  save_session(&session).await?;

  // Determine remote workdir
  let project_name = Path::new(&session.config.source.local_path)
    .file_name()
    .map(|n| n.to_string_lossy().to_string())
    .unwrap_or_else(|| "project".to_string());
  
  let remote_workdir = format!("/workspace/{}", project_name);
  session.remote_workdir = Some(remote_workdir.clone());

  // Create job directory for logs and metadata
  let job_dir = format!("/workspace/.doppio/jobs/{}", &session.id[..8]);
  session.remote_job_dir = Some(job_dir.clone());
  session.remote_log_path = Some(format!("{}/output.log", job_dir));
  
  save_session(&session).await?;

  // Sync source code using rclone
  let sync_config = SyncConfig {
    local_path: session.config.source.local_path.clone(),
    remote_path: remote_workdir.clone(),
    use_gitignore: session.config.source.use_gitignore,
    extra_excludes: session.config.source.extra_excludes.clone(),
    delete_remote: matches!(session.config.source.sync_mode, SyncMode::Full),
  };

  match sync::sync_to_remote(&session.id, ssh, &sync_config, app).await {
    Ok(_) => {
      session.status = SessionStatus::Created;
      save_session(&session).await?;
      Ok(session)
    }
    Err(e) => {
      session.status = SessionStatus::Failed;
      save_session(&session).await?;
      Err(e)
    }
  }
}

pub async fn sync_session_no_app(id: &str) -> Result<Session, AppError> {
  sync_session(id, None).await
}

pub async fn run_session(id: &str) -> Result<Session, AppError> {
  let mut session = get_session(id).await?;
  let host = get_host(&session.host_id).await?;

  if host.status != HostStatus::Online {
    return Err(AppError::invalid_input("Host is not online"));
  }

  let ssh = host.ssh.as_ref()
    .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;

  // Build the run command with logging
  let tmux_session = session.tmux_session.clone()
    .unwrap_or_else(|| format!("doppio-{}", &session.id[..8]));
  let job_dir = session.remote_job_dir.clone()
    .unwrap_or_else(|| format!("/workspace/.doppio/jobs/{}", &session.id[..8]));
  let log_path = session.remote_log_path.clone()
    .unwrap_or_else(|| format!("{}/output.log", job_dir));
  let workdir = session.remote_workdir.clone()
    .or_else(|| session.config.run.workdir.clone())
    .unwrap_or_else(|| "/workspace".to_string());

  // Create job directory and run command in tmux
  let setup_cmd = format!(
    "mkdir -p {} && cd {} && {} 2>&1 | tee {}; echo $? > {}/exit_code",
    job_dir,
    workdir,
    session.config.run.command,
    log_path,
    job_dir
  );

  // Execute via SSH in a new tmux session
  let full_cmd = format!(
    "tmux new-session -d -s {} '{}' || tmux send-keys -t {} '{}' Enter",
    tmux_session,
    setup_cmd,
    tmux_session,
    setup_cmd
  );

  // Run the SSH command
  let mut cmd = tokio::process::Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg(&full_cmd);

  let output = cmd.output().await
    .map_err(|e| AppError::command(format!("Failed to start SSH: {}", e)))?;

  if !output.status.success() {
    let stderr = String::from_utf8_lossy(&output.stderr);
    return Err(AppError::command(format!("Failed to start tmux session: {}", stderr)));
  }

  session.status = SessionStatus::Running;
  session.started_at = Some(chrono::Utc::now().to_rfc3339());
  session.tmux_session = Some(tmux_session);
  save_session(&session).await?;

  Ok(session)
}

pub async fn stop_session(id: &str) -> Result<Session, AppError> {
  let mut session = get_session(id).await?;
  let host = get_host(&session.host_id).await?;
  
  if let (Some(ssh), Some(tmux_session)) = (&host.ssh, &session.tmux_session) {
    // Send SIGTERM to all processes in the tmux session
    let kill_cmd = format!(
      "tmux send-keys -t {} C-c; sleep 1; tmux kill-session -t {} 2>/dev/null || true",
      tmux_session,
      tmux_session
    );

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
      cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&kill_cmd);

    let _ = cmd.output().await; // Ignore errors, session might already be dead
  }

  session.status = SessionStatus::Stopped;
  session.completed_at = Some(chrono::Utc::now().to_rfc3339());
  save_session(&session).await?;

  Ok(session)
}

pub async fn get_session_metrics(id: &str) -> Result<SessionMetrics, AppError> {
  let session = get_session(id).await?;
  let _host = get_host(&session.host_id).await?;

  // TODO: Implement actual metrics fetching via SSH
  Ok(SessionMetrics {
    gpu: vec![],
    training: None,
    timestamp: chrono::Utc::now().to_rfc3339(),
  })
}

pub async fn get_session_logs(id: &str, lines: usize) -> Result<Vec<String>, AppError> {
  let session = get_session(id).await?;
  let host = get_host(&session.host_id).await?;

  let ssh = match &host.ssh {
    Some(s) => s,
    None => return Ok(vec![]),
  };

  let log_path = match &session.remote_log_path {
    Some(p) => p,
    None => return Ok(vec![]),
  };

  // Tail the log file via SSH
  let tail_cmd = format!("tail -n {} {} 2>/dev/null || echo ''", lines, log_path);

  let mut cmd = tokio::process::Command::new("ssh");
  for arg in ssh.common_ssh_options() {
    cmd.arg(arg);
  }
  cmd.arg(ssh.target());
  cmd.arg(&tail_cmd);

  let output = cmd.output().await
    .map_err(|e| AppError::command(format!("Failed to fetch logs: {}", e)))?;

  let stdout = String::from_utf8_lossy(&output.stdout);
  let lines: Vec<String> = stdout.lines().map(|l| l.to_string()).collect();
  
  Ok(lines)
}

/// Download session outputs to local directory
pub async fn download_session_outputs(
  id: &str,
  local_dir: &str,
  app: Option<&AppHandle>,
) -> Result<(), AppError> {
  let session = get_session(id).await?;
  let host = get_host(&session.host_id).await?;

  let ssh = host.ssh.as_ref()
    .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;

  let remote_path = session.config.output.model_path.as_ref()
    .or(session.remote_workdir.as_ref())
    .ok_or_else(|| AppError::invalid_input("No output path configured"))?;

  sync::sync_from_remote(&session.id, ssh, remote_path, local_dir, app).await
}

