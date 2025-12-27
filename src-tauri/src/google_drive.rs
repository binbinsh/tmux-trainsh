//! Google Drive module
//!
//! Provides OAuth flow and operations for Google Drive:
//! - OAuth authentication for direct Google Drive access
//! - Mount operations for Colab/Vast.ai integration (TODO)

use serde::{Deserialize, Serialize};

use crate::error::AppError;

/// URL encode a string
fn url_encode(s: &str) -> String {
    let mut encoded = String::new();
    for c in s.chars() {
        match c {
            'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => encoded.push(c),
            ' ' => encoded.push_str("%20"),
            _ => {
                for b in c.to_string().as_bytes() {
                    encoded.push_str(&format!("%{:02X}", b));
                }
            }
        }
    }
    encoded
}

// ============================================================
// Types
// ============================================================

/// OAuth configuration for starting the flow
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OAuthConfig {
    pub client_id: String,
    pub client_secret: String,
}

/// OAuth authorization URL response
#[derive(Debug, Clone, Serialize)]
pub struct OAuthUrlResponse {
    pub auth_url: String,
    pub redirect_uri: String,
}

/// OAuth token response
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OAuthToken {
    pub access_token: String,
    pub refresh_token: String,
    pub token_type: String,
    pub expiry: String,
}

/// Full token JSON for rclone (includes client credentials)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RcloneToken {
    pub access_token: String,
    pub token_type: String,
    pub refresh_token: String,
    pub expiry: String,
}

// ============================================================
// OAuth Flow
// ============================================================

const GOOGLE_AUTH_URL: &str = "https://accounts.google.com/o/oauth2/v2/auth";
const GOOGLE_TOKEN_URL: &str = "https://oauth2.googleapis.com/token";
// Use OOB redirect for desktop apps - user copies the code manually
const REDIRECT_URI: &str = "urn:ietf:wg:oauth:2.0:oob";

/// Generate the OAuth authorization URL for Google Drive
pub fn generate_auth_url(config: &OAuthConfig) -> OAuthUrlResponse {
    // Build OAuth URL with required scopes for Google Drive
    let scopes = "https://www.googleapis.com/auth/drive";
    
    let auth_url = format!(
        "{}?client_id={}&redirect_uri={}&response_type=code&scope={}&access_type=offline&prompt=consent",
        GOOGLE_AUTH_URL,
        url_encode(&config.client_id),
        url_encode(REDIRECT_URI),
        url_encode(scopes)
    );

    OAuthUrlResponse {
        auth_url,
        redirect_uri: REDIRECT_URI.to_string(),
    }
}

/// Exchange authorization code for tokens
pub async fn exchange_code(
    config: &OAuthConfig,
    auth_code: &str,
) -> Result<RcloneToken, AppError> {
    let client = reqwest::Client::new();
    
    let params = [
        ("client_id", config.client_id.as_str()),
        ("client_secret", config.client_secret.as_str()),
        ("code", auth_code.trim()),
        ("grant_type", "authorization_code"),
        ("redirect_uri", REDIRECT_URI),
    ];

    let response = client
        .post(GOOGLE_TOKEN_URL)
        .form(&params)
        .send()
        .await
        .map_err(|e| AppError::command(format!("Failed to exchange code: {}", e)))?;

    if !response.status().is_success() {
        let error_text = response.text().await.unwrap_or_default();
        return Err(AppError::command(format!(
            "Token exchange failed: {}",
            error_text
        )));
    }

    let token_response: serde_json::Value = response
        .json()
        .await
        .map_err(|e| AppError::command(format!("Failed to parse token response: {}", e)))?;

    // Parse expiry time
    let expires_in = token_response
        .get("expires_in")
        .and_then(|v| v.as_i64())
        .unwrap_or(3600);
    
    let expiry = chrono::Utc::now() + chrono::Duration::seconds(expires_in);

    let token = RcloneToken {
        access_token: token_response
            .get("access_token")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        token_type: token_response
            .get("token_type")
            .and_then(|v| v.as_str())
            .unwrap_or("Bearer")
            .to_string(),
        refresh_token: token_response
            .get("refresh_token")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        expiry: expiry.to_rfc3339(),
    };

    if token.access_token.is_empty() {
        return Err(AppError::command("No access token in response".to_string()));
    }

    Ok(token)
}

/// Verify that a token is valid by making a test API call
pub async fn verify_token(token: &RcloneToken) -> Result<bool, AppError> {
    let client = reqwest::Client::new();
    
    let response = client
        .get("https://www.googleapis.com/drive/v3/about?fields=user")
        .header("Authorization", format!("Bearer {}", token.access_token))
        .send()
        .await
        .map_err(|e| AppError::command(format!("Failed to verify token: {}", e)))?;

    Ok(response.status().is_success())
}

/// Format token as JSON string for rclone config
pub fn format_token_for_rclone(token: &RcloneToken) -> String {
    serde_json::json!({
        "access_token": token.access_token,
        "token_type": token.token_type,
        "refresh_token": token.refresh_token,
        "expiry": token.expiry,
    })
    .to_string()
}

/// Check if token is expired (with 5 minute buffer)
pub fn is_token_expired(token_json: &str) -> bool {
    let parsed: Result<RcloneToken, _> = serde_json::from_str(token_json);
    match parsed {
        Ok(token) => {
            if let Ok(expiry) = chrono::DateTime::parse_from_rfc3339(&token.expiry) {
                let now = chrono::Utc::now();
                let buffer = chrono::Duration::minutes(5);
                expiry < now + buffer
            } else {
                true // Can't parse expiry, assume expired
            }
        }
        Err(_) => true, // Can't parse token, assume expired
    }
}

/// Refresh an expired token
pub async fn refresh_token(
    client_id: &str,
    client_secret: &str,
    token_json: &str,
) -> Result<String, AppError> {
    let token: RcloneToken = serde_json::from_str(token_json)
        .map_err(|e| AppError::invalid_input(format!("Invalid token format: {}", e)))?;
    
    if token.refresh_token.is_empty() {
        return Err(AppError::command("No refresh token available"));
    }
    
    let client = reqwest::Client::new();
    
    let params = [
        ("client_id", client_id),
        ("client_secret", client_secret),
        ("refresh_token", &token.refresh_token),
        ("grant_type", "refresh_token"),
    ];
    
    let response = client
        .post(GOOGLE_TOKEN_URL)
        .form(&params)
        .send()
        .await
        .map_err(|e| AppError::command(format!("Failed to refresh token: {}", e)))?;
    
    if !response.status().is_success() {
        let error_text = response.text().await.unwrap_or_default();
        return Err(AppError::command(format!(
            "Token refresh failed: {}",
            error_text
        )));
    }
    
    let token_response: serde_json::Value = response
        .json()
        .await
        .map_err(|e| AppError::command(format!("Failed to parse refresh response: {}", e)))?;
    
    // Parse new expiry time
    let expires_in = token_response
        .get("expires_in")
        .and_then(|v| v.as_i64())
        .unwrap_or(3600);
    
    let expiry = chrono::Utc::now() + chrono::Duration::seconds(expires_in);
    
    // Build new token (refresh_token might not be returned, use old one)
    let new_token = RcloneToken {
        access_token: token_response
            .get("access_token")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        token_type: token_response
            .get("token_type")
            .and_then(|v| v.as_str())
            .unwrap_or("Bearer")
            .to_string(),
        refresh_token: token_response
            .get("refresh_token")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .unwrap_or(token.refresh_token), // Keep old refresh token if not returned
        expiry: expiry.to_rfc3339(),
    };
    
    if new_token.access_token.is_empty() {
        return Err(AppError::command("No access token in refresh response"));
    }
    
    Ok(format_token_for_rclone(&new_token))
}

/// Test Google Drive connection using librclone
pub fn test_gdrive_connection(
    client_id: &str,
    client_secret: &str,
    token_json: &str,
) -> Result<bool, AppError> {
    let remote_name = format!(
        "gdrive_test_{}",
        uuid::Uuid::new_v4().to_string().replace("-", "")[..8].to_string()
    );

    // Create empty remote first, then set parameters to avoid OAuth trigger
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
        .map_err(|e| AppError::command(format!("Failed to create test remote: {}", e)))?;

    // Set parameters one by one
    let _ = librclone::rpc("config/update", &serde_json::json!({
        "name": remote_name,
        "parameters": { "client_id": client_id },
        "opt": { "nonInteractive": true }
    }).to_string());
    
    let _ = librclone::rpc("config/update", &serde_json::json!({
        "name": remote_name,
        "parameters": { "client_secret": client_secret },
        "opt": { "nonInteractive": true }
    }).to_string());
    
    let _ = librclone::rpc("config/update", &serde_json::json!({
        "name": remote_name,
        "parameters": { "token": token_json },
        "opt": { "nonInteractive": true }
    }).to_string());
    
    let _ = librclone::rpc("config/update", &serde_json::json!({
        "name": remote_name,
        "parameters": { "scope": "drive" },
        "opt": { "nonInteractive": true }
    }).to_string());

    // Try to list root to verify connection
    let list_opts = serde_json::json!({
        "fs": format!("{}:", remote_name),
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
        Ok(_) => Ok(true),
        Err(e) => {
            eprintln!("GDrive test failed: {}", e);
            Ok(false)
        }
    }
}

// ============================================================
// Tauri Commands
// ============================================================

/// Generate OAuth URL for Google Drive
#[tauri::command]
pub async fn gdrive_generate_auth_url(
    client_id: String,
    client_secret: String,
) -> Result<OAuthUrlResponse, AppError> {
    let config = OAuthConfig {
        client_id,
        client_secret,
    };
    Ok(generate_auth_url(&config))
}

/// Exchange authorization code for tokens
#[tauri::command]
pub async fn gdrive_exchange_code(
    client_id: String,
    client_secret: String,
    auth_code: String,
) -> Result<String, AppError> {
    let config = OAuthConfig {
        client_id,
        client_secret,
    };
    
    let token = exchange_code(&config, &auth_code).await?;
    let token_json = format_token_for_rclone(&token);
    
    Ok(token_json)
}

/// Verify Google Drive token
#[tauri::command]
pub async fn gdrive_verify_token(token_json: String) -> Result<bool, AppError> {
    let token: RcloneToken = serde_json::from_str(&token_json)
        .map_err(|e| AppError::invalid_input(format!("Invalid token format: {}", e)))?;
    
    verify_token(&token).await
}

/// Test Google Drive connection with full credentials
#[tauri::command]
pub async fn gdrive_test_connection(
    client_id: String,
    client_secret: String,
    token_json: String,
) -> Result<bool, AppError> {
    test_gdrive_connection(&client_id, &client_secret, &token_json)
}

