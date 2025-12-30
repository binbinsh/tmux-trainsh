//! Vast.ai operations

use std::path::Path;
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, BufReader};

use super::transfer::ProgressCallback;
use crate::config::load_config;
use crate::error::AppError;
use crate::host;
use crate::vast::VastClient;

/// Start a Vast.ai instance
pub async fn start_instance(instance_id: i64) -> Result<(), AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    client.start_instance(instance_id).await?;
    let _ = host::resolve_ssh_spec_with_retry(&format!("vast:{instance_id}"), Duration::from_secs(300)).await?;
    Ok(())
}

/// Stop a Vast.ai instance
pub async fn stop_instance(instance_id: i64) -> Result<(), AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    client.stop_instance(instance_id).await
}

/// Destroy a Vast.ai instance
pub async fn destroy_instance(instance_id: i64) -> Result<(), AppError> {
    let cfg = load_config().await?;
    let client = VastClient::from_cfg(&cfg)?;
    client.destroy_instance(instance_id).await
}

#[derive(Debug, Clone)]
struct VastCopyLocation {
    id: Option<String>,
    path: String,
}

/// Copy data using Vast's copy API with CLI-compatible src/dst formats.
pub async fn copy(
    src: &str,
    dst: &str,
    identity_file: Option<&str>,
    progress: Option<ProgressCallback>,
) -> Result<String, AppError> {
    let src_loc = parse_vast_location(src)?;
    let dst_loc = parse_vast_location(dst)?;

    let src_is_local = is_local_id(src_loc.id.as_deref());
    let dst_is_local = is_local_id(dst_loc.id.as_deref());

    if src_is_local && dst_is_local {
        return Err(AppError::invalid_input(
            "vast_copy requires at least one non-local endpoint",
        ));
    }

    if let Some(cb) = &progress {
        cb(&format!("Requesting Vast copy session: {} -> {}", src, dst));
    }

    let cfg = load_config().await?;
    let identity_path = identity_file
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .map(|p| p.to_string())
        .or_else(|| cfg.vast.ssh_key_path.clone().filter(|p| !p.trim().is_empty()));
    let client = VastClient::from_cfg(&cfg)?;
    let use_rsync_endpoint = src_loc.id.is_none() || dst_loc.id.is_none();
    let response = client
        .copy(
            src_loc.id.clone(),
            dst_loc.id.clone(),
            src_loc.path.clone(),
            dst_loc.path.clone(),
            use_rsync_endpoint,
        )
        .await?;

    if !response.success.unwrap_or(false) {
        let msg = response
            .msg
            .or(response.error)
            .unwrap_or_else(|| "Vast copy failed".to_string());
        return Err(AppError::vast_api(msg));
    }

    if src_is_local {
        if let Some(path) = identity_path.as_deref() {
            if !Path::new(path).exists() {
                return Err(AppError::invalid_input(format!(
                    "Identity file not found: {path}"
                )));
            }
        }
        let dst_id = dst_loc.id.as_deref().ok_or_else(|| {
            AppError::invalid_input("Destination instance ID is required for upload")
        })?;
        let dst_addr = response
            .dst_addr
            .as_deref()
            .ok_or_else(|| AppError::vast_api("Missing dst_addr from Vast copy response"))?;
        let dst_port = response
            .dst_port
            .ok_or_else(|| AppError::vast_api("Missing dst_port from Vast copy response"))?;

        if let Some(cb) = &progress {
            cb("Starting rsync upload...");
        }

        let ssh_cmd = build_ssh_command(dst_port, identity_path.as_deref());
        let remote = build_rsync_remote(dst_addr, dst_id, &dst_loc.path);
        let args = vec![
            "-arz".to_string(),
            "-v".to_string(),
            "--progress".to_string(),
            "--rsh=ssh".to_string(),
            "-e".to_string(),
            ssh_cmd,
            src_loc.path.clone(),
            remote,
        ];
        run_rsync_with_progress(args, progress).await?;
        return Ok(format!(
            "Uploaded {} to {}:{}",
            src_loc.path, dst_id, dst_loc.path
        ));
    }

    if dst_is_local {
        if let Some(path) = identity_path.as_deref() {
            if !Path::new(path).exists() {
                return Err(AppError::invalid_input(format!(
                    "Identity file not found: {path}"
                )));
            }
        }
        let src_id = src_loc.id.as_deref().ok_or_else(|| {
            AppError::invalid_input("Source instance ID is required for download")
        })?;
        let src_addr = response
            .src_addr
            .as_deref()
            .ok_or_else(|| AppError::vast_api("Missing src_addr from Vast copy response"))?;
        let src_port = response
            .src_port
            .ok_or_else(|| AppError::vast_api("Missing src_port from Vast copy response"))?;

        prepare_local_destination(&dst_loc.path).await?;

        if let Some(cb) = &progress {
            cb("Starting rsync download...");
        }

        let ssh_cmd = build_ssh_command(src_port, identity_path.as_deref());
        let remote = build_rsync_remote(src_addr, src_id, &src_loc.path);
        let args = vec![
            "-arz".to_string(),
            "-v".to_string(),
            "--progress".to_string(),
            "--rsh=ssh".to_string(),
            "-e".to_string(),
            ssh_cmd,
            remote,
            dst_loc.path.clone(),
        ];
        run_rsync_with_progress(args, progress).await?;
        return Ok(format!(
            "Downloaded {}:{} to {}",
            src_id, src_loc.path, dst_loc.path
        ));
    }

    Ok(response
        .msg
        .unwrap_or_else(|| "Vast copy initiated".to_string()))
}

fn parse_vast_location(input: &str) -> Result<VastCopyLocation, AppError> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Err(AppError::invalid_input("Source/destination cannot be empty"));
    }

    if let Some((left, right)) = trimmed.split_once(':') {
        let id = left.trim();
        let path = right.to_string();
        if id.is_empty() {
            return Err(AppError::invalid_input(
                "Copy location must include a prefix like C.<id> or local",
            ));
        }
        if path.is_empty() {
            return Err(AppError::invalid_input(
                "Path component cannot be empty",
            ));
        }
        return Ok(VastCopyLocation {
            id: Some(id.to_string()),
            path,
        });
    }

    if let Ok(instance_id) = trimmed.parse::<i64>() {
        if instance_id <= 0 {
            return Err(AppError::invalid_input("Instance ID must be positive"));
        }
        return Ok(VastCopyLocation {
            id: Some(instance_id.to_string()),
            path: "/".to_string(),
        });
    }

    Err(AppError::invalid_input(
        "Invalid copy location. Use formats like C.<id>:/path or local:/path.",
    ))
}

fn is_local_id(id: Option<&str>) -> bool {
    matches!(id, None) || id.is_some_and(|v| v.trim().eq_ignore_ascii_case("local"))
}

fn build_rsync_remote(addr: &str, id: &str, path: &str) -> String {
    let module_path = if path.starts_with('/') {
        format!("{id}{path}")
    } else {
        format!("{id}/{path}")
    };
    format!("vastai_kaalia@{}::{}", addr, module_path)
}

fn build_ssh_command(port: i64, identity_file: Option<&str>) -> String {
    let mut cmd = String::from("ssh -o StrictHostKeyChecking=no");
    if let Some(path) = identity_file.map(str::trim).filter(|p| !p.is_empty()) {
        cmd.push_str(" -i ");
        cmd.push_str(&shell_quote(path));
    }
    cmd.push_str(&format!(" -p {}", port));
    cmd
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

async fn prepare_local_destination(path: &str) -> Result<(), AppError> {
    if path.trim().is_empty() {
        return Err(AppError::invalid_input("Destination path cannot be empty"));
    }

    if path.ends_with('/') {
        tokio::fs::create_dir_all(path)
            .await
            .map_err(|e| AppError::io(format!("Failed to create directory: {e}")))?;
        return Ok(());
    }

    if let Some(parent) = Path::new(path).parent() {
        if !parent.as_os_str().is_empty() {
            tokio::fs::create_dir_all(parent)
                .await
                .map_err(|e| AppError::io(format!("Failed to create directory: {e}")))?;
        }
    }
    Ok(())
}

async fn run_rsync_with_progress(
    args: Vec<String>,
    progress: Option<ProgressCallback>,
) -> Result<(), AppError> {
    use std::process::Stdio;

    let mut cmd = tokio::process::Command::new("rsync");
    cmd.args(&args);
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::command(format!("Failed to spawn rsync: {e}")))?;

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    let progress_clone = progress.clone();
    let stdout_handle = tokio::spawn(async move {
        if let Some(stdout) = stdout {
            let reader = BufReader::new(stdout);
            let mut lines = reader.lines();
            while let Ok(Some(line)) = lines.next_line().await {
                if let Some(ref cb) = progress_clone {
                    cb(&line);
                }
            }
        }
    });

    let stderr_output = std::sync::Arc::new(tokio::sync::Mutex::new(Vec::new()));
    let stderr_output_clone = stderr_output.clone();
    let progress_clone = progress.clone();
    let stderr_handle = tokio::spawn(async move {
        if let Some(stderr) = stderr {
            let reader = BufReader::new(stderr);
            let mut lines = reader.lines();
            while let Ok(Some(line)) = lines.next_line().await {
                stderr_output_clone.lock().await.push(line.clone());
                if let Some(ref cb) = progress_clone {
                    cb(&format!("stderr: {}", line));
                }
            }
        }
    });

    let status = child
        .wait()
        .await
        .map_err(|e| AppError::command(format!("Failed to wait for rsync: {e}")))?;

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
