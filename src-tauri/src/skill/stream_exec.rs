//! PTY-based command execution with interactive input support
//!
//! This module provides a command executor that:
//! - Uses PTY (pseudo-terminal) for realistic terminal emulation
//! - Captures all output including prompts without newlines
//! - Detects when input is needed (password prompts, y/n questions)
//! - Supports sending input to the process

use std::collections::HashMap;
use std::io::{Read, Write};
use std::sync::Arc;
use std::time::Duration;

use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use regex::Regex;
use tokio::sync::{mpsc, oneshot, Mutex};

use crate::error::AppError;

/// Safely truncate a string to keep approximately the last `max_bytes` bytes,
/// ensuring we don't split in the middle of a UTF-8 character.
fn truncate_string_end(s: &str, max_bytes: usize) -> String {
    if s.len() <= max_bytes {
        return s.to_string();
    }
    // Find a valid char boundary near the target position
    let start = s.len() - max_bytes;
    let mut boundary = start;
    // Walk forward until we find a char boundary
    while boundary < s.len() && !s.is_char_boundary(boundary) {
        boundary += 1;
    }
    if boundary >= s.len() {
        String::new()
    } else {
        s[boundary..].to_string()
    }
}

/// Patterns that indicate the process is waiting for user input.
/// These are checked case-insensitively against the accumulated output.
const INPUT_PROMPTS: &[&str] = &[
    // Password prompts (various formats)
    "password:",
    "password for",
    "password for ",  // With trailing space (common in sudo prompts)
    "passphrase:",
    "passphrase for",
    "'s password:",   // SSH-style "user's password:"
    // sudo-specific patterns
    "sudo password",
    "[sudo]",         // Will be combined with password check below
    // Yes/No prompts
    "[y/n]",
    "[y/n]:",
    "(y/n)",
    "(y/n):",
    "[yes/no]",
    "[yes/no]:",
    "(yes/no)",
    "(yes/no):",
    "yes/no",
    // Question prompts
    "continue?",
    "proceed?",
    "are you sure?",
    "overwrite?",
    "replace?",
    // Input request prompts
    "enter passphrase",
    "enter password",
    "enter pin",
    "verification code:",
    "token:",
];

/// Check if the output indicates input is needed
fn detect_input_prompt(text: &str) -> Option<String> {
    let lower = text.to_lowercase();

    for pattern in INPUT_PROMPTS {
        if lower.contains(pattern) {
            // Extract the line containing the prompt
            for line in text.lines().rev() {
                if line.to_lowercase().contains(pattern) {
                    return Some(line.trim().to_string());
                }
            }
            // If no line found, return the last non-empty line
            let trimmed = text.trim();
            if !trimmed.is_empty() {
                return Some(trimmed.lines().last().unwrap_or(trimmed).to_string());
            }
        }
    }

    // Check for common sudo pattern
    if lower.contains("[sudo]") && lower.contains("password") {
        let trimmed = text.trim();
        return Some(trimmed.lines().last().unwrap_or(trimmed).to_string());
    }

    None
}

/// Strip ANSI escape codes from text
fn strip_ansi(s: &str) -> String {
    lazy_static::lazy_static! {
        static ref ANSI_RE: Regex = Regex::new(r"\x1b\[[0-9;]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-Za-z]|\x08|\x07").unwrap();
    }
    ANSI_RE.replace_all(s, "").to_string()
}

/// Events emitted during command execution
#[derive(Debug, Clone)]
pub enum StreamEvent {
    /// Output received (already stripped of ANSI codes)
    Output { data: String },
    /// Input is needed from the user
    InputNeeded { prompt: String },
    /// Process exited
    Exited { code: Option<i32> },
}

/// Handle to send input to a running command
#[derive(Clone)]
pub struct InputHandle {
    tx: mpsc::Sender<String>,
}

impl InputHandle {
    pub async fn send(&self, input: String) -> Result<(), AppError> {
        self.tx
            .send(input)
            .await
            .map_err(|_| AppError::command("Failed to send input to process"))
    }
}

/// State for a streaming command execution
pub struct StreamingExecution {
    /// Channel to receive events
    pub events_rx: mpsc::Receiver<StreamEvent>,
    /// Handle to send input
    pub input_handle: InputHandle,
    /// Channel to cancel the execution
    cancel_tx: Option<oneshot::Sender<()>>,
}

impl StreamingExecution {
    /// Cancel the execution
    pub fn cancel(&mut self) {
        if let Some(tx) = self.cancel_tx.take() {
            let _ = tx.send(());
        }
    }
}

/// Execute a command locally using PTY
pub async fn execute_streaming(
    command: &str,
    workdir: Option<&str>,
    env: &HashMap<String, String>,
    shell: Option<&str>,
) -> Result<StreamingExecution, AppError> {
    let shell = shell
        .map(|s| s.to_string())
        .or_else(|| std::env::var("SHELL").ok())
        .unwrap_or_else(|| "sh".to_string());

    // Build the full command with workdir
    let mut full_cmd = String::new();
    if let Some(wd) = workdir {
        full_cmd.push_str(&format!("cd {} && ", shell_escape(wd)));
    }
    full_cmd.push_str(command);

    // Create PTY
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: 24,
            cols: 80,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::command(format!("Failed to create PTY: {e}")))?;

    // Build command
    let mut cmd = CommandBuilder::new(&shell);
    cmd.arg("-c");
    cmd.arg(&full_cmd);

    // Add environment variables
    for (key, value) in env {
        cmd.env(key, value);
    }

    // Spawn the command
    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| AppError::command(format!("Failed to spawn command: {e}")))?;

    // Get master for reading/writing
    let master = pair.master;

    // Create channels
    let (events_tx, events_rx) = mpsc::channel::<StreamEvent>(256);
    let (input_tx, mut input_rx) = mpsc::channel::<String>(16);
    let (cancel_tx, mut cancel_rx) = oneshot::channel::<()>();

    // Clone reader from master
    let mut master_reader = master
        .try_clone_reader()
        .map_err(|e| AppError::command(format!("Failed to clone PTY reader: {e}")))?;

    // Take writer from master (consumes it, so do this after cloning reader)
    let master_writer = master
        .take_writer()
        .map_err(|e| AppError::command(format!("Failed to take PTY writer: {e}")))?;
    let master_writer = Arc::new(std::sync::Mutex::new(master_writer));

    // Spawn reader task
    let events_tx_reader = events_tx.clone();
    std::thread::spawn(move || {
        let mut buffer = [0u8; 4096];
        let mut accumulated = String::new();
        let mut last_prompt_sent: Option<String> = None;
        let mut last_prompt_time = std::time::Instant::now();

        loop {
            match master_reader.read(&mut buffer) {
                Ok(0) => break, // EOF
                Ok(n) => {
                    let text = String::from_utf8_lossy(&buffer[..n]);
                    let cleaned = strip_ansi(&text);

                    if !cleaned.is_empty() {
                        accumulated.push_str(&cleaned);

                        // Send output event
                        let _ = events_tx_reader.blocking_send(StreamEvent::Output {
                            data: cleaned.clone(),
                        });

                        // Check for input prompt
                        // We check on every chunk but only emit if:
                        // 1. It's a new/different prompt, OR
                        // 2. Enough time has passed since the last identical prompt (to handle re-prompts)
                        if let Some(prompt) = detect_input_prompt(&accumulated) {
                            let now = std::time::Instant::now();
                            let should_emit = match &last_prompt_sent {
                                None => true,
                                Some(prev) => {
                                    // Different prompt -> emit
                                    // Same prompt but >2s passed -> emit (re-prompt after failed input)
                                    prompt != *prev
                                        || now.duration_since(last_prompt_time)
                                            > Duration::from_secs(2)
                                }
                            };

                            if should_emit {
                                let _ = events_tx_reader
                                    .blocking_send(StreamEvent::InputNeeded { prompt: prompt.clone() });
                                last_prompt_sent = Some(prompt);
                                last_prompt_time = now;
                                accumulated.clear();
                            }
                        }

                        // Keep accumulated buffer reasonable
                        if accumulated.len() > 4096 {
                            accumulated = truncate_string_end(&accumulated, 2048);
                        }
                    }
                }
                Err(_) => break,
            }
        }
    });

    // Spawn input writer task
    let master_writer_clone = master_writer.clone();
    tokio::spawn(async move {
        while let Some(input) = input_rx.recv().await {
            let data = if input.ends_with('\n') {
                input
            } else {
                format!("{}\n", input)
            };
            let mut writer = match master_writer_clone.lock() {
                Ok(w) => w,
                Err(_) => break,
            };
            if writer.write_all(data.as_bytes()).is_err() {
                break;
            }
            let _ = writer.flush();
        }
    });

    // Spawn process waiter
    let events_tx_exit = events_tx.clone();
    let child = Arc::new(Mutex::new(child));
    let child_clone = child.clone();
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_millis(100)) => {
                    let mut child_guard = child_clone.lock().await;
                    match child_guard.try_wait() {
                        Ok(Some(status)) => {
                            let code = Some(status.exit_code() as i32);
                            let _ = events_tx_exit.send(StreamEvent::Exited { code }).await;
                            break;
                        }
                        Ok(None) => continue, // Still running
                        Err(_) => {
                            let _ = events_tx_exit.send(StreamEvent::Exited { code: None }).await;
                            break;
                        }
                    }
                }
                _ = &mut cancel_rx => {
                    let mut child_guard = child_clone.lock().await;
                    let _ = child_guard.kill();
                    let _ = events_tx_exit.send(StreamEvent::Exited { code: Some(130) }).await;
                    break;
                }
            }
        }
    });

    Ok(StreamingExecution {
        events_rx,
        input_handle: InputHandle { tx: input_tx },
        cancel_tx: Some(cancel_tx),
    })
}

/// Execute a command via SSH with PTY
pub async fn execute_streaming_ssh(
    host_id: &str,
    command: &str,
    workdir: Option<&str>,
    env: &HashMap<String, String>,
) -> Result<StreamingExecution, AppError> {
    use crate::host;

    let ssh = host::resolve_ssh_spec_with_retry(host_id, Duration::from_secs(180)).await?;

    // Build remote command with workdir and env
    let mut full_cmd = String::new();

    // Add environment variables
    for (key, value) in env {
        full_cmd.push_str(&format!("export {}={}; ", key, shell_escape(value)));
    }

    // Add workdir
    if let Some(wd) = workdir {
        full_cmd.push_str(&format!("cd {} && ", shell_escape(wd)));
    }

    full_cmd.push_str(command);

    // Build SSH command with PTY allocation
    let mut ssh_args = ssh.common_ssh_options();
    ssh_args.push("-tt".to_string()); // Force PTY allocation
    ssh_args.push(ssh.target());
    ssh_args.push(full_cmd);

    // Create local PTY for the SSH process
    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: 24,
            cols: 80,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::command(format!("Failed to create PTY: {e}")))?;

    // Build SSH command
    let mut cmd = CommandBuilder::new("ssh");
    for arg in &ssh_args {
        cmd.arg(arg);
    }

    // Spawn the SSH process
    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| AppError::command(format!("Failed to spawn SSH: {e}")))?;

    let master = pair.master;

    // Create channels
    let (events_tx, events_rx) = mpsc::channel::<StreamEvent>(256);
    let (input_tx, mut input_rx) = mpsc::channel::<String>(16);
    let (cancel_tx, mut cancel_rx) = oneshot::channel::<()>();

    // Clone reader from master
    let mut master_reader = master
        .try_clone_reader()
        .map_err(|e| AppError::command(format!("Failed to clone PTY reader: {e}")))?;

    // Take writer from master
    let master_writer = master
        .take_writer()
        .map_err(|e| AppError::command(format!("Failed to take PTY writer: {e}")))?;
    let master_writer = Arc::new(std::sync::Mutex::new(master_writer));

    // Spawn reader task
    let events_tx_reader = events_tx.clone();
    std::thread::spawn(move || {
        let mut buffer = [0u8; 4096];
        let mut accumulated = String::new();
        let mut last_prompt_sent: Option<String> = None;
        let mut last_prompt_time = std::time::Instant::now();

        loop {
            match master_reader.read(&mut buffer) {
                Ok(0) => break,
                Ok(n) => {
                    let text = String::from_utf8_lossy(&buffer[..n]);
                    let cleaned = strip_ansi(&text);

                    if !cleaned.is_empty() {
                        accumulated.push_str(&cleaned);

                        let _ = events_tx_reader.blocking_send(StreamEvent::Output {
                            data: cleaned.clone(),
                        });

                        // Check for input prompt
                        // We check on every chunk but only emit if:
                        // 1. It's a new/different prompt, OR
                        // 2. Enough time has passed since the last identical prompt (to handle re-prompts)
                        if let Some(prompt) = detect_input_prompt(&accumulated) {
                            let now = std::time::Instant::now();
                            let should_emit = match &last_prompt_sent {
                                None => true,
                                Some(prev) => {
                                    // Different prompt -> emit
                                    // Same prompt but >2s passed -> emit (re-prompt after failed input)
                                    prompt != *prev
                                        || now.duration_since(last_prompt_time)
                                            > Duration::from_secs(2)
                                }
                            };

                            if should_emit {
                                let _ = events_tx_reader
                                    .blocking_send(StreamEvent::InputNeeded { prompt: prompt.clone() });
                                last_prompt_sent = Some(prompt);
                                last_prompt_time = now;
                                accumulated.clear();
                            }
                        }

                        if accumulated.len() > 4096 {
                            accumulated = truncate_string_end(&accumulated, 2048);
                        }
                    }
                }
                Err(_) => break,
            }
        }
    });

    // Spawn input writer task
    let master_writer_clone = master_writer.clone();
    tokio::spawn(async move {
        while let Some(input) = input_rx.recv().await {
            let data = if input.ends_with('\n') {
                input
            } else {
                format!("{}\n", input)
            };
            let mut writer = match master_writer_clone.lock() {
                Ok(w) => w,
                Err(_) => break,
            };
            if writer.write_all(data.as_bytes()).is_err() {
                break;
            }
            let _ = writer.flush();
        }
    });

    // Spawn process waiter
    let events_tx_exit = events_tx.clone();
    let child = Arc::new(Mutex::new(child));
    let child_clone = child.clone();
    tokio::spawn(async move {
        loop {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_millis(100)) => {
                    let mut child_guard = child_clone.lock().await;
                    match child_guard.try_wait() {
                        Ok(Some(status)) => {
                            let code = Some(status.exit_code() as i32);
                            let _ = events_tx_exit.send(StreamEvent::Exited { code }).await;
                            break;
                        }
                        Ok(None) => continue,
                        Err(_) => {
                            let _ = events_tx_exit.send(StreamEvent::Exited { code: None }).await;
                            break;
                        }
                    }
                }
                _ = &mut cancel_rx => {
                    let mut child_guard = child_clone.lock().await;
                    let _ = child_guard.kill();
                    let _ = events_tx_exit.send(StreamEvent::Exited { code: Some(130) }).await;
                    break;
                }
            }
        }
    });

    Ok(StreamingExecution {
        events_rx,
        input_handle: InputHandle { tx: input_tx },
        cancel_tx: Some(cancel_tx),
    })
}

/// Simple shell escape
fn shell_escape(s: &str) -> String {
    if s.chars()
        .all(|c| c.is_alphanumeric() || c == '_' || c == '-' || c == '/' || c == '.')
    {
        s.to_string()
    } else {
        format!("'{}'", s.replace('\'', "'\\''"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_input_prompt() {
        assert!(detect_input_prompt("[sudo] password for user:").is_some());
        assert!(detect_input_prompt("Password:").is_some());
        assert!(detect_input_prompt("Continue? [y/N]").is_some());
        assert!(detect_input_prompt("Are you sure? (yes/no)").is_some());
        assert!(detect_input_prompt("Enter passphrase:").is_some());

        assert!(detect_input_prompt("Installing packages...").is_none());
        assert!(detect_input_prompt("Done.").is_none());
    }

    #[test]
    fn test_strip_ansi() {
        assert_eq!(strip_ansi("\x1b[32mGreen\x1b[0m"), "Green");
        assert_eq!(strip_ansi("Normal text"), "Normal text");
        assert_eq!(strip_ansi("\x1b[1;31mBold Red\x1b[0m"), "Bold Red");
    }
}
