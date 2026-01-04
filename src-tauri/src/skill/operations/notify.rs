//! Notification operations

use crate::error::AppError;
use crate::skill::types::NotifyLevel;

/// Send a notification (macOS native)
pub async fn send(
    title: &str,
    message: Option<&str>,
    _level: &NotifyLevel,
) -> Result<(), AppError> {
    // Use osascript for macOS notifications
    let script = if let Some(msg) = message {
        format!(
            r#"display notification "{}" with title "{}""#,
            msg.replace('"', r#"\""#),
            title.replace('"', r#"\""#)
        )
    } else {
        format!(
            r#"display notification "" with title "{}""#,
            title.replace('"', r#"\""#)
        )
    };

    let output = tokio::process::Command::new("osascript")
        .arg("-e")
        .arg(&script)
        .output()
        .await
        .map_err(|e| AppError::command(format!("Failed to send notification: {e}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(AppError::command(format!("Notification failed: {stderr}")));
    }

    Ok(())
}
