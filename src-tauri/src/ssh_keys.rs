use std::path::PathBuf;

use serde::Serialize;
use tokio::process::Command;

use crate::{
  error::AppError,
  ssh::{ensure_bin, run_checked},
};

fn expand_tilde(path: &str) -> PathBuf {
  let p = path.trim();
  if p == "~" {
    return dirs::home_dir().unwrap_or_else(|| PathBuf::from("~"));
  }
  if let Some(rest) = p.strip_prefix("~/") {
    let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("~"));
    return home.join(rest);
  }
  PathBuf::from(p)
}

#[derive(Debug, Clone, Serialize)]
pub struct SshKeyInfo {
  pub private_key_path: String,
  pub public_key_path: String,
  pub public_key: String,
}

pub async fn read_public_key(private_key_path: String) -> Result<String, AppError> {
  ensure_bin("ssh-keygen").await?;

  let priv_path = expand_tilde(&private_key_path);
  if !priv_path.exists() {
    return Err(AppError::invalid_input(format!(
      "SSH private key not found: {}",
      priv_path.display()
    )));
  }

  let pub_path = PathBuf::from(format!("{}.pub", priv_path.to_string_lossy()));
  if pub_path.exists() {
    let s = tokio::fs::read_to_string(&pub_path).await?;
    return Ok(s.trim().to_string());
  }

  let mut c = Command::new("ssh-keygen");
  c.arg("-y");
  c.arg("-f");
  c.arg(&priv_path);
  let out = run_checked(c).await?;
  Ok(out.stdout.trim().to_string())
}

pub async fn generate_key(path: String, comment: Option<String>) -> Result<SshKeyInfo, AppError> {
  ensure_bin("ssh-keygen").await?;

  let priv_path = expand_tilde(&path);
  if priv_path.as_os_str().is_empty() {
    return Err(AppError::invalid_input("path is required"));
  }
  if let Some(parent) = priv_path.parent() {
    tokio::fs::create_dir_all(parent).await?;
  }
  if priv_path.exists() {
    return Err(AppError::invalid_input(format!(
      "Target private key already exists: {}",
      priv_path.display()
    )));
  }

  // Ensure it's under ~/.ssh for safety.
  let home = dirs::home_dir().ok_or_else(|| AppError::io("Cannot resolve home directory"))?;
  let ssh_dir = home.join(".ssh");
  if !priv_path.starts_with(&ssh_dir) {
    return Err(AppError::invalid_input(format!(
      "For safety, key path must be under {}",
      ssh_dir.display()
    )));
  }

  let comment = comment.unwrap_or_else(|| "doppio".to_string());

  let mut c = Command::new("ssh-keygen");
  c.arg("-t");
  c.arg("ed25519");
  c.arg("-f");
  c.arg(&priv_path);
  c.arg("-N");
  c.arg("");
  c.arg("-C");
  c.arg(comment);
  run_checked(c).await?;

  let pub_path = PathBuf::from(format!("{}.pub", priv_path.to_string_lossy()));
  if !pub_path.exists() {
    return Err(AppError::io("ssh-keygen did not create .pub file"));
  }
  let public_key = tokio::fs::read_to_string(&pub_path).await?.trim().to_string();

  Ok(SshKeyInfo {
    private_key_path: priv_path.to_string_lossy().to_string(),
    public_key_path: pub_path.to_string_lossy().to_string(),
    public_key,
  })
}


