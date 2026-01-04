//! Storage management module
//!
//! Provides unified storage abstraction for local files, SSH remotes, and cloud storage.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use aws_config::{BehaviorVersion, Region};
use aws_credential_types::Credentials;
use aws_sdk_s3 as s3;
use s3::error::ProvideErrorMetadata;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};
use tokio::sync::RwLock;

use crate::error::AppError;
use crate::host;
use crate::ssh::SshSpec;

// ============================================================
// Storage Backend Types
// ============================================================

/// Backend configuration for different storage types
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum StorageBackend {
    /// Local filesystem
    Local { root_path: String },

    /// SSH/SFTP remote (references an existing Host)
    SshRemote { host_id: String, root_path: String },

    /// Google Drive via OAuth
    GoogleDrive {
        client_id: Option<String>,
        client_secret: Option<String>,
        token: Option<String>,
        root_folder_id: Option<String>,
    },

    /// Cloudflare R2 (S3-compatible)
    CloudflareR2 {
        account_id: String,
        access_key_id: String,
        secret_access_key: String,
        bucket: String,
        endpoint: Option<String>,
    },

    /// Google Cloud Storage
    GoogleCloudStorage {
        project_id: String,
        service_account_json: Option<String>,
        bucket: String,
    },

    /// SMB/CIFS (NAS)
    Smb {
        host: String,
        share: String,
        user: Option<String>,
        password: Option<String>,
        domain: Option<String>,
    },
}

impl StorageBackend {
    /// Get a display name for this backend type
    pub fn type_name(&self) -> &'static str {
        match self {
            Self::Local { .. } => "Local",
            Self::SshRemote { .. } => "SSH Remote",
            Self::GoogleDrive { .. } => "Google Drive",
            Self::CloudflareR2 { .. } => "Cloudflare R2",
            Self::GoogleCloudStorage { .. } => "Google Cloud Storage",
            Self::Smb { .. } => "SMB/NAS",
        }
    }

    /// Get default icon for this backend type
    pub fn default_icon(&self) -> &'static str {
        match self {
            Self::Local { .. } => "💻",
            Self::SshRemote { .. } => "🖥️",
            Self::GoogleDrive { .. } => "📁",
            Self::CloudflareR2 { .. } => "☁️",
            Self::GoogleCloudStorage { .. } => "🌐",
            Self::Smb { .. } => "🗄️",
        }
    }
}

// ============================================================
// Storage Model
// ============================================================

/// A configured storage location
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Storage {
    pub id: String,
    pub name: String,
    pub icon: Option<String>,
    pub backend: StorageBackend,
    pub readonly: bool,
    pub created_at: String,
    pub last_accessed_at: Option<String>,
}

impl Storage {
    pub fn new(name: String, backend: StorageBackend) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name,
            icon: Some(backend.default_icon().to_string()),
            backend,
            readonly: false,
            created_at: chrono::Utc::now().to_rfc3339(),
            last_accessed_at: None,
        }
    }

    /// Get display icon (custom or default)
    pub fn display_icon(&self) -> &str {
        self.icon.as_deref().unwrap_or(self.backend.default_icon())
    }
}

// ============================================================
// File Entry
// ============================================================

/// Represents a file or directory entry
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileEntry {
    pub name: String,
    pub path: String,
    pub is_dir: bool,
    pub size: u64,
    pub modified_at: Option<String>,
    pub mime_type: Option<String>,
}

// ============================================================
// Storage Create/Update Input
// ============================================================

#[derive(Debug, Clone, Deserialize)]
pub struct StorageCreateInput {
    pub name: String,
    pub icon: Option<String>,
    pub backend: StorageBackend,
    pub readonly: Option<bool>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct StorageUpdateInput {
    pub name: Option<String>,
    pub icon: Option<String>,
    pub readonly: Option<bool>,
    pub backend: Option<StorageBackend>,
}

// ============================================================
// Storage Test Result
// ============================================================

#[derive(Debug, Clone, Serialize)]
pub struct StorageTestResult {
    pub success: bool,
    pub message: String,
    pub latency_ms: Option<u64>,
}

// ============================================================
// Cloudflare R2 (API helpers)
// ============================================================

#[derive(Debug, Clone, Serialize)]
pub struct R2PurgeDeleteResult {
    pub deleted_objects: u64,
    pub bucket_deleted: bool,
    pub local_storage_deleted: bool,
}

fn validate_cloudflare_account_id(account_id: &str) -> Result<(), AppError> {
    // Cloudflare account_id is typically a 32-char hex string.
    let ok = account_id.len() == 32 && account_id.chars().all(|c| c.is_ascii_hexdigit());
    if !ok {
        return Err(AppError::invalid_input(
            "Invalid Cloudflare account_id (expected 32 hex chars)",
        ));
    }
    Ok(())
}

fn validate_r2_bucket_name(bucket: &str) -> Result<(), AppError> {
    // Minimal S3-style bucket validation to avoid accidental malformed requests.
    if bucket.len() < 3 || bucket.len() > 63 {
        return Err(AppError::invalid_input(
            "Invalid bucket name length (expected 3..=63)",
        ));
    }
    if !bucket
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
    {
        return Err(AppError::invalid_input(
            "Invalid bucket name (allowed: a-z, 0-9, '-')",
        ));
    }
    if !bucket
        .chars()
        .next()
        .is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        || !bucket
            .chars()
            .last()
            .is_some_and(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
    {
        return Err(AppError::invalid_input(
            "Invalid bucket name (must start/end with [a-z0-9])",
        ));
    }
    Ok(())
}

fn validate_non_empty(label: &str, value: &str) -> Result<(), AppError> {
    if value.trim().is_empty() {
        return Err(AppError::invalid_input(format!("{} is required", label)));
    }
    Ok(())
}

async fn build_r2_s3_client(
    account_id: &str,
    access_key_id: &str,
    secret_access_key: &str,
    endpoint: Option<&str>,
) -> Result<s3::Client, AppError> {
    validate_cloudflare_account_id(account_id)?;
    validate_non_empty("access_key_id", access_key_id)?;
    validate_non_empty("secret_access_key", secret_access_key)?;

    let endpoint = endpoint
        .filter(|e| !e.trim().is_empty())
        .map(|e| e.to_string())
        .unwrap_or_else(|| format!("https://{}.r2.cloudflarestorage.com", account_id));

    let shared_config = aws_config::defaults(BehaviorVersion::latest())
        .region(Region::new("auto"))
        .credentials_provider(Credentials::new(
            access_key_id,
            secret_access_key,
            None,
            None,
            "cloudflare_r2",
        ))
        .load()
        .await;

    let s3_config = s3::config::Builder::from(&shared_config)
        .endpoint_url(endpoint)
        // R2 endpoints typically work best with path-style addressing.
        .force_path_style(true)
        .build();

    Ok(s3::Client::from_conf(s3_config))
}

async fn r2_delete_all_objects(client: &s3::Client, bucket: &str) -> Result<u64, AppError> {
    validate_r2_bucket_name(bucket)?;

    let mut deleted_objects: u64 = 0;
    let mut continuation_token: Option<String> = None;

    loop {
        let mut req = client
            .list_objects_v2()
            .bucket(bucket)
            .max_keys(1000);

        if let Some(token) = continuation_token.take() {
            req = req.continuation_token(token);
        }

        let resp = match req.send().await {
            Ok(resp) => resp,
            Err(e) => {
                // If the bucket is already gone (e.g. deleted in the Cloudflare UI), treat purge as a no-op.
                let no_such_bucket = matches!(
                    e,
                    s3::error::SdkError::ServiceError(ref se)
                        if matches!(se.err().code(), Some("NoSuchBucket" | "NoSuchBucketException"))
                );
                if no_such_bucket {
                    return Ok(deleted_objects);
                }
                return Err(AppError::network(format!("R2 list objects failed: {}", e)));
            }
        };

        let mut keys: Vec<String> = Vec::new();
        if let Some(contents) = resp.contents {
            for obj in contents {
                if let Some(key) = obj.key {
                    keys.push(key);
                }
            }
        }

        if !keys.is_empty() {
            for chunk in keys.chunks(1000) {
                let objects = chunk
                    .iter()
                    .map(|k| {
                        s3::types::ObjectIdentifier::builder()
                            .key(k)
                            .build()
                            .map_err(|e| AppError::internal(format!("Failed to build object id: {}", e)))
                    })
                    .collect::<Result<Vec<_>, AppError>>()?;

                let delete = s3::types::Delete::builder()
                    .set_objects(Some(objects))
                    .quiet(true)
                    .build()
                    .map_err(|e| AppError::internal(format!("Failed to build delete request: {}", e)))?;

                let del_resp = client
                    .delete_objects()
                    .bucket(bucket)
                    .delete(delete)
                    .send()
                    .await
                    .map_err(|e| AppError::network(format!("R2 delete objects failed: {}", e)))?;

                if let Some(errors) = del_resp.errors {
                    if !errors.is_empty() {
                        let first = &errors[0];
                        let key = first.key.as_deref().unwrap_or("<unknown>");
                        let code = first.code.as_deref().unwrap_or("<unknown>");
                        let message = first.message.as_deref().unwrap_or("<unknown>");
                        return Err(AppError::network(format!(
                            "R2 delete objects returned errors: key={}, code={}, message={}",
                            key, code, message
                        )));
                    }
                }

                deleted_objects = deleted_objects.saturating_add(chunk.len() as u64);
            }
        }

        if !resp.is_truncated.unwrap_or(false) {
            break;
        }
        continuation_token = resp.next_continuation_token;
    }

    Ok(deleted_objects)
}

async fn cloudflare_r2_delete_bucket(
    account_id: &str,
    bucket: &str,
    api_token: &str,
) -> Result<(), AppError> {
    validate_cloudflare_account_id(account_id)?;
    validate_r2_bucket_name(bucket)?;
    validate_non_empty("Cloudflare API token", api_token)?;

    let url = format!(
        "https://api.cloudflare.com/client/v4/accounts/{}/r2/buckets/{}",
        account_id, bucket
    );

    let client = reqwest::Client::new();
    let resp = client
        .delete(url)
        .bearer_auth(api_token)
        .send()
        .await
        .map_err(|e| AppError::http(format!("Cloudflare API request failed: {}", e)))?;

    let status = resp.status();
    let text = resp.text().await.unwrap_or_default();

    if !status.is_success() {
        // Deleting an already-deleted bucket should be idempotent.
        if status.as_u16() == 404 {
            return Ok(());
        }
        if status.as_u16() == 401 || status.as_u16() == 403 {
            return Err(AppError::permission_denied(format!(
                "Cloudflare API token is unauthorized or lacks permission: status={}, body={}",
                status, text
            )));
        }
        return Err(AppError::http(format!(
            "Cloudflare API delete bucket failed: status={}, body={}",
            status, text
        )));
    }

    let v: serde_json::Value = serde_json::from_str(&text).unwrap_or(serde_json::json!({}));
    if v
        .get("success")
        .and_then(|b| b.as_bool())
        .unwrap_or(false)
    {
        return Ok(());
    }

    let errors = v
        .get("errors")
        .and_then(|e| e.as_array())
        .cloned()
        .unwrap_or_default();
    Err(AppError::http(format!(
        "Cloudflare API delete bucket returned success=false: errors={}",
        serde_json::Value::Array(errors)
    )))
}

async fn cloudflare_r2_bucket_exists(
    account_id: &str,
    bucket: &str,
    api_token: &str,
) -> Result<bool, AppError> {
    validate_cloudflare_account_id(account_id)?;
    validate_r2_bucket_name(bucket)?;
    validate_non_empty("Cloudflare API token", api_token)?;

    let url = format!(
        "https://api.cloudflare.com/client/v4/accounts/{}/r2/buckets/{}",
        account_id, bucket
    );

    let client = reqwest::Client::new();
    let resp = client
        .get(url)
        .bearer_auth(api_token)
        .send()
        .await
        .map_err(|e| AppError::http(format!("Cloudflare API request failed: {}", e)))?;

    let status = resp.status();
    let text = resp.text().await.unwrap_or_default();

    if status.as_u16() == 404 {
        return Ok(false);
    }
    if status.as_u16() == 401 || status.as_u16() == 403 {
        return Err(AppError::permission_denied(format!(
            "Cloudflare API token is unauthorized or lacks permission: status={}, body={}",
            status, text
        )));
    }
    if !status.is_success() {
        return Err(AppError::http(format!(
            "Cloudflare API get bucket failed: status={}, body={}",
            status, text
        )));
    }

    Ok(true)
}

// ============================================================
// Storage Store (in-memory + file persistence)
// ============================================================

pub struct StorageStore {
    storages: RwLock<HashMap<String, Storage>>,
    data_path: PathBuf,
}

impl StorageStore {
    pub fn new(data_dir: &std::path::Path) -> Self {
        let data_path = data_dir.join("storages.json");
        let storages = Self::load_from_file(&data_path).unwrap_or_default();
        Self {
            storages: RwLock::new(storages),
            data_path,
        }
    }

    fn load_from_file(path: &PathBuf) -> Option<HashMap<String, Storage>> {
        let content = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&content).ok()
    }

    async fn save_to_file(&self) -> Result<(), AppError> {
        // Clone data while holding lock, then release before I/O
        let content = {
            let storages = self.storages.read().await;
            serde_json::to_string_pretty(&*storages)?
        };
        // Use async file write to avoid blocking
        tokio::fs::write(&self.data_path, content).await?;
        Ok(())
    }

    pub async fn list(&self) -> Vec<Storage> {
        let storages = self.storages.read().await;
        storages.values().cloned().collect()
    }

    pub async fn get(&self, id: &str) -> Option<Storage> {
        let storages = self.storages.read().await;
        storages.get(id).cloned()
    }

    pub async fn create(&self, input: StorageCreateInput) -> Result<Storage, AppError> {
        let storage = Storage {
            id: uuid::Uuid::new_v4().to_string(),
            name: input.name,
            icon: input
                .icon
                .or_else(|| Some(input.backend.default_icon().to_string())),
            backend: input.backend,
            readonly: input.readonly.unwrap_or(false),
            created_at: chrono::Utc::now().to_rfc3339(),
            last_accessed_at: None,
        };

        {
            let mut storages = self.storages.write().await;
            storages.insert(storage.id.clone(), storage.clone());
        }
        self.save_to_file().await?;
        Ok(storage)
    }

    pub async fn update(&self, id: &str, input: StorageUpdateInput) -> Result<Storage, AppError> {
        let mut storages = self.storages.write().await;
        let storage = storages
            .get_mut(id)
            .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", id)))?;

        if let Some(name) = input.name {
            storage.name = name;
        }
        if let Some(icon) = input.icon {
            storage.icon = Some(icon);
        }
        if let Some(readonly) = input.readonly {
            storage.readonly = readonly;
        }
        if let Some(backend) = input.backend {
            storage.backend = backend;
        }

        let storage = storage.clone();
        drop(storages);
        self.save_to_file().await?;
        Ok(storage)
    }

    pub async fn delete(&self, id: &str) -> Result<(), AppError> {
        let mut storages = self.storages.write().await;
        storages
            .remove(id)
            .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", id)))?;
        drop(storages);
        self.save_to_file().await?;
        Ok(())
    }

    pub async fn update_last_accessed(&self, id: &str) -> Result<(), AppError> {
        let mut storages = self.storages.write().await;
        if let Some(storage) = storages.get_mut(id) {
            storage.last_accessed_at = Some(chrono::Utc::now().to_rfc3339());
        }
        drop(storages);
        self.save_to_file().await?;
        Ok(())
    }
}

// ============================================================
// rclone Remote Operations
// ============================================================

/// Build SFTP config for rclone from SSH spec
fn build_sftp_config(ssh: &SshSpec) -> serde_json::Value {
    // Always use external ssh command for:
    // 1. ssh-agent support (rclone's built-in SSH has issues with it)
    // 2. Proper host key handling with StrictHostKeyChecking=no
    // 3. ProxyCommand support for cloudflared tunnels

    let mut ssh_cmd_parts = vec![
        "ssh".to_string(),
        "-o".to_string(),
        "StrictHostKeyChecking=no".to_string(),
        "-o".to_string(),
        "UserKnownHostsFile=/dev/null".to_string(),
        "-o".to_string(),
        "LogLevel=ERROR".to_string(),
        "-p".to_string(),
        ssh.port.to_string(),
    ];

    // Add identity file if specified
    if let Some(key_path) = &ssh.key_path {
        ssh_cmd_parts.push("-i".to_string());
        ssh_cmd_parts.push(key_path.clone());
    }

    // Handle extra args (ProxyCommand, etc.)
    for i in 0..ssh.extra_args.len() {
        if ssh.extra_args[i] == "-o" && i + 1 < ssh.extra_args.len() {
            ssh_cmd_parts.push("-o".to_string());
            ssh_cmd_parts.push(ssh.extra_args[i + 1].clone());
        }
    }

    // Add user@host as positional argument (required for external ssh)
    ssh_cmd_parts.push(format!("{}@{}", ssh.user, ssh.host));

    // When using external ssh command, don't include host/port/user in config
    // as rclone ignores them anyway (and warns about it)
    serde_json::json!({
        "type": "sftp",
        "shell_type": "unix",
        "md5sum_command": "md5sum",
        "sha1sum_command": "sha1sum",
        "ssh": ssh_cmd_parts.join(" "),
    })
}

/// Build rclone remote config from StorageBackend (for non-SSH backends)
fn build_rclone_config(backend: &StorageBackend) -> Result<serde_json::Value, AppError> {
    match backend {
        StorageBackend::Local { root_path: _ } => Ok(serde_json::json!({
            "type": "local",
        })),
        StorageBackend::SshRemote { host_id, .. } => {
            // SSH remotes should use build_sftp_config_for_host instead
            Err(AppError::invalid_input(format!(
                "Use build_sftp_config_for_host for SSH remote: {}",
                host_id
            )))
        }
        StorageBackend::GoogleDrive {
            client_id,
            client_secret,
            token,
            root_folder_id,
        } => {
            let mut config = serde_json::json!({
                "type": "drive",
                "scope": "drive",
            });

            if let Some(id) = client_id {
                config["client_id"] = serde_json::json!(id);
            }
            if let Some(secret) = client_secret {
                config["client_secret"] = serde_json::json!(secret);
            }
            if let Some(token) = token {
                config["token"] = serde_json::json!(token);
            }
            eprintln!("GDrive config: using OAuth, has_token={}", token.is_some());

            if let Some(folder_id) = root_folder_id {
                config["root_folder_id"] = serde_json::json!(folder_id);
            }
            Ok(config)
        }
        StorageBackend::CloudflareR2 {
            account_id,
            access_key_id,
            secret_access_key,
            bucket: _,
            endpoint,
        } => {
            let endpoint = endpoint
                .clone()
                .unwrap_or_else(|| format!("https://{}.r2.cloudflarestorage.com", account_id));
            Ok(serde_json::json!({
                "type": "s3",
                "provider": "Cloudflare",
                "access_key_id": access_key_id,
                "secret_access_key": secret_access_key,
                "endpoint": endpoint,
                "acl": "private",
            }))
        }
        StorageBackend::GoogleCloudStorage {
            project_id,
            service_account_json,
            bucket: _,
        } => {
            let mut config = serde_json::json!({
                "type": "gcs",
                "project_number": project_id,
            });
            if let Some(sa) = service_account_json {
                config["service_account_credentials"] = serde_json::json!(sa);
            }
            Ok(config)
        }
        StorageBackend::Smb {
            host,
            share: _,
            user,
            password,
            domain,
        } => {
            let mut config = serde_json::json!({
                "type": "smb",
                "host": host,
            });
            if let Some(user) = user {
                config["user"] = serde_json::json!(user);
            }
            if let Some(pass) = password {
                config["pass"] = serde_json::json!(pass);
            }
            if let Some(domain) = domain {
                config["domain"] = serde_json::json!(domain);
            }
            Ok(config)
        }
    }
}

/// Get SSH spec for a host and build SFTP config
async fn get_sftp_config_for_host(host_id: &str) -> Result<(serde_json::Value, SshSpec), AppError> {
    let host_info = host::get_host(host_id).await?;
    let ssh = host_info.ssh.ok_or_else(|| {
        AppError::invalid_input(format!("Host {} has no SSH configuration", host_id))
    })?;
    let config = build_sftp_config(&ssh);
    Ok((config, ssh))
}

/// Create a temporary rclone remote and return its name
fn create_temp_remote(name_prefix: &str, config: &serde_json::Value) -> Result<String, AppError> {
    let remote_name = format!(
        "{}_{}",
        name_prefix,
        uuid::Uuid::new_v4().to_string().replace("-", "")[..8].to_string()
    );

    let remote_type = config
        .get("type")
        .and_then(|v| v.as_str())
        .unwrap_or("local");

    // For Google Drive, use two-step process to avoid OAuth trigger
    if remote_type == "drive" {
        // Step 1: Create empty drive remote with nonInteractive
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

        librclone::rpc("config/create", &create_params.to_string())
            .map_err(|e| AppError::command(format!("Failed to create drive remote: {}", e)))?;

        // Step 2: Set parameters one by one using config/update
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
        if let Some(root_folder_id) = config.get("root_folder_id").and_then(|v| v.as_str()) {
            let _ = librclone::rpc(
                "config/update",
                &serde_json::json!({
                    "name": remote_name,
                    "parameters": { "root_folder_id": root_folder_id },
                    "opt": { "nonInteractive": true }
                })
                .to_string(),
            );
        }
        // Always set scope
        let _ = librclone::rpc(
            "config/update",
            &serde_json::json!({
                "name": remote_name,
                "parameters": { "scope": "drive" },
                "opt": { "nonInteractive": true }
            })
            .to_string(),
        );

        return Ok(remote_name);
    }

    // For other storage types, use standard create with nonInteractive
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

/// Delete a temporary rclone remote
fn delete_temp_remote(remote_name: &str) {
    let delete_params = serde_json::json!({ "name": remote_name });
    let _ = librclone::rpc("config/delete", &delete_params.to_string());
}

// ============================================================
// File Operations via rclone
// ============================================================

/// List files in a storage at given path
pub async fn list_files(storage: &Storage, path: &str) -> Result<Vec<FileEntry>, AppError> {
    match &storage.backend {
        StorageBackend::Local { root_path } => list_local_files(root_path, path).await,
        StorageBackend::SshRemote { host_id, root_path } => {
            list_ssh_files(host_id, root_path, path).await
        }
        _ => {
            // Use rclone for cloud backends
            list_rclone_files(storage, path).await
        }
    }
}

/// List files on SSH remote using rclone SFTP
async fn list_ssh_files(
    host_id: &str,
    root_path: &str,
    sub_path: &str,
) -> Result<Vec<FileEntry>, AppError> {
    let (config, _ssh) = get_sftp_config_for_host(host_id).await?;
    let remote_name = create_temp_remote("sftp", &config)?;

    // Build full path
    let full_path = if sub_path.is_empty() || sub_path == "/" {
        root_path.to_string()
    } else {
        format!(
            "{}/{}",
            root_path.trim_end_matches('/'),
            sub_path.trim_start_matches('/')
        )
    };

    let list_opts = serde_json::json!({
        "fs": format!("{}:{}", remote_name, full_path),
        "remote": "",
        "opt": {
            "recurse": false,
        }
    });

    let result = librclone::rpc("operations/list", &list_opts.to_string());
    delete_temp_remote(&remote_name);

    match result {
        Ok(output) => {
            let parsed: serde_json::Value = serde_json::from_str(&output)
                .map_err(|e| AppError::command(format!("Failed to parse list output: {}", e)))?;

            let mut entries = Vec::new();
            if let Some(list) = parsed.get("list").and_then(|l| l.as_array()) {
                for item in list {
                    let name = item
                        .get("Name")
                        .and_then(|n| n.as_str())
                        .unwrap_or("")
                        .to_string();
                    let item_path = item
                        .get("Path")
                        .and_then(|p| p.as_str())
                        .unwrap_or(&name)
                        .to_string();
                    let is_dir = item.get("IsDir").and_then(|d| d.as_bool()).unwrap_or(false);
                    let size = item.get("Size").and_then(|s| s.as_u64()).unwrap_or(0);
                    let modified_at = item
                        .get("ModTime")
                        .and_then(|m| m.as_str())
                        .map(|s| s.to_string());

                    // Skip hidden files
                    if name.starts_with('.') {
                        continue;
                    }

                    entries.push(FileEntry {
                        name,
                        path: if sub_path.is_empty() || sub_path == "/" {
                            format!("/{}", item_path)
                        } else {
                            format!("{}/{}", sub_path.trim_end_matches('/'), item_path)
                        },
                        is_dir,
                        size,
                        modified_at,
                        mime_type: None,
                    });
                }
            }

            // Sort: directories first, then alphabetically
            entries.sort_by(|a, b| match (a.is_dir, b.is_dir) {
                (true, false) => std::cmp::Ordering::Less,
                (false, true) => std::cmp::Ordering::Greater,
                _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
            });

            Ok(entries)
        }
        Err(e) => Err(AppError::command(format!(
            "Failed to list SSH files: {}",
            e
        ))),
    }
}

async fn list_local_files(root_path: &str, sub_path: &str) -> Result<Vec<FileEntry>, AppError> {
    let full_path = if sub_path.is_empty() || sub_path == "/" {
        PathBuf::from(root_path)
    } else {
        PathBuf::from(root_path).join(sub_path.trim_start_matches('/'))
    };

    let mut entries = Vec::new();
    let mut dir = tokio::fs::read_dir(&full_path).await.map_err(|e| {
        AppError::command(format!("Failed to read directory {:?}: {}", full_path, e))
    })?;

    while let Some(entry) = dir.next_entry().await? {
        let metadata = entry.metadata().await?;
        let name = entry.file_name().to_string_lossy().to_string();

        // Skip hidden files
        if name.starts_with('.') {
            continue;
        }

        let path = if sub_path.is_empty() || sub_path == "/" {
            format!("/{}", name)
        } else {
            format!("{}/{}", sub_path.trim_end_matches('/'), name)
        };

        let modified_at = metadata
            .modified()
            .ok()
            .map(|t| chrono::DateTime::<chrono::Utc>::from(t).to_rfc3339());

        entries.push(FileEntry {
            name,
            path,
            is_dir: metadata.is_dir(),
            size: metadata.len(),
            modified_at,
            mime_type: None,
        });
    }

    // Sort: directories first, then alphabetically
    entries.sort_by(|a, b| match (a.is_dir, b.is_dir) {
        (true, false) => std::cmp::Ordering::Less,
        (false, true) => std::cmp::Ordering::Greater,
        _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
    });

    Ok(entries)
}

async fn list_rclone_files(storage: &Storage, path: &str) -> Result<Vec<FileEntry>, AppError> {
    let config = build_rclone_config(&storage.backend)?;
    let remote_name = create_temp_remote("storage", &config)?;

    let remote_path = match &storage.backend {
        StorageBackend::CloudflareR2 { bucket, .. } => format!(
            "{}:{}/{}",
            remote_name,
            bucket,
            path.trim_start_matches('/')
        ),
        StorageBackend::GoogleCloudStorage { bucket, .. } => format!(
            "{}:{}/{}",
            remote_name,
            bucket,
            path.trim_start_matches('/')
        ),
        StorageBackend::Smb { share, .. } => {
            if share.is_empty() {
                // No share specified, list at root (shows available shares)
                format!("{}:{}", remote_name, path.trim_start_matches('/'))
            } else {
                // Share specified, prepend to path
                format!("{}:{}/{}", remote_name, share, path.trim_start_matches('/'))
            }
        }
        _ => format!("{}:{}", remote_name, path.trim_start_matches('/')),
    };

    let list_opts = serde_json::json!({
        "fs": remote_path,
        "remote": "",
        "opt": {
            "recurse": false,
        }
    });

    let result = librclone::rpc("operations/list", &list_opts.to_string());
    delete_temp_remote(&remote_name);

    match result {
        Ok(output) => {
            let parsed: serde_json::Value = serde_json::from_str(&output)
                .map_err(|e| AppError::command(format!("Failed to parse list output: {}", e)))?;

            let mut entries = Vec::new();
            if let Some(list) = parsed.get("list").and_then(|l| l.as_array()) {
                for item in list {
                    let name = item
                        .get("Name")
                        .and_then(|n| n.as_str())
                        .unwrap_or("")
                        .to_string();
                    let item_path = item
                        .get("Path")
                        .and_then(|p| p.as_str())
                        .unwrap_or("")
                        .to_string();
                    let is_dir = item.get("IsDir").and_then(|d| d.as_bool()).unwrap_or(false);
                    let size = item.get("Size").and_then(|s| s.as_u64()).unwrap_or(0);
                    let modified_at = item
                        .get("ModTime")
                        .and_then(|m| m.as_str())
                        .map(|s| s.to_string());

                    entries.push(FileEntry {
                        name,
                        path: if path.is_empty() || path == "/" {
                            format!("/{}", item_path)
                        } else {
                            format!("{}/{}", path.trim_end_matches('/'), item_path)
                        },
                        is_dir,
                        size,
                        modified_at,
                        mime_type: None,
                    });
                }
            }

            // Sort: directories first, then alphabetically
            entries.sort_by(|a, b| match (a.is_dir, b.is_dir) {
                (true, false) => std::cmp::Ordering::Less,
                (false, true) => std::cmp::Ordering::Greater,
                _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
            });

            Ok(entries)
        }
        Err(e) => Err(AppError::command(format!("Failed to list files: {}", e))),
    }
}

/// Test storage connection
pub async fn test_storage(storage: &Storage) -> StorageTestResult {
    let start = std::time::Instant::now();

    match &storage.backend {
        StorageBackend::Local { root_path } => {
            let path = PathBuf::from(root_path);
            if path.exists() && path.is_dir() {
                StorageTestResult {
                    success: true,
                    message: "Local path is accessible".to_string(),
                    latency_ms: Some(start.elapsed().as_millis() as u64),
                }
            } else {
                StorageTestResult {
                    success: false,
                    message: format!("Path does not exist or is not a directory: {}", root_path),
                    latency_ms: None,
                }
            }
        }
        _ => {
            // For other backends, try to list root
            match list_files(storage, "/").await {
                Ok(_) => StorageTestResult {
                    success: true,
                    message: "Connection successful".to_string(),
                    latency_ms: Some(start.elapsed().as_millis() as u64),
                },
                Err(e) => StorageTestResult {
                    success: false,
                    message: format!("Connection failed: {}", e),
                    latency_ms: None,
                },
            }
        }
    }
}

// ============================================================
// Standalone Storage Access (for use without AppHandle)
// ============================================================

/// Get a storage by ID directly from the data file.
/// This is useful for skill execution where AppHandle is not available.
pub async fn get_storage(storage_id: &str) -> Result<Storage, AppError> {
    let data_path = crate::config::doppio_data_dir().join("storages.json");
    let content = tokio::fs::read_to_string(&data_path)
        .await
        .map_err(|e| AppError::io(format!("Failed to read storages file: {}", e)))?;
    let storages: HashMap<String, Storage> = serde_json::from_str(&content)
        .map_err(|e| AppError::invalid_input(format!("Failed to parse storages: {}", e)))?;
    storages
        .get(storage_id)
        .cloned()
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))
}

// ============================================================
// Tauri Commands
// ============================================================

#[tauri::command]
pub async fn storage_list(app: AppHandle) -> Result<Vec<Storage>, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    Ok(store.list().await)
}

#[tauri::command]
pub async fn storage_get(app: AppHandle, id: String) -> Result<Storage, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    store
        .get(&id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", id)))
}

#[tauri::command]
pub async fn storage_create(
    app: AppHandle,
    config: StorageCreateInput,
) -> Result<Storage, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    store.create(config).await
}

#[tauri::command]
pub async fn storage_update(
    app: AppHandle,
    id: String,
    config: StorageUpdateInput,
) -> Result<Storage, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    store.update(&id, config).await
}

#[tauri::command]
pub async fn storage_delete(app: AppHandle, id: String) -> Result<(), AppError> {
    let store = app.state::<Arc<StorageStore>>();
    store.delete(&id).await
}

/// Purge all objects in a Cloudflare R2 bucket, then delete the bucket via Cloudflare API.
/// Optionally deletes the local storage configuration after successful bucket deletion.
#[tauri::command]
pub async fn storage_r2_purge_and_delete_bucket(
    app: AppHandle,
    storage_id: String,
    cloudflare_api_token: Option<String>,
    delete_local_storage: bool,
) -> Result<R2PurgeDeleteResult, AppError> {
    validate_non_empty("storage_id", &storage_id)?;

    let store = app.state::<Arc<StorageStore>>();
    let storage = store
        .get(&storage_id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))?;

    if storage.readonly {
        return Err(AppError::permission_denied(
            "Storage is read-only; refusing to delete bucket",
        ));
    }

    let (account_id, access_key_id, secret_access_key, bucket, endpoint) = match &storage.backend {
        StorageBackend::CloudflareR2 {
            account_id,
            access_key_id,
            secret_access_key,
            bucket,
            endpoint,
        } => (
            account_id.clone(),
            access_key_id.clone(),
            secret_access_key.clone(),
            bucket.clone(),
            endpoint.clone(),
        ),
        _ => {
            return Err(AppError::invalid_input(
                "storage_id is not a Cloudflare R2 storage",
            ))
        }
    };

    validate_cloudflare_account_id(&account_id)?;
    validate_r2_bucket_name(&bucket)?;

    eprintln!(
        "R2 purge+delete started: storage_id={}, bucket={}",
        storage_id, bucket
    );

    let provided_token = cloudflare_api_token
        .as_deref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .map(|s| s.to_string());

    let token_to_use = if let Some(tok) = provided_token.clone() {
        tok
    } else {
        crate::secrets::get_secret("cloudflare/api_token").map_err(|_| {
            AppError::invalid_input(
                "Cloudflare API token not set. Provide one now, or save a secret named cloudflare/api_token.",
            )
        })?
    };

    // Validate token and bucket existence before doing any destructive purge.
    let bucket_exists = cloudflare_r2_bucket_exists(&account_id, &bucket, &token_to_use).await?;
    if !bucket_exists {
        let mut local_storage_deleted = false;
        if delete_local_storage {
            store.delete(&storage_id).await?;
            local_storage_deleted = true;
        }
        return Ok(R2PurgeDeleteResult {
            deleted_objects: 0,
            bucket_deleted: true,
            local_storage_deleted,
        });
    }

    let s3_client = build_r2_s3_client(
        &account_id,
        &access_key_id,
        &secret_access_key,
        endpoint.as_deref(),
    )
    .await?;

    let deleted_objects = r2_delete_all_objects(&s3_client, &bucket).await?;
    eprintln!(
        "R2 purge finished: storage_id={}, bucket={}, deleted_objects={}",
        storage_id, bucket, deleted_objects
    );

    cloudflare_r2_delete_bucket(&account_id, &bucket, &token_to_use).await?;
    eprintln!(
        "R2 bucket deleted via Cloudflare API: storage_id={}, bucket={}",
        storage_id, bucket
    );

    if let Some(tok) = provided_token {
        let input = crate::secrets::SecretInput {
            name: "cloudflare/api_token".to_string(),
            value: tok,
            description: Some("Cloudflare API token (R2)".to_string()),
        };
        let _ = tokio::task::spawn_blocking(move || crate::secrets::upsert_secret(&input)).await;
    }

    let mut local_storage_deleted = false;
    if delete_local_storage {
        store.delete(&storage_id).await?;
        local_storage_deleted = true;
    }

    Ok(R2PurgeDeleteResult {
        deleted_objects,
        bucket_deleted: true,
        local_storage_deleted,
    })
}

#[tauri::command]
pub async fn storage_test(app: AppHandle, id: String) -> Result<StorageTestResult, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    let mut storage = store
        .get(&id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", id)))?;

    // For Google Drive, refresh token before use
    if let StorageBackend::GoogleDrive {
        client_id,
        client_secret,
        token,
        root_folder_id,
    } = &storage.backend
    {
        if let (Some(cid), Some(csec), Some(tok)) =
            (client_id.as_ref(), client_secret.as_ref(), token.as_ref())
        {
            eprintln!("Google Drive: refreshing token before test...");
            match crate::google_drive::refresh_token(cid, csec, tok).await {
                Ok(new_token) => {
                    let update = StorageUpdateInput {
                        name: None,
                        icon: None,
                        readonly: None,
                        backend: Some(StorageBackend::GoogleDrive {
                            client_id: Some(cid.clone()),
                            client_secret: Some(csec.clone()),
                            token: Some(new_token),
                            root_folder_id: root_folder_id.clone(),
                        }),
                    };
                    if let Ok(updated) = store.update(&id, update).await {
                        storage = updated;
                        eprintln!("Google Drive token refreshed successfully");
                    }
                }
                Err(e) => {
                    return Ok(StorageTestResult {
                        success: false,
                        message: format!(
                            "Token refresh failed: {}. Please re-authorize in Storage settings.",
                            e
                        ),
                        latency_ms: None,
                    });
                }
            }
        } else {
            return Ok(StorageTestResult {
                success: false,
                message: "Google Drive not properly configured. Please set up OAuth.".to_string(),
                latency_ms: None,
            });
        }
    }

    Ok(test_storage(&storage).await)
}

#[tauri::command]
pub async fn storage_list_files(
    app: AppHandle,
    storage_id: String,
    path: String,
) -> Result<Vec<FileEntry>, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    let mut storage = store
        .get(&storage_id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))?;

    // For Google Drive OAuth mode, refresh token if expired
    if let StorageBackend::GoogleDrive {
        client_id,
        client_secret,
        token,
        root_folder_id,
    } = &storage.backend
    {
        if let (Some(cid), Some(csec), Some(tok)) =
            (client_id.as_ref(), client_secret.as_ref(), token.as_ref())
        {
            if crate::google_drive::is_token_expired(tok) {
                eprintln!("Google Drive token expired, refreshing...");
                match crate::google_drive::refresh_token(cid, csec, tok).await {
                    Ok(new_token) => {
                        let update = StorageUpdateInput {
                            name: None,
                            icon: None,
                            readonly: None,
                            backend: Some(StorageBackend::GoogleDrive {
                                client_id: Some(cid.clone()),
                                client_secret: Some(csec.clone()),
                                token: Some(new_token),
                                root_folder_id: root_folder_id.clone(),
                            }),
                        };
                        if let Ok(updated) = store.update(&storage_id, update).await {
                            storage = updated;
                            eprintln!("Google Drive token refreshed successfully");
                        }
                    }
                    Err(e) => {
                        return Err(AppError::command(format!(
                            "Google Drive token refresh failed: {}. Please delete and re-add the storage.", e
                        )));
                    }
                }
            }
        } else {
            return Err(AppError::command(
                "Google Drive not properly configured. Please set up OAuth.".to_string(),
            ));
        }
    }

    // Update last accessed
    let _ = store.update_last_accessed(&storage_id).await;

    list_files(&storage, &path).await
}

#[tauri::command]
pub async fn storage_mkdir(
    app: AppHandle,
    storage_id: String,
    path: String,
) -> Result<(), AppError> {
    let store = app.state::<Arc<StorageStore>>();
    let storage = store
        .get(&storage_id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))?;

    if storage.readonly {
        return Err(AppError::permission_denied("Storage is read-only"));
    }

    match &storage.backend {
        StorageBackend::Local { root_path } => {
            let full_path = PathBuf::from(root_path).join(path.trim_start_matches('/'));
            tokio::fs::create_dir_all(&full_path).await?;
            Ok(())
        }
        StorageBackend::SshRemote { host_id, root_path } => {
            let (config, _) = get_sftp_config_for_host(host_id).await?;
            let remote_name = create_temp_remote("sftp", &config)?;

            let full_path = format!(
                "{}/{}",
                root_path.trim_end_matches('/'),
                path.trim_start_matches('/')
            );
            let mkdir_opts = serde_json::json!({
                "fs": format!("{}:{}", remote_name, full_path),
                "remote": "",
            });

            let result = librclone::rpc("operations/mkdir", &mkdir_opts.to_string());
            delete_temp_remote(&remote_name);

            result.map_err(|e| AppError::command(format!("Failed to create directory: {}", e)))?;
            Ok(())
        }
        StorageBackend::Smb { share, .. } => {
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("storage", &config)?;

            let full_path = if share.is_empty() {
                path.trim_start_matches('/').to_string()
            } else {
                format!("{}/{}", share, path.trim_start_matches('/'))
            };

            let mkdir_opts = serde_json::json!({
                "fs": format!("{}:{}", remote_name, full_path),
                "remote": "",
            });

            let result = librclone::rpc("operations/mkdir", &mkdir_opts.to_string());
            delete_temp_remote(&remote_name);

            result.map_err(|e| AppError::command(format!("Failed to create directory: {}", e)))?;
            Ok(())
        }
        _ => {
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("storage", &config)?;

            let mkdir_opts = serde_json::json!({
                "fs": format!("{}:", remote_name),
                "remote": path.trim_start_matches('/'),
            });

            let result = librclone::rpc("operations/mkdir", &mkdir_opts.to_string());
            delete_temp_remote(&remote_name);

            result.map_err(|e| AppError::command(format!("Failed to create directory: {}", e)))?;
            Ok(())
        }
    }
}

#[tauri::command]
pub async fn storage_delete_file(
    app: AppHandle,
    storage_id: String,
    path: String,
) -> Result<(), AppError> {
    let store = app.state::<Arc<StorageStore>>();
    let storage = store
        .get(&storage_id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))?;

    if storage.readonly {
        return Err(AppError::permission_denied("Storage is read-only"));
    }

    match &storage.backend {
        StorageBackend::Local { root_path } => {
            let full_path = PathBuf::from(root_path).join(path.trim_start_matches('/'));
            if full_path.is_dir() {
                tokio::fs::remove_dir_all(&full_path).await?;
            } else {
                tokio::fs::remove_file(&full_path).await?;
            }
            Ok(())
        }
        StorageBackend::SshRemote { host_id, root_path } => {
            let (config, _) = get_sftp_config_for_host(host_id).await?;
            let remote_name = create_temp_remote("sftp", &config)?;

            let full_path = format!(
                "{}/{}",
                root_path.trim_end_matches('/'),
                path.trim_start_matches('/')
            );
            let delete_opts = serde_json::json!({
                "fs": format!("{}:{}", remote_name, full_path),
                "remote": "",
            });

            // Try deletefile first, then purge for directories
            let result = librclone::rpc("operations/deletefile", &delete_opts.to_string());
            if result.is_err() {
                let _ = librclone::rpc("operations/purge", &delete_opts.to_string());
            }

            delete_temp_remote(&remote_name);
            Ok(())
        }
        StorageBackend::Smb { share, .. } => {
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("storage", &config)?;

            let full_path = if share.is_empty() {
                path.trim_start_matches('/').to_string()
            } else {
                format!("{}/{}", share, path.trim_start_matches('/'))
            };

            let delete_opts = serde_json::json!({
                "fs": format!("{}:{}", remote_name, full_path),
                "remote": "",
            });

            // Try deletefile first, then purge for directories
            let result = librclone::rpc("operations/deletefile", &delete_opts.to_string());
            if result.is_err() {
                let _ = librclone::rpc("operations/purge", &delete_opts.to_string());
            }

            delete_temp_remote(&remote_name);
            Ok(())
        }
        _ => {
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("storage", &config)?;

            let delete_opts = serde_json::json!({
                "fs": format!("{}:", remote_name),
                "remote": path.trim_start_matches('/'),
            });

            // Try deletefile first, then purge for directories
            let result = librclone::rpc("operations/deletefile", &delete_opts.to_string());
            if result.is_err() {
                let _ = librclone::rpc("operations/purge", &delete_opts.to_string());
            }

            delete_temp_remote(&remote_name);
            Ok(())
        }
    }
}

// ============================================================
// Storage Usage (for R2 cost calculation)
// ============================================================

/// Storage usage information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageUsage {
    pub storage_id: String,
    pub storage_name: String,
    pub backend_type: String,
    pub bucket_name: Option<String>,
    /// Total bytes on disk (for filesystems like SMB/SSH)
    pub total_bytes: Option<u64>,
    /// Total bytes on disk in GB
    pub total_gb: Option<f64>,
    /// Total bytes used
    pub used_bytes: u64,
    /// Total bytes used in GB
    pub used_gb: f64,
    /// Free bytes (for filesystems)
    pub free_bytes: Option<u64>,
    /// Free bytes in GB
    pub free_gb: Option<f64>,
    /// Object count (if available)
    pub object_count: Option<u64>,
    /// When this was last fetched
    pub fetched_at: String,
}

/// Get usage for a specific storage (works for R2 and other cloud backends)
#[tauri::command]
pub async fn storage_get_usage(
    app: AppHandle,
    storage_id: String,
) -> Result<StorageUsage, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    let storage = store
        .get(&storage_id)
        .await
        .ok_or_else(|| AppError::not_found(format!("Storage not found: {}", storage_id)))?;

    let bucket_name = match &storage.backend {
        StorageBackend::CloudflareR2 { bucket, .. } => Some(bucket.clone()),
        StorageBackend::GoogleCloudStorage { bucket, .. } => Some(bucket.clone()),
        _ => None,
    };

    // For cloud backends, use rclone to get size
    match &storage.backend {
        StorageBackend::GoogleDrive { .. } => {
            // Google Drive supports operations/about for quota info
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("gdrive_usage", &config)?;

            let about_opts = serde_json::json!({
                "fs": format!("{}:", remote_name),
            });

            let result = librclone::rpc("operations/about", &about_opts.to_string());
            delete_temp_remote(&remote_name);

            match result {
                Ok(result_str) => {
                    // Parse result: {"total": N, "used": N, "free": N, "trashed": N}
                    let parsed: serde_json::Value = serde_json::from_str(&result_str)?;
                    let total = parsed.get("total").and_then(|v| v.as_u64());
                    let used = parsed.get("used").and_then(|v| v.as_u64()).unwrap_or(0);
                    let free = parsed.get("free").and_then(|v| v.as_u64());

                    Ok(StorageUsage {
                        storage_id: storage.id,
                        storage_name: storage.name,
                        backend_type: storage.backend.type_name().to_string(),
                        bucket_name: None,
                        total_bytes: total,
                        total_gb: total.map(|t| t as f64 / (1024.0 * 1024.0 * 1024.0)),
                        used_bytes: used,
                        used_gb: used as f64 / (1024.0 * 1024.0 * 1024.0),
                        free_bytes: free,
                        free_gb: free.map(|f| f as f64 / (1024.0 * 1024.0 * 1024.0)),
                        object_count: None,
                        fetched_at: chrono::Utc::now().to_rfc3339(),
                    })
                }
                Err(e) => {
                    eprintln!("Failed to get Google Drive quota: {}", e);
                    Ok(StorageUsage {
                        storage_id: storage.id,
                        storage_name: storage.name,
                        backend_type: storage.backend.type_name().to_string(),
                        bucket_name: None,
                        total_bytes: None,
                        total_gb: None,
                        used_bytes: 0,
                        used_gb: 0.0,
                        free_bytes: None,
                        free_gb: None,
                        object_count: None,
                        fetched_at: chrono::Utc::now().to_rfc3339(),
                    })
                }
            }
        }
        StorageBackend::CloudflareR2 { .. } | StorageBackend::GoogleCloudStorage { .. } => {
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("usage", &config)?;

            // Get bucket path
            let bucket_path = match &storage.backend {
                StorageBackend::CloudflareR2 { bucket, .. } => bucket.clone(),
                StorageBackend::GoogleCloudStorage { bucket, .. } => bucket.clone(),
                _ => String::new(),
            };

            // Use operations/size to get accurate count
            let size_opts = serde_json::json!({
                "fs": format!("{}:{}", remote_name, bucket_path),
            });

            let result = librclone::rpc("operations/size", &size_opts.to_string());
            delete_temp_remote(&remote_name);

            let result_str = result
                .map_err(|e| AppError::command(format!("Failed to get storage size: {}", e)))?;

            // Parse result: {"count": N, "bytes": N}
            let parsed: serde_json::Value = serde_json::from_str(&result_str)?;
            let bytes = parsed.get("bytes").and_then(|v| v.as_u64()).unwrap_or(0);
            let count = parsed.get("count").and_then(|v| v.as_u64());

            Ok(StorageUsage {
                storage_id: storage.id,
                storage_name: storage.name,
                backend_type: storage.backend.type_name().to_string(),
                bucket_name,
                total_bytes: None,
                total_gb: None,
                used_bytes: bytes,
                used_gb: bytes as f64 / (1024.0 * 1024.0 * 1024.0),
                free_bytes: None,
                free_gb: None,
                object_count: count,
                fetched_at: chrono::Utc::now().to_rfc3339(),
            })
        }
        StorageBackend::Local { root_path: _ } => {
            // For local, we could calculate dir size but skip for now
            Ok(StorageUsage {
                storage_id: storage.id,
                storage_name: storage.name,
                backend_type: "Local".to_string(),
                bucket_name: None,
                total_bytes: None,
                total_gb: None,
                used_bytes: 0,
                used_gb: 0.0,
                free_bytes: None,
                free_gb: None,
                object_count: None,
                fetched_at: chrono::Utc::now().to_rfc3339(),
            })
        }
        StorageBackend::SshRemote { host_id, root_path } => {
            // Use operations/about to get disk space info for SSH remotes
            let (config, _ssh) = get_sftp_config_for_host(host_id).await?;
            let remote_name = create_temp_remote("sftp_usage", &config)?;

            let about_opts = serde_json::json!({
                "fs": format!("{}:{}", remote_name, root_path),
            });

            let result = librclone::rpc("operations/about", &about_opts.to_string());
            delete_temp_remote(&remote_name);

            match result {
                Ok(result_str) => {
                    // Parse result: {"total": N, "used": N, "free": N, "objects": N}
                    let parsed: serde_json::Value = serde_json::from_str(&result_str)?;
                    let total = parsed.get("total").and_then(|v| v.as_u64());
                    let used = parsed.get("used").and_then(|v| v.as_u64()).unwrap_or(0);
                    let free = parsed.get("free").and_then(|v| v.as_u64());

                    Ok(StorageUsage {
                        storage_id: storage.id,
                        storage_name: storage.name,
                        backend_type: storage.backend.type_name().to_string(),
                        bucket_name: None,
                        total_bytes: total,
                        total_gb: total.map(|t| t as f64 / (1024.0 * 1024.0 * 1024.0)),
                        used_bytes: used,
                        used_gb: used as f64 / (1024.0 * 1024.0 * 1024.0),
                        free_bytes: free,
                        free_gb: free.map(|f| f as f64 / (1024.0 * 1024.0 * 1024.0)),
                        object_count: None,
                        fetched_at: chrono::Utc::now().to_rfc3339(),
                    })
                }
                Err(e) => {
                    // Return empty usage if about fails
                    eprintln!("Failed to get SSH disk usage: {}", e);
                    Ok(StorageUsage {
                        storage_id: storage.id,
                        storage_name: storage.name,
                        backend_type: storage.backend.type_name().to_string(),
                        bucket_name: None,
                        total_bytes: None,
                        total_gb: None,
                        used_bytes: 0,
                        used_gb: 0.0,
                        free_bytes: None,
                        free_gb: None,
                        object_count: None,
                        fetched_at: chrono::Utc::now().to_rfc3339(),
                    })
                }
            }
        }
        StorageBackend::Smb { share, .. } => {
            // Use operations/about to get disk space info for SMB
            let config = build_rclone_config(&storage.backend)?;
            let remote_name = create_temp_remote("smb_usage", &config)?;

            // For SMB, we need to specify the share name as the path
            // Format: remote:share/ to get disk usage of that share
            let smb_path = if share.is_empty() {
                // No share - can't get disk usage without a share
                delete_temp_remote(&remote_name);
                return Ok(StorageUsage {
                    storage_id: storage.id,
                    storage_name: storage.name,
                    backend_type: storage.backend.type_name().to_string(),
                    bucket_name: None,
                    total_bytes: None,
                    total_gb: None,
                    used_bytes: 0,
                    used_gb: 0.0,
                    free_bytes: None,
                    free_gb: None,
                    object_count: None,
                    fetched_at: chrono::Utc::now().to_rfc3339(),
                });
            } else {
                // Use share/ as the path (trailing slash is important)
                format!("{}:{}/", remote_name, share)
            };

            let about_opts = serde_json::json!({
                "fs": smb_path,
            });

            eprintln!("SMB about request: fs={}", smb_path);
            let result = librclone::rpc("operations/about", &about_opts.to_string());
            delete_temp_remote(&remote_name);

            match result {
                Ok(result_str) => {
                    eprintln!("SMB about response: {}", result_str);
                    // Parse result: {"total": N, "used": N, "free": N}
                    let parsed: serde_json::Value = serde_json::from_str(&result_str)?;
                    let total = parsed.get("total").and_then(|v| v.as_u64());
                    let used = parsed.get("used").and_then(|v| v.as_u64()).unwrap_or(0);
                    let free = parsed.get("free").and_then(|v| v.as_u64());

                    Ok(StorageUsage {
                        storage_id: storage.id,
                        storage_name: storage.name,
                        backend_type: storage.backend.type_name().to_string(),
                        bucket_name: None,
                        total_bytes: total,
                        total_gb: total.map(|t| t as f64 / (1024.0 * 1024.0 * 1024.0)),
                        used_bytes: used,
                        used_gb: used as f64 / (1024.0 * 1024.0 * 1024.0),
                        free_bytes: free,
                        free_gb: free.map(|f| f as f64 / (1024.0 * 1024.0 * 1024.0)),
                        object_count: None,
                        fetched_at: chrono::Utc::now().to_rfc3339(),
                    })
                }
                Err(e) => {
                    // Return empty usage if about fails
                    eprintln!("Failed to get SMB disk usage: {}", e);
                    Ok(StorageUsage {
                        storage_id: storage.id,
                        storage_name: storage.name,
                        backend_type: storage.backend.type_name().to_string(),
                        bucket_name: None,
                        total_bytes: None,
                        total_gb: None,
                        used_bytes: 0,
                        used_gb: 0.0,
                        free_bytes: None,
                        free_gb: None,
                        object_count: None,
                        fetched_at: chrono::Utc::now().to_rfc3339(),
                    })
                }
            }
        }
    }
}

/// Get usage for all R2 storages
#[tauri::command]
pub async fn storage_get_r2_usages(app: AppHandle) -> Result<Vec<StorageUsage>, AppError> {
    let store = app.state::<Arc<StorageStore>>();
    let storages = store.list().await;

    let mut usages = Vec::new();
    for storage in storages {
        if matches!(storage.backend, StorageBackend::CloudflareR2 { .. }) {
            match storage_get_usage(app.clone(), storage.id.clone()).await {
                Ok(usage) => usages.push(usage),
                Err(e) => {
                    // Log error but continue with other storages
                    eprintln!("Failed to get usage for {}: {}", storage.name, e);
                }
            }
        }
    }

    Ok(usages)
}
