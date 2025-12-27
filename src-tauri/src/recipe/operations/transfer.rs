//! Transfer operation for recipes
//!
//! Handles file transfers between any combination of:
//! - Local filesystem
//! - SSH hosts
//! - Storage backends (Google Drive, S3, etc.)

use std::collections::HashMap;
use std::path::PathBuf;

use crate::error::AppError;
use crate::host;
use crate::recipe::types::{TransferEndpoint, TransferOp};
use crate::storage::{get_storage, Storage, StorageBackend};
use crate::sync as sync_module;
use super::ssh as ssh_ops;

/// Execute a transfer operation
pub async fn execute(
    op: &TransferOp,
    variables: &HashMap<String, String>,
) -> Result<Option<String>, AppError> {
    // Resolve the target host if needed
    let target_host = variables.get("target").cloned();
    
    // Determine transfer type and execute
    match (&op.source, &op.destination) {
        // Local → Host
        (TransferEndpoint::Local { path: local_path }, TransferEndpoint::Host { host_id, path: remote_path }) => {
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let local_path = interpolate(local_path, variables);
            let remote_path = interpolate(remote_path, variables);
            
            if is_local_target(&host_id) {
                // Local target - just do a local copy
                let status = tokio::process::Command::new("rsync")
                    .args(["-av", "--progress", &local_path, &remote_path])
                    .status()
                    .await
                    .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
                
                if !status.success() {
                    return Err(AppError::command("Local copy failed"));
                }
                Ok(Some(format!("Copied {} to {}", local_path, remote_path)))
            } else {
                upload_to_host(&host_id, &local_path, &remote_path, &op.exclude_patterns, op.delete).await?;
                Ok(Some(format!("Uploaded {} to {}:{}", local_path, host_id, remote_path)))
            }
        }
        
        // Host → Local
        (TransferEndpoint::Host { host_id, path: remote_path }, TransferEndpoint::Local { path: local_path }) => {
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let remote_path = interpolate(remote_path, variables);
            let local_path = interpolate(local_path, variables);
            
            if is_local_target(&host_id) {
                // Local target - just do a local copy
                let status = tokio::process::Command::new("rsync")
                    .args(["-av", "--progress", &remote_path, &local_path])
                    .status()
                    .await
                    .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
                
                if !status.success() {
                    return Err(AppError::command("Local copy failed"));
                }
                Ok(Some(format!("Copied {} to {}", remote_path, local_path)))
            } else {
                download_from_host(&host_id, &remote_path, &local_path, &op.exclude_patterns).await?;
                Ok(Some(format!("Downloaded {}:{} to {}", host_id, remote_path, local_path)))
            }
        }
        
        // Host → Host (same or different hosts)
        (TransferEndpoint::Host { host_id: src_host, path: src_path }, TransferEndpoint::Host { host_id: dst_host, path: dst_path }) => {
            let src_host_id = resolve_host_id(src_host.as_deref(), target_host.as_deref())?;
            let dst_host_id = resolve_host_id(dst_host.as_deref(), target_host.as_deref())?;
            let src_path = interpolate(src_path, variables);
            let dst_path = interpolate(dst_path, variables);
            
            // Check if both are local
            let src_is_local = is_local_target(&src_host_id);
            let dst_is_local = is_local_target(&dst_host_id);
            
            if src_is_local && dst_is_local {
                // Both local - just do a local copy
                let status = tokio::process::Command::new("rsync")
                    .args(["-av", "--progress", &src_path, &dst_path])
                    .status()
                    .await
                    .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
                
                if !status.success() {
                    return Err(AppError::command("Local copy failed"));
                }
                Ok(Some(format!("Copied {} to {}", src_path, dst_path)))
            } else if src_is_local {
                // Source is local, dest is remote - upload
                upload_to_host(&dst_host_id, &src_path, &dst_path, &op.exclude_patterns, op.delete).await?;
                Ok(Some(format!("Uploaded {} to {}:{}", src_path, dst_host_id, dst_path)))
            } else if dst_is_local {
                // Source is remote, dest is local - download
                download_from_host(&src_host_id, &src_path, &dst_path, &op.exclude_patterns).await?;
                Ok(Some(format!("Downloaded {}:{} to {}", src_host_id, src_path, dst_path)))
            } else if src_host_id == dst_host_id {
                // Same host - just use cp/rsync locally on the host
                copy_on_host(&src_host_id, &src_path, &dst_path).await?;
                Ok(Some(format!("Transferred {}:{} to {}:{}", src_host_id, src_path, dst_host_id, dst_path)))
            } else {
                // Different hosts - download then upload, or use rsync between hosts
                transfer_between_hosts(&src_host_id, &src_path, &dst_host_id, &dst_path, &op.exclude_patterns).await?;
                Ok(Some(format!("Transferred {}:{} to {}:{}", src_host_id, src_path, dst_host_id, dst_path)))
            }
        }
        
        // Local → Storage
        (TransferEndpoint::Local { path: local_path }, TransferEndpoint::Storage { storage_id, path: storage_path }) => {
            let local_path = interpolate(local_path, variables);
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);
            
            upload_to_storage(&local_path, &storage_id, &storage_path, &op.exclude_patterns).await?;
            Ok(Some(format!("Uploaded {} to storage {}:{}", local_path, storage_id, storage_path)))
        }
        
        // Storage → Local
        (TransferEndpoint::Storage { storage_id, path: storage_path }, TransferEndpoint::Local { path: local_path }) => {
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);
            let local_path = interpolate(local_path, variables);
            
            download_from_storage(&storage_id, &storage_path, &local_path).await?;
            Ok(Some(format!("Downloaded storage {}:{} to {}", storage_id, storage_path, local_path)))
        }
        
        // Host → Storage
        (TransferEndpoint::Host { host_id, path: remote_path }, TransferEndpoint::Storage { storage_id, path: storage_path }) => {
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let remote_path = interpolate(remote_path, variables);
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);
            
            if is_local_target(&host_id) {
                // Local to storage - upload from local path
                upload_to_storage(&remote_path, &storage_id, &storage_path, &op.exclude_patterns).await?;
                Ok(Some(format!("Uploaded {} to storage {}:{}", remote_path, storage_id, storage_path)))
            } else {
                transfer_host_to_storage(&host_id, &remote_path, &storage_id, &storage_path).await?;
                Ok(Some(format!("Transferred {}:{} to storage {}:{}", host_id, remote_path, storage_id, storage_path)))
            }
        }
        
        // Storage → Host
        (TransferEndpoint::Storage { storage_id, path: storage_path }, TransferEndpoint::Host { host_id, path: remote_path }) => {
            let storage_id = interpolate(storage_id, variables);
            let storage_path = interpolate(storage_path, variables);
            let host_id = resolve_host_id(host_id.as_deref(), target_host.as_deref())?;
            let remote_path = interpolate(remote_path, variables);
            
            if is_local_target(&host_id) {
                // Storage to local - download to local path
                download_from_storage(&storage_id, &storage_path, &remote_path).await?;
                Ok(Some(format!("Downloaded storage {}:{} to {}", storage_id, storage_path, remote_path)))
            } else {
                transfer_storage_to_host(&storage_id, &storage_path, &host_id, &remote_path).await?;
                Ok(Some(format!("Transferred storage {}:{} to {}:{}", storage_id, storage_path, host_id, remote_path)))
            }
        }
        
        // Storage → Storage
        (TransferEndpoint::Storage { storage_id: src_id, path: src_path }, TransferEndpoint::Storage { storage_id: dst_id, path: dst_path }) => {
            let src_id = interpolate(src_id, variables);
            let src_path = interpolate(src_path, variables);
            let dst_id = interpolate(dst_id, variables);
            let dst_path = interpolate(dst_path, variables);
            
            transfer_storage_to_storage(&src_id, &src_path, &dst_id, &dst_path).await?;
            Ok(Some(format!("Transferred storage {}:{} to storage {}:{}", src_id, src_path, dst_id, dst_path)))
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
    explicit
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

/// Upload from local to host using rsync CLI
async fn upload_to_host(
    host_id: &str,
    local_path: &str,
    remote_path: &str,
    excludes: &[String],
    delete: bool,
) -> Result<(), AppError> {
    let host = host::get_host(host_id).await?;
    let ssh = host.ssh.as_ref()
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    
    let ssh_opts = build_ssh_opts(ssh);
    let remote = format!("{}@{}:{}", ssh.user, ssh.host, remote_path);
    
    let mut rsync = tokio::process::Command::new("rsync");
    rsync.args(["-avz", "--progress"]);
    rsync.args(["-e", &format!("ssh {}", ssh_opts)]);
    for exclude in excludes {
        rsync.args(["--exclude", exclude]);
    }
    if delete {
        rsync.arg("--delete");
    }
    rsync.arg(local_path);
    rsync.arg(&remote);
    
    let status = rsync.status().await
        .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
    
    if !status.success() {
        return Err(AppError::command("Upload to host failed"));
    }
    
    Ok(())
}

/// Download from host to local using rsync CLI
async fn download_from_host(
    host_id: &str,
    remote_path: &str,
    local_path: &str,
    excludes: &[String],
) -> Result<(), AppError> {
    let host = host::get_host(host_id).await?;
    let ssh = host.ssh.as_ref()
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    
    // Create local directory if needed
    if let Some(parent) = std::path::Path::new(local_path).parent() {
        tokio::fs::create_dir_all(parent).await
            .map_err(|e| AppError::io(format!("Failed to create directory: {}", e)))?;
    }
    
    let ssh_opts = build_ssh_opts(ssh);
    let remote = format!("{}@{}:{}", ssh.user, ssh.host, remote_path);
    
    let mut rsync = tokio::process::Command::new("rsync");
    rsync.args(["-avz", "--progress"]);
    rsync.args(["-e", &format!("ssh {}", ssh_opts)]);
    for exclude in excludes {
        rsync.args(["--exclude", exclude]);
    }
    rsync.arg(&remote);
    rsync.arg(local_path);
    
    let status = rsync.status().await
        .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
    
    if !status.success() {
        return Err(AppError::command("Download from host failed"));
    }
    
    Ok(())
}

/// Copy files within the same host
async fn copy_on_host(
    host_id: &str,
    src_path: &str,
    dst_path: &str,
) -> Result<(), AppError> {
    // Create destination directory and copy
    let cmd = format!("mkdir -p $(dirname {}) && cp -r {} {}", dst_path, src_path, dst_path);
    ssh_ops::execute_command(host_id, &cmd, None, &HashMap::new()).await?;
    Ok(())
}

/// Transfer files between two different hosts via local machine using rsync CLI
async fn transfer_between_hosts(
    src_host_id: &str,
    src_path: &str,
    dst_host_id: &str,
    dst_path: &str,
    excludes: &[String],
) -> Result<(), AppError> {
    // Get both hosts
    let src_host = host::get_host(src_host_id).await?;
    let dst_host = host::get_host(dst_host_id).await?;
    
    let src_ssh = src_host.ssh.as_ref()
        .ok_or_else(|| AppError::invalid_input("Source host has no SSH configuration"))?;
    let dst_ssh = dst_host.ssh.as_ref()
        .ok_or_else(|| AppError::invalid_input("Destination host has no SSH configuration"))?;
    
    // Create temp directory
    let temp_dir = std::env::temp_dir().join(format!("transfer-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&temp_dir).await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;
    
    // Build SSH options for source
    let src_ssh_opts = build_ssh_opts(src_ssh);
    let src_remote = format!("{}@{}:{}", src_ssh.user, src_ssh.host, src_path);
    
    // Download from source using rsync CLI (supports ssh-agent)
    let mut rsync_down = tokio::process::Command::new("rsync");
    rsync_down.args(["-avz", "--progress"]);
    rsync_down.args(["-e", &format!("ssh {}", src_ssh_opts)]);
    for exclude in excludes {
        rsync_down.args(["--exclude", exclude]);
    }
    rsync_down.arg(&src_remote);
    rsync_down.arg(temp_dir.to_str().unwrap());
    
    let status = rsync_down.status().await
        .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
    if !status.success() {
        let _ = tokio::fs::remove_dir_all(&temp_dir).await;
        return Err(AppError::command("Download from source host failed"));
    }
    
    // Build SSH options for destination
    let dst_ssh_opts = build_ssh_opts(dst_ssh);
    let dst_remote = format!("{}@{}:{}", dst_ssh.user, dst_ssh.host, dst_path);
    
    // Upload to destination using rsync CLI
    let mut rsync_up = tokio::process::Command::new("rsync");
    rsync_up.args(["-avz", "--progress"]);
    rsync_up.args(["-e", &format!("ssh {}", dst_ssh_opts)]);
    for exclude in excludes {
        rsync_up.args(["--exclude", exclude]);
    }
    // Add trailing slash to copy contents, not the directory itself
    let local_src = format!("{}/", temp_dir.to_string_lossy());
    rsync_up.arg(&local_src);
    rsync_up.arg(&dst_remote);
    
    let output = rsync_up.output().await
        .map_err(|e| AppError::command(format!("Failed to run rsync: {}", e)))?;
    
    // Cleanup temp dir
    let _ = tokio::fs::remove_dir_all(&temp_dir).await;
    
    // Check exit status - be lenient with certain exit codes
    let exit_code = output.status.code().unwrap_or(-1);
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        
        eprintln!("[transfer] rsync exit code: {}", exit_code);
        eprintln!("[transfer] rsync stderr: {}", stderr);
        
        // Exit code 255: SSH connection closed after transfer
        // This is common with cloudflared tunnels - the connection drops after transfer completes
        // Since we saw the progress output (speedup is X.XX) in terminal, the transfer succeeded
        if exit_code == 255 {
            eprintln!("[transfer] Exit code 255 (SSH connection closed) - treating as success for cloudflared tunnels");
            return Ok(());
        }
        
        // Exit code 24: Partial transfer due to vanished source files (often OK)
        if exit_code == 24 {
            eprintln!("[transfer] Exit code 24 (partial transfer) - treating as success");
            return Ok(());
        }
        
        return Err(AppError::command(format!(
            "Upload to destination host failed (exit code {}): {}",
            exit_code, stderr
        )));
    }
    
    Ok(())
}

/// Build SSH command-line options from SshSpec
fn build_ssh_opts(ssh: &crate::ssh::SshSpec) -> String {
    let mut opts = vec![format!("-p {}", ssh.port)];
    
    if let Some(key_path) = &ssh.key_path {
        opts.push(format!("-i {}", key_path));
    }
    
    opts.push("-o StrictHostKeyChecking=accept-new".to_string());
    
    // Handle extra args (like ProxyCommand for cloudflared)
    let mut i = 0;
    while i < ssh.extra_args.len() {
        if ssh.extra_args[i] == "-o" && i + 1 < ssh.extra_args.len() {
            opts.push(format!("-o {}", ssh.extra_args[i + 1]));
            i += 2;
        } else {
            opts.push(ssh.extra_args[i].clone());
            i += 1;
        }
    }
    
    opts.join(" ")
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
        
        let result = librclone::rpc("sync/copy", &serde_json::json!({
            "srcFs": local_path,
            "dstFs": dst_fs,
            "_async": false,
        }).to_string());
        
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
        tokio::fs::create_dir_all(parent).await
            .map_err(|e| AppError::io(format!("Failed to create directory: {}", e)))?;
    }
    
    if let Some(config) = remote_config {
        let remote_name = create_temp_rclone_remote("src", &config)?;
        let src_fs = format!("{}:{}", remote_name, full_path);
        
        let result = librclone::rpc("sync/copy", &serde_json::json!({
            "srcFs": src_fs,
            "dstFs": local_path,
            "_async": false,
        }).to_string());
        
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
    tokio::fs::create_dir_all(&temp_dir).await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;
    
    // Download from host to temp
    download_from_host(host_id, remote_path, temp_dir.to_str().unwrap(), &[]).await?;
    
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
    tokio::fs::create_dir_all(&temp_dir).await
        .map_err(|e| AppError::io(format!("Failed to create temp dir: {}", e)))?;
    
    // Download from storage to temp
    download_from_storage(storage_id, storage_path, temp_dir.to_str().unwrap()).await?;
    
    // Upload from temp to host
    upload_to_host(host_id, temp_dir.to_str().unwrap(), remote_path, &[], false).await?;
    
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
    
    let src_remote_name = src_config.as_ref().map(|c| create_temp_rclone_remote("src", c)).transpose()?;
    let dst_remote_name = dst_config.as_ref().map(|c| create_temp_rclone_remote("dst", c)).transpose()?;
    
    let src_fs = match &src_remote_name {
        Some(name) => format!("{}:{}", name, src_full_path),
        None => src_full_path.clone(),
    };
    
    let dst_fs = match &dst_remote_name {
        Some(name) => format!("{}:{}", name, dst_full_path),
        None => dst_full_path.clone(),
    };
    
    let result = librclone::rpc("sync/copy", &serde_json::json!({
        "srcFs": src_fs,
        "dstFs": dst_fs,
        "_async": false,
    }).to_string());
    
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
fn build_rclone_remote(storage: &Storage, path: &str) -> Result<(Option<serde_json::Value>, String), AppError> {
    match &storage.backend {
        StorageBackend::Local { root_path } => {
            let full_path = PathBuf::from(root_path)
                .join(path.trim_start_matches('/'))
                .to_string_lossy()
                .to_string();
            Ok((None, full_path))
        }
        StorageBackend::CloudflareR2 { account_id, access_key_id, secret_access_key, bucket, endpoint } => {
            let endpoint = endpoint.clone().unwrap_or_else(|| {
                format!("https://{}.r2.cloudflarestorage.com", account_id)
            });
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
        StorageBackend::GoogleDrive { token, root_folder_id, service_account_json, .. } => {
            let mut config = serde_json::json!({
                "type": "drive",
                "scope": "drive",
            });
            // Service Account takes priority
            if let Some(sa_json) = service_account_json {
                config["service_account_credentials"] = serde_json::Value::String(sa_json.clone());
            } else if let Some(token) = token {
                config["token"] = serde_json::Value::String(token.clone());
            }
            if let Some(root_id) = root_folder_id {
                config["root_folder_id"] = serde_json::Value::String(root_id.clone());
            }
            Ok((Some(config), path.to_string()))
        }
        StorageBackend::GoogleCloudStorage { project_id, service_account_json, bucket } => {
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
        StorageBackend::SshRemote { host_id, root_path: _ } => {
            // For SSH remote, we need to get the host's SSH config
            // This is handled separately in async context
            Err(AppError::command(format!(
                "SSH remote storage {} not directly supported in transfer. Use Host endpoint instead with host_id={}",
                storage.id, host_id
            )))
        }
        StorageBackend::Smb { host, share, user, password, domain } => {
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

