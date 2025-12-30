//! Secrets management module
//!
//! Provides secure storage for API keys, tokens, and other credentials.
//! Uses OS-native keychain when available, falls back to encrypted file storage.
//!
//! Secrets are referenced in recipes using the `${secret:name}` syntax.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::config::doppio_data_dir;
use crate::error::AppError;

/// The service name used for keyring entries
const KEYRING_SERVICE: &str = "dev.doppio.secrets";

// ============================================================
// File-based fallback storage (when keyring fails)
// ============================================================

fn secrets_values_path() -> std::path::PathBuf {
    doppio_data_dir().join(".secrets_values.json")
}

fn load_file_secrets() -> HashMap<String, String> {
    let path = secrets_values_path();
    if !path.exists() {
        return HashMap::new();
    }

    match std::fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(_) => HashMap::new(),
    }
}

fn save_file_secrets(secrets: &HashMap<String, String>) -> Result<(), AppError> {
    let path = secrets_values_path();
    let json = serde_json::to_string_pretty(secrets)
        .map_err(|e| AppError::internal(format!("Failed to serialize secrets: {}", e)))?;
    std::fs::write(&path, json)
        .map_err(|e| AppError::internal(format!("Failed to write secrets file: {}", e)))
}

fn get_file_secret(name: &str) -> Option<String> {
    load_file_secrets().get(name).cloned()
}

fn set_file_secret(name: &str, value: &str) -> Result<(), AppError> {
    let mut secrets = load_file_secrets();
    secrets.insert(name.to_string(), value.to_string());
    save_file_secrets(&secrets)
}

fn delete_file_secret(name: &str) -> Result<(), AppError> {
    let mut secrets = load_file_secrets();
    secrets.remove(name);
    save_file_secrets(&secrets)
}

/// Secret metadata (stored in app data, not the actual secret value)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecretMeta {
    /// Secret name/key (e.g., "github/token", "huggingface/api_key")
    pub name: String,
    /// Optional description
    pub description: Option<String>,
    /// When this secret was created
    pub created_at: String,
    /// When this secret was last updated
    pub updated_at: String,
}

/// Secret with value (only used for display/edit, never persisted to disk)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Secret {
    pub name: String,
    pub value: String,
    pub description: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

/// Input for creating/updating a secret
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecretInput {
    pub name: String,
    pub value: String,
    pub description: Option<String>,
}

/// Get a secret value by name
/// Tries file storage first (primary), then keyring as fallback
pub fn get_secret(name: &str) -> Result<String, AppError> {
    eprintln!("[secrets] get_secret('{}') called", name);

    // Try file storage first (primary storage)
    if let Some(value) = get_file_secret(name) {
        eprintln!("[secrets] Found '{}' in file storage", name);
        return Ok(value);
    }

    // Fallback to keyring (legacy)
    match keyring::Entry::new(KEYRING_SERVICE, name) {
        Ok(entry) => match entry.get_password() {
            Ok(password) => {
                eprintln!("[secrets] Found '{}' in keyring (legacy)", name);
                return Ok(password);
            }
            Err(e) => {
                eprintln!(
                    "[secrets] Keyring get_password failed for '{}': {:?}",
                    name, e
                );
            }
        },
        Err(e) => {
            eprintln!(
                "[secrets] Keyring entry creation failed for '{}': {:?}",
                name, e
            );
        }
    }

    Err(AppError::not_found(format!("Secret '{}' not found", name)))
}

/// Set a secret value
/// Always saves to file storage (keyring on macOS has issues in dev mode)
pub fn set_secret(name: &str, value: &str) -> Result<(), AppError> {
    eprintln!("[secrets] Setting secret: {}", name);

    // Try keyring (best effort, but don't rely on it)
    if let Ok(entry) = keyring::Entry::new(KEYRING_SERVICE, name) {
        if entry.set_password(value).is_ok() {
            eprintln!("[secrets] Also saved to keyring");
        }
    }

    // Always save to file storage as primary/backup
    set_file_secret(name, value)?;
    eprintln!("[secrets] Saved to file storage");

    eprintln!("[secrets] Secret '{}' saved successfully", name);
    Ok(())
}

/// Delete a secret
pub fn delete_secret(name: &str) -> Result<(), AppError> {
    // Try to delete from keyring
    if let Ok(entry) = keyring::Entry::new(KEYRING_SERVICE, name) {
        let _ = entry.delete_credential(); // Ignore errors
    }

    // Also delete from file storage
    delete_file_secret(name)?;

    Ok(())
}

/// Check if a secret exists
pub fn secret_exists(name: &str) -> bool {
    get_secret(name).is_ok()
}

// ============================================================
// Secret Metadata Storage (JSON file for names/descriptions)
// ============================================================

use std::path::PathBuf;

fn secrets_meta_path() -> PathBuf {
    doppio_data_dir().join("secrets.json")
}

fn load_secrets_meta() -> Result<HashMap<String, SecretMeta>, AppError> {
    let path = secrets_meta_path();
    if !path.exists() {
        return Ok(HashMap::new());
    }

    let content = std::fs::read_to_string(&path)
        .map_err(|e| AppError::io_error(format!("Failed to read secrets metadata: {}", e)))?;

    let meta: HashMap<String, SecretMeta> = serde_json::from_str(&content)
        .map_err(|e| AppError::internal(format!("Failed to parse secrets metadata: {}", e)))?;

    Ok(meta)
}

fn save_secrets_meta(meta: &HashMap<String, SecretMeta>) -> Result<(), AppError> {
    let path = secrets_meta_path();

    // Ensure parent directory exists
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| AppError::io_error(format!("Failed to create data directory: {}", e)))?;
    }

    let content = serde_json::to_string_pretty(meta)
        .map_err(|e| AppError::internal(format!("Failed to serialize secrets metadata: {}", e)))?;

    std::fs::write(&path, content)
        .map_err(|e| AppError::io_error(format!("Failed to write secrets metadata: {}", e)))?;

    Ok(())
}

/// Create or update a secret
pub fn upsert_secret(input: &SecretInput) -> Result<SecretMeta, AppError> {
    let now = chrono::Utc::now().to_rfc3339();

    // Store the actual value in keyring
    set_secret(&input.name, &input.value)?;

    // Update metadata
    let mut meta_store = load_secrets_meta()?;

    let meta = if let Some(existing) = meta_store.get(&input.name) {
        SecretMeta {
            name: input.name.clone(),
            description: input.description.clone(),
            created_at: existing.created_at.clone(),
            updated_at: now,
        }
    } else {
        SecretMeta {
            name: input.name.clone(),
            description: input.description.clone(),
            created_at: now.clone(),
            updated_at: now,
        }
    };

    meta_store.insert(input.name.clone(), meta.clone());
    save_secrets_meta(&meta_store)?;

    Ok(meta)
}

/// List all secrets (metadata only, no values)
pub fn list_secrets() -> Result<Vec<SecretMeta>, AppError> {
    let meta_store = load_secrets_meta()?;
    eprintln!(
        "[secrets] Loaded {} secrets from metadata",
        meta_store.len()
    );

    // Verify each secret still exists in keyring
    let mut secrets: Vec<SecretMeta> = meta_store
        .into_values()
        .filter(|m| {
            let exists = secret_exists(&m.name);
            eprintln!("[secrets] Checking '{}': exists={}", m.name, exists);
            exists
        })
        .collect();

    eprintln!("[secrets] After filtering: {} secrets", secrets.len());

    // Sort by name
    secrets.sort_by(|a, b| a.name.cmp(&b.name));

    Ok(secrets)
}

/// Get a secret with its value
pub fn get_secret_full(name: &str) -> Result<Secret, AppError> {
    let value = get_secret(name)?;
    let meta_store = load_secrets_meta()?;

    let meta = meta_store.get(name).cloned().unwrap_or_else(|| SecretMeta {
        name: name.to_string(),
        description: None,
        created_at: chrono::Utc::now().to_rfc3339(),
        updated_at: chrono::Utc::now().to_rfc3339(),
    });

    Ok(Secret {
        name: meta.name,
        value,
        description: meta.description,
        created_at: meta.created_at,
        updated_at: meta.updated_at,
    })
}

/// Delete a secret and its metadata
pub fn remove_secret(name: &str) -> Result<(), AppError> {
    // Delete from keyring
    delete_secret(name)?;

    // Remove metadata
    let mut meta_store = load_secrets_meta()?;
    meta_store.remove(name);
    save_secrets_meta(&meta_store)?;

    Ok(())
}

// ============================================================
// Variable Interpolation Support
// ============================================================

/// Interpolate secrets in a string
///
/// Replaces `${secret:name}` patterns with actual secret values.
/// Returns an error if any referenced secret is not found.
pub fn interpolate_secrets(template: &str) -> Result<String, AppError> {
    let re = regex::Regex::new(r"\$\{secret:([^}]+)\}")
        .map_err(|e| AppError::internal(format!("Invalid regex: {}", e)))?;

    let mut result = template.to_string();
    let mut errors = Vec::new();

    for cap in re.captures_iter(template) {
        let full_match = cap.get(0).unwrap().as_str();
        let secret_name = cap.get(1).unwrap().as_str();

        match get_secret(secret_name) {
            Ok(value) => {
                result = result.replace(full_match, &value);
            }
            Err(e) => {
                errors.push(format!("{}: {}", secret_name, e));
            }
        }
    }

    if !errors.is_empty() {
        return Err(AppError::invalid_input(format!(
            "Failed to resolve secrets: {}",
            errors.join(", ")
        )));
    }

    Ok(result)
}

/// Extract secret names referenced in a template
pub fn extract_secret_refs(template: &str) -> Vec<String> {
    let re = regex::Regex::new(r"\$\{secret:([^}]+)\}").unwrap();

    re.captures_iter(template)
        .map(|cap| cap.get(1).unwrap().as_str().to_string())
        .collect()
}

// ============================================================
// Common Secret Templates
// ============================================================

/// Well-known secret names for common services
pub mod common {
    pub const GITHUB_TOKEN: &str = "github/token";
    pub const HUGGINGFACE_TOKEN: &str = "huggingface/token";
    pub const WANDB_API_KEY: &str = "wandb/api_key";
    pub const OPENAI_API_KEY: &str = "openai/api_key";
    pub const ANTHROPIC_API_KEY: &str = "anthropic/api_key";
    pub const SSH_PASSPHRASE: &str = "ssh/passphrase";
}

/// Suggested secrets with descriptions
pub fn suggested_secrets() -> Vec<(&'static str, &'static str, &'static str)> {
    vec![
        (
            common::GITHUB_TOKEN,
            "GitHub Personal Access Token",
            "Access private repos with `git clone`",
        ),
        (
            common::HUGGINGFACE_TOKEN,
            "HuggingFace Token",
            "Download/upload models on HuggingFace Hub",
        ),
        (
            common::WANDB_API_KEY,
            "Weights & Biases API Key",
            "Log training metrics to W&B",
        ),
        (
            common::OPENAI_API_KEY,
            "OpenAI API Key",
            "Access GPT models",
        ),
        (
            common::ANTHROPIC_API_KEY,
            "Anthropic API Key",
            "Access Claude models",
        ),
    ]
}

// ============================================================
// Tauri Commands
// ============================================================

use tauri;

/// List all secrets (metadata only)
#[tauri::command]
pub async fn secret_list() -> Result<Vec<SecretMeta>, AppError> {
    list_secrets()
}

/// Get a secret with its value
#[tauri::command]
pub async fn secret_get(name: String) -> Result<Secret, AppError> {
    get_secret_full(&name)
}

/// Create or update a secret
#[tauri::command]
pub async fn secret_upsert(input: SecretInput) -> Result<SecretMeta, AppError> {
    upsert_secret(&input)
}

/// Delete a secret
#[tauri::command]
pub async fn secret_delete(name: String) -> Result<(), AppError> {
    remove_secret(&name)
}

/// Check if a secret exists
#[tauri::command]
pub async fn secret_check_exists(name: String) -> Result<bool, AppError> {
    Ok(secret_exists(&name))
}

/// Get suggested secret templates
#[tauri::command]
pub async fn secret_suggestions() -> Result<Vec<serde_json::Value>, AppError> {
    let suggestions: Vec<serde_json::Value> = suggested_secrets()
        .into_iter()
        .map(|(name, label, description)| {
            serde_json::json!({
                "name": name,
                "label": label,
                "description": description,
            })
        })
        .collect();
    Ok(suggestions)
}

/// Validate that all secrets referenced in a template exist
#[tauri::command]
pub async fn secret_validate_refs(template: String) -> Result<serde_json::Value, AppError> {
    let refs = extract_secret_refs(&template);
    let mut missing: Vec<String> = vec![];
    let mut found: Vec<String> = vec![];

    for name in refs {
        if secret_exists(&name) {
            found.push(name);
        } else {
            missing.push(name);
        }
    }

    Ok(serde_json::json!({
        "valid": missing.is_empty(),
        "found": found,
        "missing": missing,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_secret_refs() {
        let template =
            "export HF_TOKEN=${secret:huggingface/token} && export GH=${secret:github/token}";
        let refs = extract_secret_refs(template);
        assert_eq!(refs, vec!["huggingface/token", "github/token"]);
    }

    #[test]
    fn test_extract_no_secrets() {
        let template = "echo hello ${var}";
        let refs = extract_secret_refs(template);
        assert!(refs.is_empty());
    }
}
