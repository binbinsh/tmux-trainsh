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

/// Terminal theme options
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum TerminalTheme {
    #[default]
    TokyoNightLight,
    TokyoNightDark,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
pub struct TerminalConfig {
    pub theme: TerminalTheme,
}

impl Default for TerminalConfig {
    fn default() -> Self {
        Self {
            theme: TerminalTheme::TokyoNightLight,
        }
    }
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
    pub terminal: TerminalConfig,
}

impl Default for TrainshConfig {
    fn default() -> Self {
        Self {
            vast: VastConfig::default(),
            colab: ColabConfig::default(),
            scamalytics: ScamalyticsConfig::default(),
            terminal: TerminalConfig::default(),
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

/// Get data directory path (for display to user)
pub fn get_data_dir_path() -> String {
    doppio_data_dir().to_string_lossy().to_string()
}
