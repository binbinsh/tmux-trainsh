//! Transfer operation for skills
//!
//! Handles file transfers between any combination of:
//! - Local filesystem
//! - SSH hosts
//! - Storage backends (Google Drive, S3, etc.)

use std::collections::HashMap;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, BufReader};

use super::ssh as ssh_ops;
use crate::error::AppError;
use crate::host;
use crate::skill::types::{TransferEndpoint, TransferOp};
use crate::storage::{get_storage, Storage, StorageBackend};

/// Progress callback type alias
pub type ProgressCallback = Arc<dyn Fn(&str) + Send + Sync>;

/// Execute a transfer operation
pub async fn execute(
    op: &TransferOp,
    variables: &HashMap<String, String>,
    progress: Option<ProgressCallback>,
) -> Result<Option<String>, AppError> {
    // Resolve the target host if needed
    let target_host = variables.get("target").cloned();

    // Determine transfer type and execute
    match (&op.source, &op.destination) {
        // Local → Host
        (
            TransferEndpoint::Local { path: local_path },
            TransferEndpoint::Host {
                host_id,
                path: remote_path,
            },
        ) => {
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let local_path = interpolate(local_path, variables);
            let remote_path = interpolate(remote_path, variables);

            if is_local_target(&host_id) {
                // Local target - just do a local copy with streaming
                run_rsync_with_progress(
                    &["-av", "--progress", &local_path, &remote_path],
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!("Copied {} to {}", local_path, remote_path)))
            } else {
                upload_to_host(
                    &host_id,
                    &local_path,
                    &remote_path,
                    &op.exclude_patterns,
                    op.delete,
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!(
                    "Uploaded {} to {}:{}",
                    local_path, host_id, remote_path
                )))
            }
        }

        // Host → Local
        (
            TransferEndpoint::Host {
                host_id,
                path: remote_path,
            },
            TransferEndpoint::Local { path: local_path },
        ) => {
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let remote_path = interpolate(remote_path, variables);
            let local_path = interpolate(local_path, variables);

            if is_local_target(&host_id) {
                // Local target - just do a local copy with streaming
                run_rsync_with_progress(
                    &["-av", "--progress", &remote_path, &local_path],
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!("Copied {} to {}", remote_path, local_path)))
            } else {
                download_from_host(
                    &host_id,
                    &remote_path,
                    &local_path,
                    &op.exclude_patterns,
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!(
                    "Downloaded {}:{} to {}",
                    host_id, remote_path, local_path
                )))
            }
        }

        // Host → Host (same or different hosts)
        (
            TransferEndpoint::Host {
                host_id: src_host,
                path: src_path,
            },
            TransferEndpoint::Host {
                host_id: dst_host,
                path: dst_path,
            },
        ) => {
            let src_host_id = resolve_host_id(src_host.as_deref(), target_host.as_deref())?;
            let dst_host_id = resolve_host_id(dst_host.as_deref(), target_host.as_deref())?;
            let src_path = interpolate(src_path, variables);
            let dst_path = interpolate(dst_path, variables);

            // Check if both are local
            let src_is_local = is_local_target(&src_host_id);
            let dst_is_local = is_local_target(&dst_host_id);

            if src_is_local && dst_is_local {
                // Both local - just do a local copy with streaming
                run_rsync_with_progress(
                    &["-av", "--progress", &src_path, &dst_path],
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!("Copied {} to {}", src_path, dst_path)))
            } else if src_is_local {
                // Source is local, dest is remote - upload
                upload_to_host(
                    &dst_host_id,
                    &src_path,
                    &dst_path,
                    &op.exclude_patterns,
                    op.delete,
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!(
                    "Uploaded {} to {}:{}",
                    src_path, dst_host_id, dst_path
                )))
            } else if dst_is_local {
                // Source is remote, dest is local - download
                download_from_host(
                    &src_host_id,
                    &src_path,
                    &dst_path,
                    &op.exclude_patterns,
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!(
                    "Downloaded {}:{} to {}",
                    src_host_id, src_path, dst_path
                )))
            } else if src_host_id == dst_host_id {
                // Same host - just use cp/rsync locally on the host
                copy_on_host(&src_host_id, &src_path, &dst_path).await?;
                Ok(Some(format!(
                    "Transferred {}:{} to {}:{}",
                    src_host_id, src_path, dst_host_id, dst_path
                )))
            } else {
                // Different hosts - download to local temp, then upload (rsync)
                transfer_between_hosts_rsync(
                    &src_host_id,
                    &src_path,
                    &dst_host_id,
                    &dst_path,
                    &op.exclude_patterns,
                    op.delete,
                    progress.clone(),
                )
                .await?;
                Ok(Some(format!(
                    "Transferred {}:{} to {}:{}",
                    src_host_id, src_path, dst_host_id, dst_path
                )))
            }
        }

        // Local → Storage
        (
            TransferEndpoint::Local { path: local_path },
            TransferEndpoint::Storage {
                storage_id,
                path: storage_path,
            },
        ) => {
            let local_path = interpolate(local_path, variables);
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);

            upload_to_storage(
                &local_path,
                &storage_id,
                &storage_path,
                &op.exclude_patterns,
            )
            .await?;
            Ok(Some(format!(
                "Uploaded {} to storage {}:{}",
                local_path, storage_id, storage_path
            )))
        }

        // Storage → Local
        (
            TransferEndpoint::Storage {
                storage_id,
                path: storage_path,
            },
            TransferEndpoint::Local { path: local_path },
        ) => {
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);
            let local_path = interpolate(local_path, variables);

            download_from_storage(&storage_id, &storage_path, &local_path).await?;
            Ok(Some(format!(
                "Downloaded storage {}:{} to {}",
                storage_id, storage_path, local_path
            )))
        }

        // Host → Storage
        (
            TransferEndpoint::Host {
                host_id,
                path: remote_path,
            },
            TransferEndpoint::Storage {
                storage_id,
                path: storage_path,
            },
        ) => {
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let remote_path = interpolate(remote_path, variables);
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);

            if is_local_target(&host_id) {
                // Local to storage - upload from local path
                upload_to_storage(
                    &remote_path,
                    &storage_id,
                    &storage_path,
                    &op.exclude_patterns,
                )
                .await?;
                Ok(Some(format!(
                    "Uploaded {} to storage {}:{}",
                    remote_path, storage_id, storage_path
                )))
            } else {
                transfer_host_to_storage(&host_id, &remote_path, &storage_id, &storage_path)
                    .await?;
                Ok(Some(format!(
                    "Transferred {}:{} to storage {}:{}",
                    host_id, remote_path, storage_id, storage_path
                )))
            }
        }

        // Storage → Host
        (
            TransferEndpoint::Storage {
                storage_id,
                path: storage_path,
            },
            TransferEndpoint::Host {
                host_id,
                path: remote_path,
            },
        ) => {
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let remote_path = interpolate(remote_path, variables);

            if is_local_target(&host_id) {
                // Storage to local - download to local path
                download_from_storage(&storage_id, &storage_path, &remote_path).await?;
                Ok(Some(format!(
                    "Downloaded storage {}:{} to {}",
                    storage_id, storage_path, remote_path
                )))
            } else {
                transfer_storage_to_host(&storage_id, &storage_path, &host_id, &remote_path)
                    .await?;
                Ok(Some(format!(
                    "Transferred storage {}:{} to {}:{}",
                    storage_id, storage_path, host_id, remote_path
                )))
            }
        }

        // Storage → Storage
        (
            TransferEndpoint::Storage {
                storage_id: src_id,
                path: src_path,
            },
            TransferEndpoint::Storage {
                storage_id: dst_id,
                path: dst_path,
            },
        ) => {
            let src_id = interpolate(src_id, variables);
            let src_path = interpolate(src_path, variables);
            let dst_id = interpolate(dst_id, variables);
            let dst_path = interpolate(dst_path, variables);

            transfer_storage_to_storage(&src_id, &src_path, &dst_id, &dst_path).await?;
            Ok(Some(format!(
                "Transferred storage {}:{} to storage {}:{}",
                src_id, src_path, dst_id, dst_path
            )))
        }

        // Local → Local (just use cp)
        (TransferEndpoint::Local { path: src }, TransferEndpoint::Local { path: dst }) => {
            let src = interpolate(src, variables);
            let dst = interpolate(dst, variables);

            // Use rsync for local copy
            let status = tokio::process::Command::new("rsync")
                .args(["-av", "--progress", &src, &dst])
                .status()
                .await
                .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;

            if !status.success() {
                return Err(AppError::command("Local copy failed"));
            }
            Ok(Some(format!("Copied {} to {}", src, dst)))
        }
    }
}

/// Special target value for local execution
const LOCAL_TARGET: &str = "__local__";

/// Check if a host_id refers to local execution
fn is_local_target(host_id: &str) -> bool {
    host_id == LOCAL_TARGET
}

fn resolve_host_id(explicit: Option<&str>, target: Option<&str>) -> Result<String, AppError> {
    // Treat empty string as None
    explicit
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string())
        .or_else(|| target.map(|s| s.to_string()))
        .ok_or_else(|| AppError::command("No host_id specified and no target defined"))
}

fn interpolate(s: &str, variables: &HashMap<String, String>) -> String {
    let mut result = s.to_string();
    for (key, value) in variables {
        result = result.replace(&format!("${{{}}}", key), value);
    }
    result
}

/// Run rsync with live progress output streaming
async fn run_rsync_with_progress(
    args: &[&str],
    progress: Option<ProgressCallback>,
) -> Result<(), AppError> {
    use std::process::Stdio;

    let mut cmd = tokio::process::Command::new("rsync");
    cmd.args(args);
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::command(format!("Failed to spawn rsync: {}", e)))?;

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    // Stream stdout
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

    // Stream stderr
    let stderr_output = Arc::new(tokio::sync::Mutex::new(Vec::new()));
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

    // Wait for the process to complete
    let status = child
        .wait()
        .await
        .map_err(|e| AppError::command(format!("Failed to wait for rsync: {}", e)))?;

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

/// Run rsync with SSH wrapper and live progress output streaming
async fn run_rsync_ssh_with_progress(
    ssh_wrapper: &PathBuf,
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
        .map_err(|e| AppError::command(format!("Failed to spawn rsync: {}", e)))?;

    let stdout = child.stdout.take();
    let stderr = child.stderr.take();

    // Stream stdout
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

    // Stream stderr
    let stderr_output = Arc::new(tokio::sync::Mutex::new(Vec::new()));
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

    // Wait for the process to complete
    let status = child
        .wait()
        .await
        .map_err(|e| AppError::command(format!("Failed to wait for rsync: {}", e)))?;

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

/// Upload from local to host using rsync CLI
async fn upload_to_host(
    host_id: &str,
    local_path: &str,
    remote_path: &str,
    excludes: &[String],
    delete: bool,
    progress: Option<ProgressCallback>,
) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let ssh_wrapper = build_rsync_ssh_wrapper(&ssh)?;
    let remote = format!("{}@{}:{}", ssh.user, ssh.host, remote_path);

    // Ensure destination directory exists before rsync
    let mkdir_cmd = format!(r#"mkdir -p "{}""#, remote_path.replace('"', "\\\""));
    ssh_ops::execute_command(host_id, &mkdir_cmd, None, &HashMap::new()).await?;

    // Build args as owned Strings
    let mut args: Vec<String> = vec![
        "-avz".to_string(),
        "--progress".to_string(),
        "-e".to_string(),
        ssh_wrapper.to_string_lossy().to_string(),
    ];
    for exclude in excludes {
        args.push("--exclude".to_string());
        args.push(exclude.clone());
    }
    if delete {
        args.push("--delete".to_string());
    }
    args.push(local_path.to_string());
    args.push(remote);

    run_rsync_ssh_with_progress(&ssh_wrapper, args, progress).await
}

/// Download from host to local using rsync CLI
async fn download_from_host(
    host_id: &str,
    remote_path: &str,
    local_path: &str,
    excludes: &[String],
    progress: Option<ProgressCallback>,
) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    // Create local directory if needed
    if let Some(parent) = std::path::Path::new(local_path).parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| AppError::io(format!("Failed to create directory: {}", e)))?;
    }

    let ssh_wrapper = build_rsync_ssh_wrapper(&ssh)?;
    let remote = format!("{}@{}:{}", ssh.user, ssh.host, remote_path);

    // Build args as owned Strings
    let mut args: Vec<String> = vec![
        "-avz".to_string(),
        "--progress".to_string(),
        "-e".to_string(),
        ssh_wrapper.to_string_lossy().to_string(),
    ];
    for exclude in excludes {
        args.push("--exclude".to_string());
        args.push(exclude.clone());
    }
    args.push(remote);
    args.push(local_path.to_string());

    run_rsync_ssh_with_progress(&ssh_wrapper, args, progress).await
}

/// Copy files within the same host
async fn copy_on_host(host_id: &str, src_path: &str, dst_path: &str) -> Result<(), AppError> {
    // Create destination directory and copy
    let cmd = format!(
        "mkdir -p $(dirname {}) && cp -r {} {}",
        dst_path, src_path, dst_path
    );
    ssh_ops::execute_command(host_id, &cmd, None, &HashMap::new()).await?;
    Ok(())
}

/// Transfer files between two different hosts by staging through local temp (rsync).
async fn transfer_between_hosts_rsync(
    src_host_id: &str,
    src_path: &str,
    dst_host_id: &str,
    dst_path: &str,
    excludes: &[String],
    delete: bool,
    progress: Option<ProgressCallback>,
) -> Result<(), AppError> {
    let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&temp_dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;

    let progress_clone = progress.clone();
    let result = async {
        let temp_root = temp_dir.to_string_lossy().to_string();
        if let Some(ref cb) = progress_clone {
            cb(&format!("Downloading from {}:{}", src_host_id, src_path));
        }
        download_from_host(
            src_host_id,
            src_path,
            &temp_root,
            excludes,
            progress_clone.clone(),
        )
        .await?;

        // Preserve rsync trailing-slash semantics when re-uploading.
        let mut copy_contents =
            src_path.ends_with('/') || src_path.ends_with("/.") || src_path.ends_with("/./");
        let mut payload = if copy_contents {
            temp_dir.clone()
        } else {
            let trimmed = src_path.trim_end_matches('/');
            match std::path::Path::new(trimmed).file_name() {
                Some(name) if name != "." && name != ".." => temp_dir.join(name),
                _ => {
                    copy_contents = true;
                    temp_dir.clone()
                }
            }
        };

        if !copy_contents && tokio::fs::metadata(&payload).await.is_err() {
            copy_contents = true;
            payload = temp_dir.clone();
        }

        let payload_str = payload.to_string_lossy();
        let upload_source = if copy_contents {
            format!("{}/", payload_str.as_ref().trim_end_matches('/'))
        } else {
            payload_str.to_string()
        };

        if let Some(ref cb) = progress_clone {
            cb(&format!("Uploading to {}:{}", dst_host_id, dst_path));
        }
        upload_to_host(
            dst_host_id,
            &upload_source,
            dst_path,
            excludes,
            delete,
            progress_clone,
        )
        .await?;
        Ok(())
    }
    .await;

    let _ = tokio::fs::remove_dir_all(&temp_dir).await;
    result
}

fn build_rsync_ssh_wrapper(ssh: &crate::ssh::SshSpec) -> Result<PathBuf, AppError> {
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

fn format_command_output(stdout: &str, stderr: &str) -> String {
    if !stdout.is_empty() && !stderr.is_empty() {
        format!("{}\n--- stderr ---\n{}", stdout, stderr)
    } else if !stdout.is_empty() {
        stdout.to_string()
    } else if !stderr.is_empty() {
        format!("(stderr only)\n{}", stderr)
    } else {
        "(no output)".to_string()
    }
}

/// Upload from local to storage using rclone
async fn upload_to_storage(
    local_path: &str,
    storage_id: &str,
    storage_path: &str,
    _excludes: &[String],
) -> Result<(), AppError> {
    let storage = get_storage(storage_id).await?;

    let (remote_config, full_path) = build_rclone_remote(&storage, storage_path)?;

    if let Some(config) = remote_config {
        // Create temp remote and sync
        let remote_name = create_temp_rclone_remote("dst", &config)?;
        let dst_fs = format!("{}:{}", remote_name, full_path);

        let result = librclone::rpc(
            "sync/copy",
            &serde_json::json!({
                "srcFs": local_path,
                "dstFs": dst_fs,
                "_async": false,
            })
            .to_string(),
        );

        delete_temp_rclone_remote(&remote_name);
        result.map_err(|e| AppError::command(format!("Upload to storage failed: {}", e)))?;
    } else {
        // Local storage - just use cp/rsync
        let status = tokio::process::Command::new("rsync")
            .args(["-av", local_path, &full_path])
            .status()
            .await
            .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;

        if !status.success() {
            return Err(AppError::command("Upload to local storage failed"));
        }
    }

    Ok(())
}

/// Download from storage to local using rclone
async fn download_from_storage(
    storage_id: &str,
    storage_path: &str,
    local_path: &str,
) -> Result<(), AppError> {
    let storage = get_storage(storage_id).await?;

    let (remote_config, full_path) = build_rclone_remote(&storage, storage_path)?;

    // Create local directory
    if let Some(parent) = PathBuf::from(local_path).parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|e| AppError::io(format!("Failed to create directory: {}", e)))?;
    }

    if let Some(config) = remote_config {
        let remote_name = create_temp_rclone_remote("src", &config)?;
        let src_fs = format!("{}:{}", remote_name, full_path);

        let result = librclone::rpc(
            "sync/copy",
            &serde_json::json!({
                "srcFs": src_fs,
                "dstFs": local_path,
                "_async": false,
            })
            .to_string(),
        );

        delete_temp_rclone_remote(&remote_name);
        result.map_err(|e| AppError::command(format!("Download from storage failed: {}", e)))?;
    } else {
        // Local storage
        let status = tokio::process::Command::new("rsync")
            .args(["-av", &full_path, local_path])
            .status()
            .await
            .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;

        if !status.success() {
            return Err(AppError::command("Download from local storage failed"));
        }
    }

    Ok(())
}

/// Transfer from host to storage (via local temp)
async fn transfer_host_to_storage(
    host_id: &str,
    remote_path: &str,
    storage_id: &str,
    storage_path: &str,
) -> Result<(), AppError> {
    let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&temp_dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;

    // Download from host to temp
    download_from_host(host_id, remote_path, temp_dir.to_str().unwrap(), &[], None).await?;

    // Upload from temp to storage
    upload_to_storage(temp_dir.to_str().unwrap(), storage_id, storage_path, &[]).await?;

    // Cleanup
    let _ = tokio::fs::remove_dir_all(&temp_dir).await;

    Ok(())
}

/// Transfer from storage to host (via local temp)
async fn transfer_storage_to_host(
    storage_id: &str,
    storage_path: &str,
    host_id: &str,
    remote_path: &str,
) -> Result<(), AppError> {
    let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&temp_dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;

    // Download from storage to temp
    download_from_storage(storage_id, storage_path, temp_dir.to_str().unwrap()).await?;

    // Upload from temp to host
    upload_to_host(
        host_id,
        temp_dir.to_str().unwrap(),
        remote_path,
        &[],
        false,
        None,
    )
    .await?;

    // Cleanup
    let _ = tokio::fs::remove_dir_all(&temp_dir).await;

    Ok(())
}

/// Transfer between two storages using rclone
async fn transfer_storage_to_storage(
    src_storage_id: &str,
    src_path: &str,
    dst_storage_id: &str,
    dst_path: &str,
) -> Result<(), AppError> {
    let src_storage = get_storage(src_storage_id).await?;
    let dst_storage = get_storage(dst_storage_id).await?;

    let (src_config, src_full_path) = build_rclone_remote(&src_storage, src_path)?;
    let (dst_config, dst_full_path) = build_rclone_remote(&dst_storage, dst_path)?;

    let src_remote_name = src_config
        .as_ref()
        .map(|c| create_temp_rclone_remote("src", c))
        .transpose()?;
    let dst_remote_name = dst_config
        .as_ref()
        .map(|c| create_temp_rclone_remote("dst", c))
        .transpose()?;

    let src_fs = match &src_remote_name {
        Some(name) => format!("{}:{}", name, src_full_path),
        None => src_full_path.clone(),
    };

    let dst_fs = match &dst_remote_name {
        Some(name) => format!("{}:{}", name, dst_full_path),
        None => dst_full_path.clone(),
    };

    let result = librclone::rpc(
        "sync/copy",
        &serde_json::json!({
            "srcFs": src_fs,
            "dstFs": dst_fs,
            "_async": false,
        })
        .to_string(),
    );

    // Cleanup
    if let Some(name) = src_remote_name {
        delete_temp_rclone_remote(&name);
    }
    if let Some(name) = dst_remote_name {
        delete_temp_rclone_remote(&name);
    }

    result.map_err(|e| AppError::command(format!("Storage to storage transfer failed: {}", e)))?;
    Ok(())
}

/// Build rclone remote configuration for a storage
fn build_rclone_remote(
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
            if let Some(token) = token {
                config["token"] = serde_json::Value::String(token.clone());
            }
            if let Some(root_id) = root_folder_id {
                config["root_folder_id"] = serde_json::Value::String(root_id.clone());
            }
            Ok((Some(config), path.to_string()))
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
            if let Some(sa_json) = service_account_json {
                config["service_account_credentials"] = serde_json::Value::String(sa_json.clone());
            }
            let full_path = format!("{}/{}", bucket, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
        StorageBackend::SshRemote {
            host_id,
            root_path: _,
        } => {
            // For SSH remote, we need to get the host's SSH config
            // This is handled separately in async context
            Err(AppError::command(format!(
                "SSH remote storage {} not directly supported in transfer. Use Host endpoint instead with host_id={}",
                storage.id, host_id
            )))
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
            if let Some(user) = user {
                config["user"] = serde_json::Value::String(user.clone());
            }
            if let Some(password) = password {
                config["pass"] = serde_json::Value::String(password.clone());
            }
            if let Some(domain) = domain {
                config["domain"] = serde_json::Value::String(domain.clone());
            }
            let full_path = format!("{}/{}", share, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
    }
}

/// Create a temporary rclone remote
fn create_temp_rclone_remote(prefix: &str, config: &serde_json::Value) -> Result<String, AppError> {
    let name = format!("temp_{}_{}", prefix, uuid::Uuid::new_v4().simple());

    let params = serde_json::json!({
        "name": name,
        "parameters": config,
        "type": config.get("type").and_then(|v| v.as_str()).unwrap_or(""),
    });

    librclone::rpc("config/create", &params.to_string())
        .map_err(|e| AppError::command(format!("Failed to create rclone remote: {}", e)))?;

    Ok(name)
}

/// Delete a temporary rclone remote
fn delete_temp_rclone_remote(name: &str) {
    let params = serde_json::json!({ "name": name });
    let _ = librclone::rpc("config/delete", &params.to_string());
}
