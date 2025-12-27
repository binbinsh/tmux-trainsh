//! File synchronization operations

use crate::error::AppError;
use crate::host;
use crate::sync as sync_module;

/// Upload local directory to remote host
pub async fn upload(
    host_id: &str,
    local_path: &str,
    remote_path: &str,
    excludes: &[String],
    delete: bool,
) -> Result<(), AppError> {
    let host = host::get_host(host_id).await?;
    let ssh = host.ssh.as_ref()
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    
    let config = sync_module::SyncConfig {
        local_path: local_path.to_string(),
        remote_path: remote_path.to_string(),
        use_gitignore: false,
        extra_excludes: excludes.to_vec(),
        delete_remote: delete,
    };
    
    // Use empty session ID for non-session syncs
    sync_module::sync_to_remote("recipe", ssh, &config, None).await
}

/// Download remote directory to local
pub async fn download(
    host_id: &str,
    remote_path: &str,
    local_path: &str,
    _excludes: &[String],
) -> Result<(), AppError> {
    let host = host::get_host(host_id).await?;
    let ssh = host.ssh.as_ref()
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    
    // Use sync_from_remote
    sync_module::sync_from_remote("recipe", ssh, remote_path, local_path, None).await
}

