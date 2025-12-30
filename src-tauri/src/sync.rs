use std::path::Path;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};

use crate::error::AppError;
use crate::ssh::SshSpec;

// ============================================================
// Types
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SyncPhase {
    Preparing,
    Uploading,
    Completed,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncProgress {
    pub session_id: String,
    pub phase: SyncPhase,
    pub files_total: u64,
    pub files_done: u64,
    pub bytes_total: u64,
    pub bytes_done: u64,
    pub current_file: Option<String>,
    pub error: Option<String>,
    pub speed: Option<String>,
    pub eta: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncConfig {
    pub local_path: String,
    pub remote_path: String,
    pub use_gitignore: bool,
    pub extra_excludes: Vec<String>,
    pub delete_remote: bool,
}

// ============================================================
// Rclone Remote Configuration
// ============================================================

/// Build SFTP remote config for rclone
fn build_sftp_remote_config(ssh: &SshSpec) -> serde_json::Value {
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

    // Handle proxy command for cloudflared
    for i in 0..ssh.extra_args.len() {
        if ssh.extra_args[i] == "-o" && i + 1 < ssh.extra_args.len() {
            let arg = &ssh.extra_args[i + 1];
            if arg.starts_with("ProxyCommand=") {
                let proxy_cmd = arg.strip_prefix("ProxyCommand=").unwrap_or("");
                // Use ssh command with proxy for cloudflared tunnels
                config["ssh"] = serde_json::json!(format!(
                    "ssh -o ProxyCommand={} -o StrictHostKeyChecking=accept-new",
                    proxy_cmd
                ));
            }
        }
    }

    config
}

/// Create rclone remote configuration string
fn create_remote_name() -> String {
    format!(
        "doppio_{}",
        uuid::Uuid::new_v4().to_string().replace("-", "")[..8].to_string()
    )
}

// ============================================================
// Sync Operations
// ============================================================

/// Initialize rclone (call once at startup)
pub fn init_rclone() {
    librclone::initialize();
}

/// Sync local directory to remote via SFTP using rclone
pub async fn sync_to_remote(
    session_id: &str,
    ssh: &SshSpec,
    config: &SyncConfig,
    app: Option<&AppHandle>,
) -> Result<(), AppError> {
    // Validate local path exists
    let local_path = Path::new(&config.local_path);
    if !local_path.exists() {
        return Err(AppError::invalid_input(format!(
            "Local path does not exist: {}",
            config.local_path
        )));
    }

    let session_id = session_id.to_string();

    // Emit starting progress
    emit_progress(
        app,
        &session_id,
        SyncProgress {
            session_id: session_id.clone(),
            phase: SyncPhase::Preparing,
            files_total: 0,
            files_done: 0,
            bytes_total: 0,
            bytes_done: 0,
            current_file: None,
            error: None,
            speed: None,
            eta: None,
        },
    );

    // Build remote config
    let remote_name = create_remote_name();
    let remote_config = build_sftp_remote_config(ssh);

    // Create the remote in rclone
    let create_params = serde_json::json!({
      "name": remote_name,
      "type": "sftp",
      "parameters": remote_config,
    });

    let result = librclone::rpc("config/create", &create_params.to_string());
    if let Err(e) = &result {
        return Err(AppError::command(format!(
            "Failed to create rclone remote: {}",
            e
        )));
    }

    // Build exclude filters
    let mut filter_rules = Vec::new();

    // Add gitignore-style excludes
    if config.use_gitignore {
        let gitignore_path = local_path.join(".gitignore");
        if gitignore_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&gitignore_path) {
                for line in content.lines() {
                    let line = line.trim();
                    if !line.is_empty() && !line.starts_with('#') {
                        filter_rules.push(format!("- {}", line));
                    }
                }
            }
        }
    }

    // Add extra excludes
    for exclude in &config.extra_excludes {
        filter_rules.push(format!("- {}", exclude));
    }

    // Common excludes for ML projects
    filter_rules.extend(vec![
        "- .git/**".to_string(),
        "- __pycache__/**".to_string(),
        "- *.pyc".to_string(),
        "- .venv/**".to_string(),
        "- venv/**".to_string(),
        "- node_modules/**".to_string(),
        "- .DS_Store".to_string(),
    ]);

    // Build sync options
    let mut sync_opts = serde_json::json!({
      "srcFs": config.local_path,
      "dstFs": format!("{}:{}", remote_name, config.remote_path),
      "_async": false,
    });

    // Add filter rules
    if !filter_rules.is_empty() {
        sync_opts["_filter"] = serde_json::json!({
          "FilterRule": filter_rules,
        });
    }

    if config.delete_remote {
        sync_opts["deleteMode"] = serde_json::json!("sync");
    }

    // Emit uploading progress
    emit_progress(
        app,
        &session_id,
        SyncProgress {
            session_id: session_id.clone(),
            phase: SyncPhase::Uploading,
            files_total: 0,
            files_done: 0,
            bytes_total: 0,
            bytes_done: 0,
            current_file: Some("Starting sync...".to_string()),
            error: None,
            speed: None,
            eta: None,
        },
    );

    // Run sync operation
    let sync_result = librclone::rpc("sync/sync", &sync_opts.to_string());

    // Clean up remote config
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());

    match sync_result {
        Ok(_) => {
            emit_progress(
                app,
                &session_id,
                SyncProgress {
                    session_id: session_id.clone(),
                    phase: SyncPhase::Completed,
                    files_total: 0,
                    files_done: 0,
                    bytes_total: 0,
                    bytes_done: 0,
                    current_file: None,
                    error: None,
                    speed: None,
                    eta: None,
                },
            );
            Ok(())
        }
        Err(e) => {
            let error_msg = e.to_string();
            emit_progress(
                app,
                &session_id,
                SyncProgress {
                    session_id: session_id.clone(),
                    phase: SyncPhase::Failed,
                    files_total: 0,
                    files_done: 0,
                    bytes_total: 0,
                    bytes_done: 0,
                    current_file: None,
                    error: Some(error_msg.clone()),
                    speed: None,
                    eta: None,
                },
            );
            Err(AppError::command(format!("Sync failed: {}", error_msg)))
        }
    }
}

/// Download remote directory to local
pub async fn sync_from_remote(
    session_id: &str,
    ssh: &SshSpec,
    remote_path: &str,
    local_path: &str,
    app: Option<&AppHandle>,
) -> Result<(), AppError> {
    let session_id = session_id.to_string();

    // Create local directory if it doesn't exist
    let local_dir = Path::new(local_path);
    if !local_dir.exists() {
        std::fs::create_dir_all(local_dir)?;
    }

    emit_progress(
        app,
        &session_id,
        SyncProgress {
            session_id: session_id.clone(),
            phase: SyncPhase::Preparing,
            files_total: 0,
            files_done: 0,
            bytes_total: 0,
            bytes_done: 0,
            current_file: None,
            error: None,
            speed: None,
            eta: None,
        },
    );

    // Build remote config
    let remote_name = create_remote_name();
    let remote_config = build_sftp_remote_config(ssh);

    // Create the remote
    let create_params = serde_json::json!({
      "name": remote_name,
      "type": "sftp",
      "parameters": remote_config,
    });

    let result = librclone::rpc("config/create", &create_params.to_string());
    if let Err(e) = &result {
        return Err(AppError::command(format!(
            "Failed to create rclone remote: {}",
            e
        )));
    }

    emit_progress(
        app,
        &session_id,
        SyncProgress {
            session_id: session_id.clone(),
            phase: SyncPhase::Uploading,
            files_total: 0,
            files_done: 0,
            bytes_total: 0,
            bytes_done: 0,
            current_file: Some("Downloading...".to_string()),
            error: None,
            speed: None,
            eta: None,
        },
    );

    // Run copy operation (download)
    let copy_opts = serde_json::json!({
      "srcFs": format!("{}:{}", remote_name, remote_path),
      "dstFs": local_path,
      "_async": false,
    });

    let copy_result = librclone::rpc("sync/copy", &copy_opts.to_string());

    // Clean up remote config
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());

    match copy_result {
        Ok(_) => {
            emit_progress(
                app,
                &session_id,
                SyncProgress {
                    session_id: session_id.clone(),
                    phase: SyncPhase::Completed,
                    files_total: 0,
                    files_done: 0,
                    bytes_total: 0,
                    bytes_done: 0,
                    current_file: None,
                    error: None,
                    speed: None,
                    eta: None,
                },
            );
            Ok(())
        }
        Err(e) => {
            let error_msg = e.to_string();
            emit_progress(
                app,
                &session_id,
                SyncProgress {
                    session_id: session_id.clone(),
                    phase: SyncPhase::Failed,
                    files_total: 0,
                    files_done: 0,
                    bytes_total: 0,
                    bytes_done: 0,
                    current_file: None,
                    error: Some(error_msg.clone()),
                    speed: None,
                    eta: None,
                },
            );
            Err(AppError::command(format!("Download failed: {}", error_msg)))
        }
    }
}

/// Helper to emit sync progress events
fn emit_progress(app: Option<&AppHandle>, session_id: &str, progress: SyncProgress) {
    if let Some(app) = app {
        let _ = app.emit(&format!("sync-progress-{}", session_id), &progress);
        let _ = app.emit("sync-progress", &progress);
    }
}

// ============================================================
// Utility Functions
// ============================================================

/// List files in remote directory
pub async fn list_remote(ssh: &SshSpec, remote_path: &str) -> Result<Vec<String>, AppError> {
    let remote_name = create_remote_name();
    let remote_config = build_sftp_remote_config(ssh);

    // Create the remote
    let create_params = serde_json::json!({
      "name": remote_name,
      "type": "sftp",
      "parameters": remote_config,
    });

    librclone::rpc("config/create", &create_params.to_string())
        .map_err(|e| AppError::command(format!("Failed to create rclone remote: {}", e)))?;

    // List files
    let list_opts = serde_json::json!({
      "fs": format!("{}:{}", remote_name, remote_path),
      "remote": "",
      "opt": {
        "recurse": false,
      }
    });

    let result = librclone::rpc("operations/list", &list_opts.to_string());

    // Clean up
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());

    match result {
        Ok(output) => {
            let parsed: serde_json::Value = serde_json::from_str(&output)
                .map_err(|e| AppError::command(format!("Failed to parse list output: {}", e)))?;

            let mut files = Vec::new();
            if let Some(list) = parsed.get("list").and_then(|l| l.as_array()) {
                for item in list {
                    if let Some(path) = item.get("Path").and_then(|p| p.as_str()) {
                        files.push(path.to_string());
                    }
                }
            }
            Ok(files)
        }
        Err(e) => Err(AppError::command(format!("Failed to list remote: {}", e))),
    }
}

/// Check if remote path exists
pub async fn remote_exists(ssh: &SshSpec, remote_path: &str) -> Result<bool, AppError> {
    let remote_name = create_remote_name();
    let remote_config = build_sftp_remote_config(ssh);

    // Create the remote
    let create_params = serde_json::json!({
      "name": remote_name,
      "type": "sftp",
      "parameters": remote_config,
    });

    librclone::rpc("config/create", &create_params.to_string())
        .map_err(|e| AppError::command(format!("Failed to create rclone remote: {}", e)))?;

    // Check if exists using stat
    let stat_opts = serde_json::json!({
      "fs": format!("{}:{}", remote_name, remote_path),
      "remote": "",
    });

    let result = librclone::rpc("operations/stat", &stat_opts.to_string());

    // Clean up
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());

    match result {
        Ok(output) => {
            let parsed: serde_json::Value = serde_json::from_str(&output).unwrap_or_default();
            // If item exists, it will have data
            Ok(parsed.get("item").is_some())
        }
        Err(_) => Ok(false),
    }
}
