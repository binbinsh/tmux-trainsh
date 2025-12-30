//! SSH command execution

use std::collections::HashMap;
use std::time::Duration;

use crate::error::AppError;
use crate::host;

/// Special target value for local execution
pub const LOCAL_TARGET: &str = "__local__";

/// Check if target is local
pub fn is_local_target(target: &str) -> bool {
    target == LOCAL_TARGET
}

/// Execute command locally (no SSH)
pub async fn execute_local_command(
    command: &str,
    workdir: Option<&str>,
    env: &HashMap<String, String>,
) -> Result<Option<String>, AppError> {
    // Build command with workdir and environment
    let mut full_cmd = String::new();

    // Add environment variables
    for (key, value) in env {
        full_cmd.push_str(&format!("export {}={}; ", key, shell_escape(value)));
    }

    // Add workdir
    if let Some(wd) = workdir {
        full_cmd.push_str(&format!("cd {} && ", shell_escape(wd)));
    }

    full_cmd.push_str(command);

    // Execute locally using sh
    let mut cmd = tokio::process::Command::new("sh");
    cmd.arg("-c");
    cmd.arg(&full_cmd);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to execute local command: {e}")))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    // Combine stdout and stderr for complete output
    let combined_output = if !stdout.is_empty() && !stderr.is_empty() {
        format!("{}\n--- stderr ---\n{}", stdout, stderr)
    } else if !stdout.is_empty() {
        stdout
    } else if !stderr.is_empty() {
        format!("(stderr only)\n{}", stderr)
    } else {
        String::new()
    };

    if !output.status.success() {
        return Err(AppError::command(format!(
            "Local command failed with exit code {:?}: {}",
            output.status.code(),
            if combined_output.is_empty() {
                "(no output)".to_string()
            } else {
                combined_output
            }
        )));
    }

    Ok(if combined_output.is_empty() {
        None
    } else {
        Some(combined_output)
    })
}

/// Execute SSH command on remote host
pub async fn execute_command(
    host_id: &str,
    command: &str,
    workdir: Option<&str>,
    env: &HashMap<String, String>,
) -> Result<Option<String>, AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    // Build command with workdir and environment
    let mut full_cmd = String::new();

    // Add environment variables
    for (key, value) in env {
        full_cmd.push_str(&format!("export {}={}; ", key, shell_escape(value)));
    }

    // Add workdir
    if let Some(wd) = workdir {
        full_cmd.push_str(&format!("cd {} && ", shell_escape(wd)));
    }

    full_cmd.push_str(command);

    // Execute via SSH
    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(&full_cmd);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to execute SSH: {e}")))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    // Combine stdout and stderr for complete output
    let combined_output = if !stdout.is_empty() && !stderr.is_empty() {
        format!("{}\n--- stderr ---\n{}", stdout, stderr)
    } else if !stdout.is_empty() {
        stdout
    } else if !stderr.is_empty() {
        format!("(stderr only)\n{}", stderr)
    } else {
        String::new()
    };

    if !output.status.success() {
        return Err(AppError::command(format!(
            "SSH command failed with exit code {:?}: {}",
            output.status.code(),
            if combined_output.is_empty() {
                "(no output)".to_string()
            } else {
                combined_output
            }
        )));
    }

    Ok(if combined_output.is_empty() {
        None
    } else {
        Some(combined_output)
    })
}

/// Check if a command succeeds (exit code 0)
pub async fn command_succeeds(host_id: &str, command: &str) -> Result<bool, AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(command);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to execute SSH: {e}")))?;

    Ok(output.status.success())
}

/// Get command output
pub async fn get_output(host_id: &str, command: &str) -> Result<String, AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let mut cmd = tokio::process::Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    cmd.arg(ssh.target());
    cmd.arg(command);

    let output = cmd
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to execute SSH: {e}")))?;

    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Simple shell escape (basic implementation)
fn shell_escape(s: &str) -> String {
    if s.chars()
        .all(|c| c.is_alphanumeric() || c == '_' || c == '-' || c == '/' || c == '.')
    {
        s.to_string()
    } else {
        format!("'{}'", s.replace('\'', "'\\''"))
    }
}
