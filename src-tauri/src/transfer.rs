//! Transfer task management module
//!
//! Manages file transfer operations between storages with progress tracking.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager};
use tokio::sync::RwLock;

use crate::error::AppError;
use crate::host;
use crate::ssh::SshSpec;
use crate::storage::{Storage, StorageBackend, StorageStore};

// ============================================================
// Transfer Types
// ============================================================

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TransferOperation {
    /// Copy files (keep source)
    Copy,
    /// Move files (delete source after successful copy)
    Move,
    /// Sync with delete (mirror destination to source)
    Sync,
    /// Sync without delete
    SyncNoDelete,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum TransferStatus {
    Queued,
    Running,
    Paused,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TransferProgress {
    pub files_total: u64,
    pub files_done: u64,
    pub bytes_total: u64,
    pub bytes_done: u64,
    pub speed_bps: u64,
    pub eta_seconds: Option<u64>,
    pub current_file: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferTask {
    pub id: String,
    /// Legacy field for backwards compatibility
    pub source_storage_id: String,
    pub source_path: String,
    /// Legacy field for backwards compatibility
    pub dest_storage_id: String,
    pub dest_path: String,
    /// New unified endpoint fields
    #[serde(default)]
    pub source_endpoint: Option<TransferEndpoint>,
    #[serde(default)]
    pub dest_endpoint: Option<TransferEndpoint>,
    pub operation: TransferOperation,
    pub status: TransferStatus,
    pub progress: TransferProgress,
    pub created_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
    pub error: Option<String>,
}

impl TransferTask {
    pub fn new(
        source_storage_id: String,
        source_path: String,
        dest_storage_id: String,
        dest_path: String,
        operation: TransferOperation,
    ) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            source_storage_id: source_storage_id.clone(),
            source_path,
            dest_storage_id: dest_storage_id.clone(),
            dest_path,
            source_endpoint: Some(TransferEndpoint::Storage { storage_id: source_storage_id }),
            dest_endpoint: Some(TransferEndpoint::Storage { storage_id: dest_storage_id }),
            operation,
            status: TransferStatus::Queued,
            progress: TransferProgress::default(),
            created_at: chrono::Utc::now().to_rfc3339(),
            started_at: None,
            completed_at: None,
            error: None,
        }
    }

    pub fn new_unified(
        source: TransferEndpoint,
        source_path: String,
        dest: TransferEndpoint,
        dest_path: String,
        operation: TransferOperation,
    ) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            // Legacy fields for compatibility
            source_storage_id: source.display_name(),
            source_path,
            dest_storage_id: dest.display_name(),
            dest_path,
            source_endpoint: Some(source),
            dest_endpoint: Some(dest),
            operation,
            status: TransferStatus::Queued,
            progress: TransferProgress::default(),
            created_at: chrono::Utc::now().to_rfc3339(),
            started_at: None,
            completed_at: None,
            error: None,
        }
    }

    /// Get the effective source endpoint (handles legacy tasks)
    pub fn get_source_endpoint(&self) -> TransferEndpoint {
        self.source_endpoint.clone().unwrap_or_else(|| {
            TransferEndpoint::Storage { storage_id: self.source_storage_id.clone() }
        })
    }

    /// Get the effective destination endpoint (handles legacy tasks)
    pub fn get_dest_endpoint(&self) -> TransferEndpoint {
        self.dest_endpoint.clone().unwrap_or_else(|| {
            TransferEndpoint::Storage { storage_id: self.dest_storage_id.clone() }
        })
    }
}

// ============================================================
// Transfer Create Input
// ============================================================

/// Unified endpoint for transfers - can be a storage, host, vast instance, or local filesystem
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum TransferEndpoint {
    /// A configured storage
    Storage { storage_id: String },
    /// A remote host via SSH/SFTP
    Host { host_id: String },
    /// A Vast.ai instance via SSH (when running) or Vast copy API
    Vast { instance_id: i64 },
    /// Local filesystem
    Local,
}

impl TransferEndpoint {
    pub fn display_name(&self) -> String {
        match self {
            Self::Storage { storage_id } => format!("storage:{}", storage_id),
            Self::Host { host_id } => format!("host:{}", host_id),
            Self::Vast { instance_id } => format!("vast:{}", instance_id),
            Self::Local => "local".to_string(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct TransferCreateInput {
    pub source_storage_id: String,
    pub source_paths: Vec<String>,
    pub dest_storage_id: String,
    pub dest_path: String,
    pub operation: TransferOperation,
}

/// Unified transfer input supporting any endpoint type
#[derive(Debug, Clone, Deserialize)]
pub struct UnifiedTransferInput {
    pub source: TransferEndpoint,
    pub source_paths: Vec<String>,
    pub dest: TransferEndpoint,
    pub dest_path: String,
    pub operation: TransferOperation,
}

// ============================================================
// Transfer Store
// ============================================================

pub struct TransferStore {
    tasks: RwLock<HashMap<String, TransferTask>>,
    /// Queue of task IDs waiting to run
    queue: RwLock<Vec<String>>,
    /// Currently running task ID (only one at a time for now)
    running: RwLock<Option<String>>,
    data_path: PathBuf,
}

impl TransferStore {
    pub fn new(data_dir: &std::path::Path) -> Self {
        let data_path = data_dir.join("transfers.json");
        let tasks = Self::load_from_file(&data_path).unwrap_or_default();
        Self {
            tasks: RwLock::new(tasks),
            queue: RwLock::new(Vec::new()),
            running: RwLock::new(None),
            data_path,
        }
    }

    fn load_from_file(path: &PathBuf) -> Option<HashMap<String, TransferTask>> {
        let content = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&content).ok()
    }

    async fn save_to_file(&self) -> Result<(), AppError> {
        // Clone data while holding lock, then release before I/O
        let content = {
            let tasks = self.tasks.read().await;
            serde_json::to_string_pretty(&*tasks)?
        };
        // Use async file write to avoid blocking
        tokio::fs::write(&self.data_path, content).await?;
        Ok(())
    }

    pub async fn list(&self) -> Vec<TransferTask> {
        let tasks = self.tasks.read().await;
        let mut list: Vec<_> = tasks.values().cloned().collect();
        // Sort by created_at descending (newest first)
        list.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        list
    }

    pub async fn get(&self, id: &str) -> Option<TransferTask> {
        let tasks = self.tasks.read().await;
        tasks.get(id).cloned()
    }

    pub async fn create(&self, input: TransferCreateInput) -> Result<Vec<TransferTask>, AppError> {
        let mut created = Vec::new();
        let mut tasks = self.tasks.write().await;
        let mut queue = self.queue.write().await;

        for source_path in input.source_paths {
            let task = TransferTask::new(
                input.source_storage_id.clone(),
                source_path,
                input.dest_storage_id.clone(),
                input.dest_path.clone(),
                input.operation,
            );
            let id = task.id.clone();
            tasks.insert(id.clone(), task.clone());
            queue.push(id);
            created.push(task);
        }

        drop(tasks);
        drop(queue);
        self.save_to_file().await?;
        Ok(created)
    }

    /// Create unified transfer tasks supporting any endpoint type
    pub async fn create_unified(&self, input: UnifiedTransferInput) -> Result<Vec<TransferTask>, AppError> {
        let mut created = Vec::new();
        let mut tasks = self.tasks.write().await;
        let mut queue = self.queue.write().await;

        for source_path in input.source_paths {
            let task = TransferTask::new_unified(
                input.source.clone(),
                source_path,
                input.dest.clone(),
                input.dest_path.clone(),
                input.operation,
            );
            let id = task.id.clone();
            tasks.insert(id.clone(), task.clone());
            queue.push(id);
            created.push(task);
        }

        drop(tasks);
        drop(queue);
        self.save_to_file().await?;
        Ok(created)
    }

    pub async fn update_status(&self, id: &str, status: TransferStatus) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        if let Some(task) = tasks.get_mut(id) {
            task.status = status;
            match status {
                TransferStatus::Running => {
                    task.started_at = Some(chrono::Utc::now().to_rfc3339());
                }
                TransferStatus::Completed | TransferStatus::Failed | TransferStatus::Cancelled => {
                    task.completed_at = Some(chrono::Utc::now().to_rfc3339());
                }
                _ => {}
            }
        }
        drop(tasks);
        self.save_to_file().await?;
        Ok(())
    }

    pub async fn update_progress(
        &self,
        id: &str,
        progress: TransferProgress,
    ) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        if let Some(task) = tasks.get_mut(id) {
            task.progress = progress;
        }
        Ok(())
    }

    pub async fn set_error(&self, id: &str, error: String) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        if let Some(task) = tasks.get_mut(id) {
            task.error = Some(error);
            task.status = TransferStatus::Failed;
            task.completed_at = Some(chrono::Utc::now().to_rfc3339());
        }
        drop(tasks);
        self.save_to_file().await?;
        Ok(())
    }

    pub async fn cancel(&self, id: &str) -> Result<(), AppError> {
        // Remove from queue if queued
        {
            let mut queue = self.queue.write().await;
            queue.retain(|qid| qid != id);
        }

        self.update_status(id, TransferStatus::Cancelled).await
    }

    pub async fn clear_completed(&self) -> Result<(), AppError> {
        let mut tasks = self.tasks.write().await;
        tasks.retain(|_, task| {
            !matches!(
                task.status,
                TransferStatus::Completed | TransferStatus::Failed | TransferStatus::Cancelled
            )
        });
        drop(tasks);
        self.save_to_file().await
    }

    /// Get next queued task
    pub async fn next_queued(&self) -> Option<String> {
        let queue = self.queue.read().await;
        queue.first().cloned()
    }

    /// Pop task from queue
    pub async fn pop_queue(&self) -> Option<String> {
        let mut queue = self.queue.write().await;
        if queue.is_empty() {
            None
        } else {
            Some(queue.remove(0))
        }
    }

    /// Check if any task is running
    pub async fn is_running(&self) -> bool {
        self.running.read().await.is_some()
    }

    /// Set running task
    pub async fn set_running(&self, id: Option<String>) {
        *self.running.write().await = id;
    }
}

// ============================================================
// Transfer Execution
// ============================================================

/// Execute a transfer task using rclone
pub async fn execute_transfer(
    task: &TransferTask,
    source_storage: &Storage,
    dest_storage: &Storage,
    app: &AppHandle,
) -> Result<(), AppError> {
    // Build rclone command based on operation type
    let rpc_method = match task.operation {
        TransferOperation::Copy | TransferOperation::Move => "sync/copy",
        TransferOperation::Sync => "sync/sync",
        TransferOperation::SyncNoDelete => "sync/copy",
    };

    // Build source and destination paths (use async version for SSH support)
    let (src_remote, src_path) = build_remote_spec_async(source_storage, &task.source_path).await?;
    let (dst_remote, dst_path) = build_remote_spec_async(dest_storage, &task.dest_path).await?;

    // Create temporary remotes if needed
    let src_remote_name = if let Some(config) = src_remote {
        Some(create_temp_remote("src", &config)?)
    } else {
        None
    };

    let dst_remote_name = if let Some(config) = dst_remote {
        Some(create_temp_remote("dst", &config)?)
    } else {
        None
    };

    let src_fs = match &src_remote_name {
        Some(name) => format!("{}:{}", name, src_path),
        None => src_path.clone(),
    };

    let dst_fs = match &dst_remote_name {
        Some(name) => format!("{}:{}", name, dst_path),
        None => dst_path.clone(),
    };

    // Build sync options
    let mut sync_opts = serde_json::json!({
        "srcFs": src_fs,
        "dstFs": dst_fs,
        "_async": false,
        "copyLinks": true,
    });

    if task.operation == TransferOperation::Sync {
        sync_opts["deleteMode"] = serde_json::json!("sync");
    }

    // Emit starting progress
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Starting transfer...".to_string()),
            ..Default::default()
        },
    );

    // Execute the operation
    let result = librclone::rpc(rpc_method, &sync_opts.to_string());

    // Clean up temporary remotes
    if let Some(name) = src_remote_name {
        delete_temp_remote(&name);
    }
    if let Some(name) = dst_remote_name {
        delete_temp_remote(&name);
    }

    // Handle move operation (delete source after successful copy)
    if task.operation == TransferOperation::Move && result.is_ok() {
        // Delete source
        // This would need the source storage to be writable
        // For now, we skip this and document it as a limitation
    }

    result.map_err(|e| AppError::command(format!("Transfer failed: {}", e)))?;

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

fn build_remote_spec(
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
            if let Some(t) = token {
                config["token"] = serde_json::json!(t);
            }
            if let Some(folder_id) = root_folder_id {
                config["root_folder_id"] = serde_json::json!(folder_id);
            }
            Ok((Some(config), path.trim_start_matches('/').to_string()))
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
            if let Some(sa) = service_account_json {
                config["service_account_credentials"] = serde_json::json!(sa);
            }
            let full_path = format!("{}/{}", bucket, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
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
            if let Some(u) = user {
                config["user"] = serde_json::json!(u);
            }
            if let Some(p) = password {
                config["pass"] = serde_json::json!(p);
            }
            if let Some(d) = domain {
                config["domain"] = serde_json::json!(d);
            }
            let full_path = format!("{}/{}", share, path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
        StorageBackend::SshRemote {
            host_id,
            root_path: _,
        } => {
            // SSH remotes use SFTP via rclone - need async resolution
            Err(AppError::invalid_input(format!(
                "SSH remote {} requires async resolution - use build_remote_spec_async",
                host_id
            )))
        }
    }
}

/// Build SFTP config for rclone from SSH spec
/// This is async because it may need to materialize SSH keys from secrets
async fn build_sftp_config(ssh: &SshSpec) -> Result<serde_json::Value, AppError> {
    let mut config = serde_json::json!({
        "type": "sftp",
        "host": ssh.host,
        "port": ssh.port.to_string(),
        "user": ssh.user,
        "shell_type": "unix",
        "md5sum_command": "md5sum",
        "sha1sum_command": "sha1sum",
    });

    // Resolve SSH key path (handles secrets and ~ expansion)
    if let Some(key_path) = &ssh.key_path {
        if !key_path.trim().is_empty() {
            let resolved_path = crate::ssh_keys::materialize_private_key_path(key_path).await?;
            config["key_file"] = serde_json::json!(resolved_path.to_string_lossy());
        }
    }

    // Handle proxy command for cloudflared tunnels
    for i in 0..ssh.extra_args.len() {
        if ssh.extra_args[i] == "-o" && i + 1 < ssh.extra_args.len() {
            let arg = &ssh.extra_args[i + 1];
            if arg.starts_with("ProxyCommand=") {
                let proxy_cmd = arg.strip_prefix("ProxyCommand=").unwrap_or("");
                config["ssh"] = serde_json::json!(format!(
                    "ssh -o ProxyCommand={} -o StrictHostKeyChecking=accept-new",
                    proxy_cmd
                ));
            }
        }
    }

    Ok(config)
}

/// Async version that can resolve SSH hosts
async fn build_remote_spec_async(
    storage: &Storage,
    path: &str,
) -> Result<(Option<serde_json::Value>, String), AppError> {
    match &storage.backend {
        StorageBackend::SshRemote { host_id, root_path } => {
            let host_info = host::get_host(host_id).await?;
            let ssh = host_info.ssh.ok_or_else(|| {
                AppError::invalid_input(format!("Host {} has no SSH configuration", host_id))
            })?;
            let config = build_sftp_config(&ssh).await?;
            let full_path = format!(
                "{}/{}",
                root_path.trim_end_matches('/'),
                path.trim_start_matches('/')
            );
            Ok((Some(config), full_path))
        }
        _ => build_remote_spec(storage, path),
    }
}

/// Build remote spec from a unified endpoint
async fn build_endpoint_spec(
    endpoint: &TransferEndpoint,
    path: &str,
    storage_store: &StorageStore,
) -> Result<(Option<serde_json::Value>, String), AppError> {
    match endpoint {
        TransferEndpoint::Local => {
            // Local filesystem - no remote config needed
            // Expand ~ and / to home directory (matching list_local_files behavior)
            let full_path = if path == "/" || path.is_empty() {
                // "/" shows home directory in the UI, so expand it here too
                dirs::home_dir()
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_else(|| "/".to_string())
            } else if path == "~" {
                dirs::home_dir()
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_else(|| "/".to_string())
            } else if let Some(rest) = path.strip_prefix("~/") {
                dirs::home_dir()
                    .map(|p| p.join(rest).to_string_lossy().to_string())
                    .unwrap_or_else(|| format!("/{}", rest))
            } else if path.starts_with('/') {
                path.to_string()
            } else {
                format!("/{}", path)
            };
            Ok((None, full_path))
        }
        TransferEndpoint::Host { host_id } => {
            // Direct SSH/SFTP to a host
            let host_info = host::get_host(host_id).await?;
            let ssh = host_info.ssh.ok_or_else(|| {
                AppError::invalid_input(format!("Host {} has no SSH configuration", host_id))
            })?;
            let config = build_sftp_config(&ssh).await?;
            // For hosts, path is absolute
            let full_path = if path.starts_with('/') {
                path.to_string()
            } else if path == "~" || path.starts_with("~/") {
                path.to_string()
            } else {
                format!("~/{}", path)
            };
            Ok((Some(config), full_path))
        }
        TransferEndpoint::Vast { instance_id } => {
            // Vast.ai instance - get SSH config from Vast API
            let cfg = crate::config::load_config().await?;
            let client = crate::vast::VastClient::from_cfg(&cfg)?;
            let inst = client.get_instance(*instance_id).await?;

            let host = inst.ssh_host.clone().unwrap_or_default().trim().to_string();
            let port = inst.ssh_port.unwrap_or(0);
            if host.is_empty() || port <= 0 {
                return Err(AppError::invalid_input(
                    "Vast instance does not have SSH info yet (is it running and provisioned?)",
                ));
            }

            let ssh = SshSpec {
                host,
                port,
                user: {
                    let u = cfg.vast.ssh_user.trim();
                    if u.is_empty() {
                        "root".to_string()
                    } else {
                        u.to_string()
                    }
                },
                key_path: match cfg
                    .vast
                    .ssh_key_path
                    .clone()
                    .filter(|s| !s.trim().is_empty())
                {
                    Some(s) => {
                        let p = crate::ssh_keys::materialize_private_key_path(&s).await?;
                        Some(p.to_string_lossy().to_string())
                    }
                    None => None,
                },
                extra_args: vec![],
            };

            let config = build_sftp_config(&ssh).await?;
            // For Vast instances, path is absolute (typically /root or /workspace)
            let full_path = if path.starts_with('/') {
                path.to_string()
            } else if path == "~" || path.starts_with("~/") {
                path.to_string()
            } else {
                format!("~/{}", path)
            };
            Ok((Some(config), full_path))
        }
        TransferEndpoint::Storage { storage_id } => {
            // Get storage and build spec
            let storage = storage_store.get(storage_id).await.ok_or_else(|| {
                AppError::not_found(format!("Storage not found: {}", storage_id))
            })?;
            build_remote_spec_async(&storage, path).await
        }
    }
}

fn create_temp_remote(prefix: &str, config: &serde_json::Value) -> Result<String, AppError> {
    let remote_name = format!(
        "{}_{}",
        prefix,
        uuid::Uuid::new_v4().to_string().replace("-", "")[..8].to_string()
    );

    let remote_type = config
        .get("type")
        .and_then(|v| v.as_str())
        .unwrap_or("local");

    // For Google Drive, use a different approach - create the remote without OAuth validation
    if remote_type == "drive" {
        // First create empty remote
        let create_params = serde_json::json!({
            "name": remote_name,
            "type": "drive",
            "parameters": {},
            "opt": {
                "nonInteractive": true,
                "obscure": false,
                "noAutocomplete": true,
            }
        });

        eprintln!("Creating Google Drive remote: {}", remote_name);
        librclone::rpc("config/create", &create_params.to_string())
            .map_err(|e| AppError::command(format!("Failed to create drive remote: {}", e)))?;

        // Then set parameters one by one using config/update
        if let Some(client_id) = config.get("client_id").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "client_id": client_id },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        if let Some(client_secret) = config.get("client_secret").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "client_secret": client_secret },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        if let Some(token) = config.get("token").and_then(|v| v.as_str()) {
            eprintln!("Setting token for {}", remote_name);
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "token": token },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        if let Some(scope) = config.get("scope").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "scope": scope },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }

        return Ok(remote_name);
    }

    // For other backends, use standard config/create
    let create_params = serde_json::json!({
        "name": remote_name,
        "type": remote_type,
        "parameters": config,
        "opt": {
            "nonInteractive": true,
            "obscure": false,
        }
    });

    librclone::rpc("config/create", &create_params.to_string())
        .map_err(|e| AppError::command(format!("Failed to create rclone remote: {}", e)))?;

    Ok(remote_name)
}

fn delete_temp_remote(remote_name: &str) {
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());
}

fn emit_transfer_progress(app: &AppHandle, task_id: &str, progress: TransferProgress) {
    let _ = app.emit(&format!("transfer-progress-{}", task_id), &progress);
    let _ = app.emit(
        "transfer-progress",
        serde_json::json!({
            "task_id": task_id,
            "progress": progress,
        }),
    );
}

/// Check if a Vast instance is running (has SSH access)
async fn is_vast_instance_running(instance_id: i64) -> Result<bool, AppError> {
    let cfg = crate::config::load_config().await?;
    let client = crate::vast::VastClient::from_cfg(&cfg)?;
    let inst = client.get_instance(instance_id).await?;
    let status = inst.actual_status.clone().unwrap_or_default().to_lowercase();
    Ok(status == "running")
}

/// Execute a unified transfer using endpoints
pub async fn execute_unified_transfer(
    task: &TransferTask,
    storage_store: &StorageStore,
    app: &AppHandle,
) -> Result<(), AppError> {
    let source_endpoint = task.get_source_endpoint();
    let dest_endpoint = task.get_dest_endpoint();

    // For Vast instances, require them to be running (use SFTP via rclone)
    match &source_endpoint {
        TransferEndpoint::Vast { instance_id } => {
            if !is_vast_instance_running(*instance_id).await.unwrap_or(false) {
                return Err(AppError::invalid_input(format!(
                    "Vast instance {} is not running. Please start the instance first.",
                    instance_id
                )));
            }
        }
        _ => {}
    }
    match &dest_endpoint {
        TransferEndpoint::Vast { instance_id } => {
            if !is_vast_instance_running(*instance_id).await.unwrap_or(false) {
                return Err(AppError::invalid_input(format!(
                    "Vast instance {} is not running. Please start the instance first.",
                    instance_id
                )));
            }
        }
        _ => {}
    }

    // Build source and destination paths
    let (src_remote, src_path) = build_endpoint_spec(&source_endpoint, &task.source_path, storage_store).await?;
    let (dst_remote, dst_path) = build_endpoint_spec(&dest_endpoint, &task.dest_path, storage_store).await?;

    // Get source name for destination path construction
    let source_name = std::path::Path::new(&task.source_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();

    // Create temporary remotes if needed
    let src_remote_name = if let Some(config) = src_remote {
        Some(create_temp_remote("src", &config)?)
    } else {
        None
    };

    let dst_remote_name = if let Some(config) = dst_remote {
        Some(create_temp_remote("dst", &config)?)
    } else {
        None
    };

    // Emit starting progress
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            current_file: Some("Starting transfer...".to_string()),
            ..Default::default()
        },
    );

    // Detect if source path looks like a file (has an extension and doesn't end with /)
    // This heuristic helps us choose between sync/copy (for directories) and
    // operations/copyfile (for single files)
    let source_looks_like_file = {
        let path = std::path::Path::new(&task.source_path);
        !task.source_path.ends_with('/')
            && path.extension().is_some()
            && !source_name.is_empty()
    };

    // For file-to-file transfers, destination should already specify the file
    // For directory transfers, we need to append the source folder name
    let final_dst_path = if source_looks_like_file {
        // File transfer: check if destination already ends with filename
        let dst_ends_with_source_name = dst_path.ends_with(&source_name)
            || dst_path.ends_with(&format!("/{}", source_name));

        if dst_ends_with_source_name {
            // Destination already specifies the target file
            dst_path.clone()
        } else if dst_path.ends_with('/') {
            // Destination is a directory, append filename
            format!("{}{}", dst_path, source_name)
        } else {
            // Destination doesn't have filename, append it
            format!("{}/{}", dst_path, source_name)
        }
    } else {
        // Directory transfer: append source folder name to destination
        if !source_name.is_empty() && !source_name.starts_with('.') {
            if dst_path.ends_with('/') {
                format!("{}{}", dst_path, source_name)
            } else {
                format!("{}/{}", dst_path, source_name)
            }
        } else {
            dst_path.clone()
        }
    };

    let src_fs = match &src_remote_name {
        Some(name) => format!("{}:{}", name, src_path),
        None => src_path.clone(),
    };

    let dst_fs = match &dst_remote_name {
        Some(name) => format!("{}:{}", name, final_dst_path),
        None => final_dst_path.clone(),
    };

    eprintln!("[transfer] src_fs: {}, dst_fs: {}, is_file: {}", src_fs, dst_fs, source_looks_like_file);

    // Choose the appropriate rclone method based on whether source is a file or directory
    let (rpc_method, sync_opts) = if source_looks_like_file {
        // For single file transfers, use sync/copy with the parent directory as source
        // and a filter to only copy the specific file.
        // The destination is also the parent directory (file will be copied with same name)
        let src_parent = std::path::Path::new(&src_path)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "/".to_string());

        let dst_parent = std::path::Path::new(&final_dst_path)
            .parent()
            .map(|p| p.to_string_lossy().to_string())
            .unwrap_or_else(|| "/".to_string());

        // Handle empty parent paths
        let src_parent = if src_parent.is_empty() { "/".to_string() } else { src_parent };
        let dst_parent = if dst_parent.is_empty() { "/".to_string() } else { dst_parent };

        let src_fs_dir = match &src_remote_name {
            Some(name) => format!("{}:{}", name, src_parent),
            None => src_parent,
        };

        let dst_fs_dir = match &dst_remote_name {
            Some(name) => format!("{}:{}", name, dst_parent),
            None => dst_parent,
        };

        eprintln!("[transfer] file copy: src_dir={}, dst_dir={}, file={}", src_fs_dir, dst_fs_dir, source_name);

        // Use IncludeRule with the exact filename to filter
        let opts = serde_json::json!({
            "srcFs": src_fs_dir,
            "dstFs": dst_fs_dir,
            "_async": true,
            "copyLinks": true,
            "_filter": {
                "IncludeRule": [format!("/{}", source_name)],
                "ExcludeRule": ["*"]
            }
        });
        ("sync/copy", opts)
    } else {
        // Use sync/copy for directory transfers
        let rpc = match task.operation {
            TransferOperation::Copy | TransferOperation::Move => "sync/copy",
            TransferOperation::Sync => "sync/sync",
            TransferOperation::SyncNoDelete => "sync/copy",
        };

        let mut opts = serde_json::json!({
            "srcFs": src_fs,
            "dstFs": dst_fs,
            "_async": true,
            "copyLinks": true,
        });

        if task.operation == TransferOperation::Sync {
            opts["deleteMode"] = serde_json::json!("sync");
        }
        (rpc, opts)
    };

    let result = librclone::rpc(rpc_method, &sync_opts.to_string());

    let job_id = match result {
        Ok(response) => {
            eprintln!("[transfer] rclone response: {}", response);
            // Parse job ID from response
            let parsed: serde_json::Value = serde_json::from_str(&response)
                .map_err(|e| AppError::command(format!("Failed to parse rclone response: {}", e)))?;
            let jid = parsed["jobid"].as_i64().unwrap_or(0);
            eprintln!("[transfer] job_id: {}", jid);
            jid
        }
        Err(e) => {
            eprintln!("[transfer] rclone error: {}", e);
            // Clean up remotes on error
            if let Some(name) = &src_remote_name {
                delete_temp_remote(name);
            }
            if let Some(name) = &dst_remote_name {
                delete_temp_remote(name);
            }
            return Err(AppError::command(format!("Transfer failed: {}", e)));
        }
    };

    // Poll for progress until job completes
    loop {
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;

        // Get job status
        let status_result = librclone::rpc(
            "job/status",
            &serde_json::json!({ "jobid": job_id }).to_string(),
        );

        match status_result {
            Ok(status_str) => {
                let status: serde_json::Value = serde_json::from_str(&status_str).unwrap_or_default();
                eprintln!("[transfer] job status: {}", status);

                let finished = status["finished"].as_bool().unwrap_or(false);
                let success = status["success"].as_bool().unwrap_or(false);
                let error_str = status["error"].as_str().unwrap_or("");

                // Extract progress info
                let bytes_done = status["bytes"].as_u64().unwrap_or(0);
                let bytes_total = status["totalBytes"].as_u64().unwrap_or(0);
                let speed = status["speed"].as_f64().unwrap_or(0.0) as u64;
                let eta = status["eta"].as_f64().map(|e| e as u64);

                // Get current file being transferred
                let current_file = status["transferring"]
                    .as_array()
                    .and_then(|arr| arr.first())
                    .and_then(|t| t["name"].as_str())
                    .map(|s| s.to_string());

                // Calculate files progress
                let transfers = status["transfers"].as_u64().unwrap_or(0);
                let checks = status["checks"].as_u64().unwrap_or(0);
                let files_done = transfers + checks;
                let files_total = status["totalTransfers"].as_u64().unwrap_or(0)
                    + status["totalChecks"].as_u64().unwrap_or(0);

                // Emit progress
                emit_transfer_progress(
                    app,
                    &task.id,
                    TransferProgress {
                        files_total: if files_total > 0 { files_total } else { 1 },
                        files_done,
                        bytes_total,
                        bytes_done,
                        speed_bps: speed,
                        eta_seconds: eta,
                        current_file,
                    },
                );

                if finished {
                    if !success && !error_str.is_empty() {
                        // Clean up remotes
                        if let Some(name) = &src_remote_name {
                            delete_temp_remote(name);
                        }
                        if let Some(name) = &dst_remote_name {
                            delete_temp_remote(name);
                        }
                        return Err(AppError::command(format!("Transfer failed: {}", error_str)));
                    }
                    break;
                }
            }
            Err(e) => {
                // Job might have completed, check if it's just not found
                eprintln!("[transfer] Error getting job status: {}", e);
                break;
            }
        }
    }

    // Clean up temporary remotes
    if let Some(name) = src_remote_name {
        delete_temp_remote(&name);
    }
    if let Some(name) = dst_remote_name {
        delete_temp_remote(&name);
    }

    // Emit completion
    emit_transfer_progress(
        app,
        &task.id,
        TransferProgress {
            files_done: 1,
            files_total: 1,
            bytes_done: 1,
            bytes_total: 1,
            current_file: None,
            ..Default::default()
        },
    );

    Ok(())
}

// ============================================================
// Tauri Commands
// ============================================================

#[tauri::command]
pub async fn transfer_list(app: AppHandle) -> Result<Vec<TransferTask>, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    Ok(store.list().await)
}

#[tauri::command]
pub async fn transfer_get(app: AppHandle, id: String) -> Result<TransferTask, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    store
        .get(&id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Transfer not found: {}", id)))
}

#[tauri::command]
pub async fn transfer_create(
    app: AppHandle,
    input: TransferCreateInput,
) -> Result<Vec<TransferTask>, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    let tasks = store.create(input).await?;

    // Try to start the queue processor
    let app_clone = app.clone();
    tokio::spawn(async move {
        process_transfer_queue(app_clone).await;
    });

    Ok(tasks)
}

#[tauri::command]
pub async fn transfer_cancel(app: AppHandle, id: String) -> Result<(), AppError> {
    let store = app.state::<Arc<TransferStore>>();
    store.cancel(&id).await
}

#[tauri::command]
pub async fn transfer_clear_completed(app: AppHandle) -> Result<(), AppError> {
    let store = app.state::<Arc<TransferStore>>();
    store.clear_completed().await
}

/// Create a unified transfer supporting any endpoint type
#[tauri::command]
pub async fn transfer_create_unified(
    app: AppHandle,
    input: UnifiedTransferInput,
) -> Result<Vec<TransferTask>, AppError> {
    let store = app.state::<Arc<TransferStore>>();
    let tasks = store.create_unified(input).await?;

    // Try to start the queue processor
    let app_clone = app.clone();
    tokio::spawn(async move {
        process_transfer_queue(app_clone).await;
    });

    Ok(tasks)
}

/// Process the transfer queue (runs one task at a time)
async fn process_transfer_queue(app: AppHandle) {
    let transfer_store = app.state::<Arc<TransferStore>>();
    let storage_store = app.state::<Arc<StorageStore>>();

    // Check if already running
    if transfer_store.is_running().await {
        return;
    }

    loop {
        // Get next queued task
        let task_id = match transfer_store.pop_queue().await {
            Some(id) => id,
            None => break, // No more tasks
        };

        // Mark as running
        transfer_store.set_running(Some(task_id.clone())).await;
        let _ = transfer_store
            .update_status(&task_id, TransferStatus::Running)
            .await;

        // Get task details
        let task = match transfer_store.get(&task_id).await {
            Some(t) => t,
            None => continue,
        };

        // Use unified transfer execution if we have endpoint info
        let result = if task.source_endpoint.is_some() || task.dest_endpoint.is_some() {
            // New unified execution
            execute_unified_transfer(&task, &storage_store, &app).await
        } else {
            // Legacy execution - get storages
            let source = match storage_store.get(&task.source_storage_id).await {
                Some(s) => s,
                None => {
                    let _ = transfer_store
                        .set_error(&task_id, "Source storage not found".to_string())
                        .await;
                    transfer_store.set_running(None).await;
                    continue;
                }
            };

            let dest = match storage_store.get(&task.dest_storage_id).await {
                Some(s) => s,
                None => {
                    let _ = transfer_store
                        .set_error(&task_id, "Destination storage not found".to_string())
                        .await;
                    transfer_store.set_running(None).await;
                    continue;
                }
            };

            execute_transfer(&task, &source, &dest, &app).await
        };

        match result {
            Ok(()) => {
                let _ = transfer_store
                    .update_status(&task_id, TransferStatus::Completed)
                    .await;
            }
            Err(e) => {
                let _ = transfer_store.set_error(&task_id, e.to_string()).await;
            }
        }

        // Clear running
        transfer_store.set_running(None).await;
    }
}
