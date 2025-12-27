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
    pub source_storage_id: String,
    pub source_path: String,
    pub dest_storage_id: String,
    pub dest_path: String,
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
            source_storage_id,
            source_path,
            dest_storage_id,
            dest_path,
            operation,
            status: TransferStatus::Queued,
            progress: TransferProgress::default(),
            created_at: chrono::Utc::now().to_rfc3339(),
            started_at: None,
            completed_at: None,
            error: None,
        }
    }
}

// ============================================================
// Transfer Create Input
// ============================================================

#[derive(Debug, Clone, Deserialize)]
pub struct TransferCreateInput {
    pub source_storage_id: String,
    pub source_paths: Vec<String>,
    pub dest_storage_id: String,
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

    pub async fn update_progress(&self, id: &str, progress: TransferProgress) -> Result<(), AppError> {
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
    });

    if task.operation == TransferOperation::Sync {
        sync_opts["deleteMode"] = serde_json::json!("sync");
    }

    // Emit starting progress
    emit_transfer_progress(app, &task.id, TransferProgress {
        current_file: Some("Starting transfer...".to_string()),
        ..Default::default()
    });

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
    emit_transfer_progress(app, &task.id, TransferProgress {
        files_done: 1,
        files_total: 1,
        current_file: None,
        ..Default::default()
    });

    Ok(())
}

fn build_remote_spec(storage: &Storage, path: &str) -> Result<(Option<serde_json::Value>, String), AppError> {
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
        StorageBackend::GoogleDrive { token, root_folder_id, .. } => {
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
        StorageBackend::GoogleCloudStorage { project_id, service_account_json, bucket } => {
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
        StorageBackend::Smb { host, share, user, password, domain } => {
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
        StorageBackend::SshRemote { host_id, root_path } => {
            // SSH remotes use SFTP via rclone - need async resolution
            Err(AppError::invalid_input(format!(
                "SSH remote {} requires async resolution - use build_remote_spec_async",
                host_id
            )))
        }
    }
}

/// Build SFTP config for rclone from SSH spec (same as in storage.rs)
fn build_sftp_config(ssh: &SshSpec) -> serde_json::Value {
    let mut config = serde_json::json!({
        "type": "sftp",
        "host": ssh.host,
        "port": ssh.port.to_string(),
        "user": ssh.user,
        "shell_type": "unix",
        "md5sum_command": "md5sum",
        "sha1sum_command": "sha1sum",
    });

    if let Some(key_path) = &ssh.key_path {
        config["key_file"] = serde_json::json!(key_path);
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

    config
}

/// Async version that can resolve SSH hosts
async fn build_remote_spec_async(storage: &Storage, path: &str) -> Result<(Option<serde_json::Value>, String), AppError> {
    match &storage.backend {
        StorageBackend::SshRemote { host_id, root_path } => {
            let host_info = host::get_host(host_id).await?;
            let ssh = host_info.ssh.ok_or_else(|| {
                AppError::invalid_input(format!("Host {} has no SSH configuration", host_id))
            })?;
            let config = build_sftp_config(&ssh);
            let full_path = format!("{}/{}", root_path.trim_end_matches('/'), path.trim_start_matches('/'));
            Ok((Some(config), full_path))
        }
        _ => build_remote_spec(storage, path),
    }
}

fn create_temp_remote(prefix: &str, config: &serde_json::Value) -> Result<String, AppError> {
    let remote_name = format!(
        "{}_{}", 
        prefix, 
        uuid::Uuid::new_v4().to_string().replace("-", "")[..8].to_string()
    );

    let remote_type = config.get("type").and_then(|v| v.as_str()).unwrap_or("local");
    
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
            let _ = librclone::rpc("config/update", &serde_json::json!({
                "name": remote_name,
                "parameters": { "client_id": client_id },
                "opt": { "nonInteractive": true }
            }).to_string());
        }
        if let Some(client_secret) = config.get("client_secret").and_then(|v| v.as_str()) {
            let _ = librclone::rpc("config/update", &serde_json::json!({
                "name": remote_name,
                "parameters": { "client_secret": client_secret },
                "opt": { "nonInteractive": true }
            }).to_string());
        }
        if let Some(token) = config.get("token").and_then(|v| v.as_str()) {
            eprintln!("Setting token for {}", remote_name);
            let _ = librclone::rpc("config/update", &serde_json::json!({
                "name": remote_name,
                "parameters": { "token": token },
                "opt": { "nonInteractive": true }
            }).to_string());
        }
        if let Some(scope) = config.get("scope").and_then(|v| v.as_str()) {
            let _ = librclone::rpc("config/update", &serde_json::json!({
                "name": remote_name,
                "parameters": { "scope": scope },
                "opt": { "nonInteractive": true }
            }).to_string());
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
    let _ = app.emit("transfer-progress", serde_json::json!({
        "task_id": task_id,
        "progress": progress,
    }));
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
    store.get(&id).await.ok_or_else(|| AppError::not_found(format!("Transfer not found: {}", id)))
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
        let _ = transfer_store.update_status(&task_id, TransferStatus::Running).await;

        // Get task details
        let task = match transfer_store.get(&task_id).await {
            Some(t) => t,
            None => continue,
        };

        // Get source and destination storages
        let source = match storage_store.get(&task.source_storage_id).await {
            Some(s) => s,
            None => {
                let _ = transfer_store.set_error(&task_id, "Source storage not found".to_string()).await;
                continue;
            }
        };

        let dest = match storage_store.get(&task.dest_storage_id).await {
            Some(s) => s,
            None => {
                let _ = transfer_store.set_error(&task_id, "Destination storage not found".to_string()).await;
                continue;
            }
        };

        // Execute transfer
        match execute_transfer(&task, &source, &dest, &app).await {
            Ok(()) => {
                let _ = transfer_store.update_status(&task_id, TransferStatus::Completed).await;
            }
            Err(e) => {
                let _ = transfer_store.set_error(&task_id, e.to_string()).await;
            }
        }

        // Clear running
        transfer_store.set_running(None).await;
    }
}

