//! Tmux session operations

use crate::error::AppError;
use crate::host;
use std::time::Duration;

/// Create a new tmux session
pub async fn new_session(
    host_id: &str,
    session_name: &str,
    command: Option<&str>,
    workdir: Option<&str>,
) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let mut tmux_cmd = format!("tmux new-session -d -s {}", session_name);

    if let Some(wd) = workdir {
        tmux_cmd.push_str(&format!(" -c {}", wd));
    }

    if let Some(cmd) = command {
        tmux_cmd.push_str(&format!(" '{}'", cmd.replace('\'', "'\\''")));
    }

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&tmux_cmd);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to create tmux session: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        // Ignore "duplicate session" errors
        if !stderr.contains("duplicate session") {
            return Err(AppError::command(format!(
                "Failed to create tmux session: {stderr}"
            )));
        }
    }

    Ok(())
}

/// Send keys to a tmux session
pub async fn send_keys(host_id: &str, session_name: &str, keys: &str) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let tmux_cmd = format!(
        "tmux send-keys -t {} '{}' Enter",
        session_name,
        keys.replace('\'', "'\\''")
    );

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&tmux_cmd);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to send keys: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(AppError::command(format!("Failed to send keys: {stderr}")));
    }

    Ok(())
}

/// Capture tmux pane content
pub async fn capture_pane(
    host_id: &str,
    session_name: &str,
    lines: Option<i64>,
) -> Result<String, AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let tmux_cmd = if let Some(n) = lines {
        format!("tmux capture-pane -t {} -p -S {}", session_name, n)
    } else {
        format!("tmux capture-pane -t {} -p", session_name)
    };

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&tmux_cmd);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to capture pane: {e}")))?;

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Kill a tmux session
pub async fn kill_session(host_id: &str, session_name: &str) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let tmux_cmd = format!("tmux kill-session -t {} 2>/dev/null || true", session_name);

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&tmux_cmd);

    let _ = cmd.output().await; // Ignore errors - session might not exist

    Ok(())
}

/// Check if a tmux session exists
pub async fn session_exists(host_id: &str, session_name: &str) -> Result<bool, AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let tmux_cmd = format!(
        "tmux has-session -t {} 2>/dev/null && echo yes || echo no",
        session_name
    );

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&tmux_cmd);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to check tmux session: {e}")))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(stdout.trim() == "yes")
}
