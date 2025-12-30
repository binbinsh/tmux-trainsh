use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::AppError;

/// Get the unified Doppio data directory
///
/// All data is stored in one location:
/// - macOS: ~/Library/Application Support/doppio/
/// - Linux: ~/.local/share/doppio/
/// - Windows: %APPDATA%\doppio\
///
/// Can be overridden with DOPPIO_DATA_DIR environment variable.
pub fn doppio_data_dir() -> PathBuf {
    // Allow override via environment variable
    if let Ok(env) = std::env::var("DOPPIO_DATA_DIR") {
        if !env.trim().is_empty() {
            return PathBuf::from(env);
        }
    }

    // Use platform-specific data directory
    dirs::data_dir()
        .unwrap_or_else(|| {
            dirs::home_dir()
                .unwrap_or_else(|| PathBuf::from("."))
                .join(".local")
                .join("share")
        })
        .join("doppio")
}

/// Legacy XDG data home (for migration)
pub fn xdg_data_home() -> PathBuf {
    if let Ok(env) = std::env::var("XDG_DATA_HOME") {
        if !env.trim().is_empty() {
            return PathBuf::from(env);
        }
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".local")
        .join("share")
}

pub fn default_config_path() -> PathBuf {
    doppio_data_dir().join("config.json")
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum VastSshConnectionPreference {
    Proxy,
    Direct,
}

impl Default for VastSshConnectionPreference {
    fn default() -> Self {
        Self::Proxy
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct VastConfig {
    pub api_key: Option<String>,
    pub url: String,
    pub ssh_user: String,
    pub ssh_key_path: Option<String>,
    pub ssh_connection_preference: VastSshConnectionPreference,
}

impl Default for VastConfig {
    fn default() -> Self {
        Self {
            api_key: None,
            url: "https://cloud.vast.ai/".to_string(),
            ssh_user: "root".to_string(),
            ssh_key_path: None,
            ssh_connection_preference: VastSshConnectionPreference::Proxy,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ColabConfig {
    pub mount_drive: bool,
    pub drive_dir: String,
    pub hf_home: Option<String>,
}

impl Default for ColabConfig {
    fn default() -> Self {
        Self {
            mount_drive: true,
            drive_dir: "MyDrive/doppio".to_string(),
            hf_home: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct ScamalyticsConfig {
    pub api_key: Option<String>,
    pub user: Option<String>,
    pub host: String,
}

impl Default for ScamalyticsConfig {
    fn default() -> Self {
        Self {
            api_key: None,
            user: None,
            host: "https://api11.scamalytics.com/v3/".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct TrainshConfig {
    pub vast: VastConfig,
    pub colab: ColabConfig,
    pub scamalytics: ScamalyticsConfig,
}

impl Default for TrainshConfig {
    fn default() -> Self {
        Self {
            vast: VastConfig::default(),
            colab: ColabConfig::default(),
            scamalytics: ScamalyticsConfig::default(),
        }
    }
}

pub async fn load_config() -> Result<TrainshConfig, AppError> {
    let path = default_config_path();
    if !path.exists() {
        return Ok(TrainshConfig::default());
    }
    let raw = tokio::fs::read_to_string(&path).await?;
    let cfg: TrainshConfig = serde_json::from_str(&raw)
        .map_err(|e| AppError::io(format!("Invalid config JSON at {}: {e}", path.display())))?;
    Ok(cfg)
}

pub async fn save_config(cfg: &TrainshConfig) -> Result<(), AppError> {
    let path = default_config_path();
    if let Some(parent) = path.parent() {
        tokio::fs::create_dir_all(parent).await?;
    }
    let data = serde_json::to_string_pretty(cfg)
        .map_err(|e| AppError::io(format!("Failed to serialize config: {e}")))?;
    tokio::fs::write(&path, format!("{data}\n")).await?;
    Ok(())
}

/// Legacy paths for migration
fn legacy_config_path() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".config")
        .join("doppio")
        .join("config.json")
}

fn legacy_data_dir() -> PathBuf {
    xdg_data_home().join("doppio")
}

/// Migrate data from old locations to new unified location
pub async fn migrate_legacy_data() -> Result<bool, AppError> {
    let new_dir = doppio_data_dir();
    let legacy_cfg = legacy_config_path();
    let legacy_data = legacy_data_dir();

    let mut migrated = false;

    // Migrate config
    if legacy_cfg.exists() && !default_config_path().exists() {
        if let Some(parent) = default_config_path().parent() {
            tokio::fs::create_dir_all(parent).await?;
        }
        tokio::fs::copy(&legacy_cfg, default_config_path()).await?;
        eprintln!(
            "Migrated config from {:?} to {:?}",
            legacy_cfg,
            default_config_path()
        );
        migrated = true;
    }

    // Migrate hosts
    let legacy_hosts = legacy_data.join("hosts");
    let new_hosts = new_dir.join("hosts");
    if legacy_hosts.exists() && !new_hosts.exists() {
        copy_dir_all(&legacy_hosts, &new_hosts).await?;
        eprintln!("Migrated hosts from {:?} to {:?}", legacy_hosts, new_hosts);
        migrated = true;
    }

    // Migrate sessions
    let legacy_sessions = legacy_data.join("sessions");
    let new_sessions = new_dir.join("sessions");
    if legacy_sessions.exists() && !new_sessions.exists() {
        copy_dir_all(&legacy_sessions, &new_sessions).await?;
        eprintln!(
            "Migrated sessions from {:?} to {:?}",
            legacy_sessions, new_sessions
        );
        migrated = true;
    }

    Ok(migrated)
}

/// Recursively copy a directory
async fn copy_dir_all(src: &PathBuf, dst: &PathBuf) -> Result<(), AppError> {
    tokio::fs::create_dir_all(dst).await?;
    let mut entries = tokio::fs::read_dir(src).await?;
    while let Some(entry) = entries.next_entry().await? {
        let ty = entry.file_type().await?;
        let src_path = entry.path();
        let dst_path = dst.join(entry.file_name());
        if ty.is_dir() {
            Box::pin(copy_dir_all(&src_path, &dst_path)).await?;
        } else {
            tokio::fs::copy(&src_path, &dst_path).await?;
        }
    }
    Ok(())
}

/// Get data directory path (for display to user)
pub fn get_data_dir_path() -> String {
    doppio_data_dir().to_string_lossy().to_string()
}
