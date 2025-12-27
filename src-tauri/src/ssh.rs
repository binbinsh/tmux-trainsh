use std::path::Path;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::process::Command;
use tokio::time::timeout;

use crate::error::AppError;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SshSpec {
  pub host: String,
  pub port: i64,
  pub user: String,
  #[serde(alias = "key_path")]
  pub key_path: Option<String>,
  #[serde(alias = "extra_args", default)]
  pub extra_args: Vec<String>,
}

impl SshSpec {
  pub fn validate(&self) -> Result<(), AppError> {
    if self.host.trim().is_empty() {
      return Err(AppError::invalid_input("ssh.host is required"));
    }
    if !(1..=65535).contains(&self.port) {
      return Err(AppError::invalid_input("ssh.port must be in [1, 65535]"));
    }
    if self.user.trim().is_empty() {
      return Err(AppError::invalid_input("ssh.user is required"));
    }
    if let Some(p) = &self.key_path {
      if !p.trim().is_empty() && !Path::new(p).exists() {
        return Err(AppError::invalid_input(format!("SSH key not found: {p}")));
      }
    }
    Ok(())
  }

  pub fn target(&self) -> String {
    format!("{}@{}", self.user.trim(), self.host.trim())
  }

  pub fn common_ssh_options(&self) -> Vec<String> {
    self.build_ssh_options(true)
  }

  /// SSH options for interactive terminal sessions (no BatchMode)
  pub fn interactive_ssh_options(&self) -> Vec<String> {
    self.build_ssh_options(false)
  }

  fn build_ssh_options(&self, batch_mode: bool) -> Vec<String> {
    let mut args: Vec<String> = vec![
      "-p".to_string(),
      self.port.to_string(),
    ];
    if batch_mode {
      args.push("-o".to_string());
      args.push("BatchMode=yes".to_string());
    }
    args.extend([
      "-o".to_string(),
      "ConnectTimeout=15".to_string(),
      "-o".to_string(),
      "ServerAliveInterval=30".to_string(),
      "-o".to_string(),
      "ServerAliveCountMax=4".to_string(),
      "-o".to_string(),
      "StrictHostKeyChecking=accept-new".to_string(),
    ]);
    if let Some(k) = &self.key_path {
      if !k.trim().is_empty() {
        args.push("-i".to_string());
        args.push(k.clone());
      }
    }
    // Let callers override via extra args (last one wins).
    args.extend(self.extra_args.clone());
    args
  }

  pub fn common_scp_options(&self) -> Vec<String> {
    let mut args: Vec<String> = vec![
      "-P".to_string(),
      self.port.to_string(),
      "-o".to_string(),
      "BatchMode=yes".to_string(),
      "-o".to_string(),
      "ConnectTimeout=10".to_string(),
      "-o".to_string(),
      "StrictHostKeyChecking=accept-new".to_string(),
    ];
    if let Some(k) = &self.key_path {
      if !k.trim().is_empty() {
        args.push("-i".to_string());
        args.push(k.clone());
      }
    }
    args.extend(self.extra_args.clone());
    args
  }
}

pub struct CmdOut {
  pub code: Option<i32>,
  pub stdout: String,
  pub stderr: String,
}

/// Run a command with a default 60-second timeout
pub async fn run_checked(cmd: Command) -> Result<CmdOut, AppError> {
  run_checked_with_timeout(cmd, Duration::from_secs(60)).await
}

/// Run a command with a custom timeout
pub async fn run_checked_with_timeout(mut cmd: Command, time_limit: Duration) -> Result<CmdOut, AppError> {
  let result = timeout(time_limit, cmd.output()).await;
  
  let out = match result {
    Ok(Ok(output)) => output,
    Ok(Err(e)) => return Err(AppError::command(format!("Command execution error: {}", e))),
    Err(_) => return Err(AppError::command(format!("Command timed out after {} seconds", time_limit.as_secs()))),
  };
  
  let stdout = String::from_utf8_lossy(&out.stdout).to_string();
  let stderr = String::from_utf8_lossy(&out.stderr).to_string();
  if !out.status.success() {
    let code = out.status.code();
    return Err(AppError::command(format!(
      "Command failed (code={code:?}): {stdout}{stderr}"
    )));
  }
  Ok(CmdOut {
    code: out.status.code(),
    stdout,
    stderr,
  })
}

pub async fn ensure_bin(name: &str) -> Result<(), AppError> {
  which::which(name).map_err(|_| AppError::command(format!("Required binary not found: {name}")))?;
  Ok(())
}


