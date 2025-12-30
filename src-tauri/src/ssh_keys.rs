use std::path::PathBuf;

use serde::Serialize;
use tokio::process::Command;

use crate::{
    config::doppio_data_dir,
    error::AppError,
    secrets,
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

fn looks_like_private_key_material(s: &str) -> bool {
    let t = s.trim();
    if t.is_empty() {
        return false;
    }
    if !t.contains("PRIVATE KEY") {
        return false;
    }
    t.contains("-----BEGIN") || t.contains("OPENSSH PRIVATE KEY")
}

fn extract_single_secret_ref_name(template: &str) -> Option<String> {
    let t = template.trim();
    let inner = t.strip_prefix("${secret:")?.strip_suffix('}')?;
    let name = inner.trim();
    if name.is_empty() {
        None
    } else {
        Some(name.to_string())
    }
}

fn sanitize_filename_component(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' | '.' => c,
            _ => '_',
        })
        .collect()
}

async fn write_private_key_material(path: &PathBuf, material: &str) -> Result<(), AppError> {
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }

    let content = material.trim().to_string() + "\n";
    tokio::fs::write(path, content).await?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let perms = std::fs::Permissions::from_mode(0o600);
        tokio::fs::set_permissions(path, perms).await?;
    }

    Ok(())
}

/// Resolve a private key input to a filesystem path.
///
/// Supports:
/// - normal paths (with `~` expansion)
/// - `${secret:name}` templates (resolved via the secrets store)
/// - raw private key material (PEM/OpenSSH blocks), which is materialized under `doppio_data_dir()/ssh_keys/`
pub async fn materialize_private_key_path(input: &str) -> Result<PathBuf, AppError> {
    let raw = input.trim();
    if raw.is_empty() {
        return Err(AppError::invalid_input("SSH private key is required"));
    }

    let resolved = secrets::interpolate_secrets(raw)?.trim().to_string();
    if looks_like_private_key_material(&resolved) {
        let dir = doppio_data_dir().join("ssh_keys");
        let file_name = extract_single_secret_ref_name(raw)
            .map(|n| format!("secret_{}.key", sanitize_filename_component(&n)))
            .unwrap_or_else(|| "materialized.key".to_string());
        let path = dir.join(file_name);
        write_private_key_material(&path, &resolved).await?;
        return Ok(path);
    }

    let mut path = expand_tilde(&resolved);
    if path
        .extension()
        .and_then(|e| e.to_str())
        .is_some_and(|e| e == "pub")
    {
        let p = resolved.trim_end_matches(".pub");
        path = expand_tilde(p);
    }
    if !path.exists() {
        return Err(AppError::invalid_input(format!(
            "SSH private key not found: {}",
            path.display()
        )));
    }
    Ok(path)
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

pub async fn read_private_key(private_key_path: String) -> Result<String, AppError> {
    let priv_path = expand_tilde(&private_key_path);
    if !priv_path.exists() {
        return Err(AppError::invalid_input(format!(
            "SSH private key not found: {}",
            priv_path.display()
        )));
    }

    if let Some(ext) = priv_path.extension() {
        if ext == "pub" {
            return Err(AppError::invalid_input(
                "Private key path must not be a .pub file",
            ));
        }
    }

    let home = dirs::home_dir().ok_or_else(|| AppError::io("Cannot resolve home directory"))?;
    let ssh_dir = home.join(".ssh");
    if !priv_path.starts_with(&ssh_dir) {
        return Err(AppError::invalid_input(format!(
            "For safety, key path must be under {}",
            ssh_dir.display()
        )));
    }

    let s = tokio::fs::read_to_string(&priv_path).await?;
    Ok(s.trim().to_string())
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
    let public_key = tokio::fs::read_to_string(&pub_path)
        .await?
        .trim()
        .to_string();

    Ok(SshKeyInfo {
        private_key_path: priv_path.to_string_lossy().to_string(),
        public_key_path: pub_path.to_string_lossy().to_string(),
        public_key,
    })
}
