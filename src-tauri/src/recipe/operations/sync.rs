//! File synchronization operations

use crate::error::AppError;
use crate::host;
use crate::sync as sync_module;
use std::time::Duration;

/// Upload local directory to remote host
pub async fn upload(
    host_id: &str,
    local_path: &str,
    remote_path: &str,
    excludes: &[String],
    delete: bool,
) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    let config = sync_module::SyncConfig {
        local_path: local_path.to_string(),
        remote_path: remote_path.to_string(),
        use_gitignore: false,
        extra_excludes: excludes.to_vec(),
        delete_remote: delete,
    };

    // Use empty session ID for non-session syncs
    sync_module::sync_to_remote("recipe", &ssh, &config, None).await
}

/// Download remote directory to local
pub async fn download(
    host_id: &str,
    remote_path: &str,
    local_path: &str,
    _excludes: &[String],
) -> Result<(), AppError> {
    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    // Use sync_from_remote
    sync_module::sync_from_remote("recipe", &ssh, remote_path, local_path, None).await
}
