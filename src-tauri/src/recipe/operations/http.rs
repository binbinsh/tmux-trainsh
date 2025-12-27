//! HTTP request operations

use std::collections::HashMap;
use std::time::Duration;

use crate::error::AppError;
use crate::recipe::types::HttpMethod;

/// Make an HTTP request
pub async fn request(
    method: &HttpMethod,
    url: &str,
    headers: &HashMap<String, String>,
    body: Option<&str>,
    timeout_secs: Option<u64>,
) -> Result<String, AppError> {
    let timeout = timeout_secs.unwrap_or(30);
    
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(timeout))
        .build()
        .map_err(|e| AppError::http(format!("Failed to create HTTP client: {e}")))?;
    
    let method = match method {
        HttpMethod::Get => reqwest::Method::GET,
        HttpMethod::Post => reqwest::Method::POST,
        HttpMethod::Put => reqwest::Method::PUT,
        HttpMethod::Delete => reqwest::Method::DELETE,
        HttpMethod::Patch => reqwest::Method::PATCH,
    };
    
    let mut req = client.request(method, url);
    
    for (key, value) in headers {
        req = req.header(key, value);
    }
    
    if let Some(b) = body {
        req = req.body(b.to_string());
    }
    
    let resp = req.send().await
        .map_err(|e| AppError::http(format!("HTTP request failed: {e}")))?;
    
    let status = resp.status();
    let text = resp.text().await
        .map_err(|e| AppError::http(format!("Failed to read response body: {e}")))?;
    
    if !status.is_success() {
        return Err(AppError::http(format!("HTTP {} {}: {}", status.as_u16(), status.as_str(), text)));
    }
    
    Ok(text)
}

