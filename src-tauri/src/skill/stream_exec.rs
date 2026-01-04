//! Streaming command execution with interactive input support
//!
//! This module provides a command executor that:
//! - Streams stdout/stderr in real-time
//! - Detects when input is needed (password prompts, y/n questions)
//! - Supports sending input to the process stdin

use std::collections::HashMap;
use std::process::Stdio;
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::sync::{mpsc, oneshot, Mutex};

use crate::error::AppError;

/// Patterns that indicate the process is waiting for user input
const INPUT_PROMPTS: &[&str] = &[
    "password:",
    "password for",
    "passphrase:",
    "passphrase for",
    "[y/n]",
    "[y/n]:",
    "(y/n)",
    "(y/n):",
    "[yes/no]",
    "[yes/no]:",
    "(yes/no)",
    "(yes/no):",
    "continue?",
    "proceed?",
    "are you sure?",
    "enter passphrase",
    "enter password",
    "sudo password",
    ": $",
    ": ",
];

/// Check if the output line indicates input is needed
fn detect_input_prompt(line: &str) -> Option<String> {
    let lower = line.to_lowercase();
    let trimmed = lower.trim();

    // Skip empty lines
    if trimmed.is_empty() {
        return None;
    }

    for pattern in INPUT_PROMPTS {
        if trimmed.ends_with(pattern) || trimmed.contains(pattern) {
            // Return the original line as the prompt
            return Some(line.trim().to_string());
        }
    }

    // Check for common sudo pattern
    if trimmed.starts_with("[sudo]") && trimmed.contains("password") {
        return Some(line.trim().to_string());
    }

    None
}

/// Output stream type
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StreamType {
    Stdout,
    Stderr,
}

/// Events emitted during command execution
#[derive(Debug, Clone)]
pub enum StreamEvent {
    /// Output line received
    Output { stream: StreamType, data: String },
    /// Input is needed from the user
    InputNeeded { prompt: String },
    /// Process exited
    Exited { code: Option<i32> },
}

/// Handle to send input to a running command
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

/// Execute a command with streaming output and interactive input support
pub async fn execute_streaming(
    command: &str,
    workdir: Option<&str>,
    env: &HashMap<String, String>,
    shell: Option<&str>,
) -> Result<StreamingExecution, AppError> {
    let shell = shell.unwrap_or("sh");

    // Build the full command with workdir and env
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

    // Spawn the process
    let mut child = Command::new(shell)
        .arg("-c")
        .arg(&full_cmd)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| AppError::command(format!("Failed to spawn command: {e}")))?;

    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| AppError::command("Failed to get stdin"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| AppError::command("Failed to get stdout"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| AppError::command("Failed to get stderr"))?;

    // Create channels
    let (events_tx, events_rx) = mpsc::channel::<StreamEvent>(256);
    let (input_tx, mut input_rx) = mpsc::channel::<String>(16);
    let (cancel_tx, cancel_rx) = oneshot::channel::<()>();

    let stdin = Arc::new(Mutex::new(stdin));

    // Spawn stdout reader
    let events_tx_stdout = events_tx.clone();
    let mut stdout_reader = BufReader::new(stdout);
    tokio::spawn(async move {
        let mut line = String::new();
        loop {
            line.clear();
            match stdout_reader.read_line(&mut line).await {
                Ok(0) => break, // EOF
                Ok(_) => {
                    let trimmed = line.trim_end_matches(&['\r', '\n'][..]).to_string();

                    // Check for input prompt
                    if let Some(prompt) = detect_input_prompt(&trimmed) {
                        let _ = events_tx_stdout
                            .send(StreamEvent::InputNeeded { prompt })
                            .await;
                    }

                    let _ = events_tx_stdout
                        .send(StreamEvent::Output {
                            stream: StreamType::Stdout,
                            data: trimmed,
                        })
                        .await;
                }
                Err(_) => break,
            }
        }
    });

    // Spawn stderr reader
    let events_tx_stderr = events_tx.clone();
    let mut stderr_reader = BufReader::new(stderr);
    tokio::spawn(async move {
        let mut line = String::new();
        loop {
            line.clear();
            match stderr_reader.read_line(&mut line).await {
                Ok(0) => break, // EOF
                Ok(_) => {
                    let trimmed = line.trim_end_matches(&['\r', '\n'][..]).to_string();

                    // Check for input prompt in stderr too (sudo often writes to stderr)
                    if let Some(prompt) = detect_input_prompt(&trimmed) {
                        let _ = events_tx_stderr
                            .send(StreamEvent::InputNeeded { prompt })
                            .await;
                    }

                    let _ = events_tx_stderr
                        .send(StreamEvent::Output {
                            stream: StreamType::Stderr,
                            data: trimmed,
                        })
                        .await;
                }
                Err(_) => break,
            }
        }
    });

    // Spawn input writer
    tokio::spawn(async move {
        while let Some(input) = input_rx.recv().await {
            let mut stdin_guard = stdin.lock().await;
            // Write input with newline
            let data = if input.ends_with('\n') {
                input
            } else {
                format!("{}\n", input)
            };
            if stdin_guard.write_all(data.as_bytes()).await.is_err() {
                break;
            }
            if stdin_guard.flush().await.is_err() {
                break;
            }
        }
    });

    // Spawn process waiter
    let events_tx_exit = events_tx.clone();
    tokio::spawn(async move {
        let mut cancel_rx = cancel_rx;

        tokio::select! {
            result = child.wait() => {
                let code = result.ok().and_then(|s| s.code());
                let _ = events_tx_exit.send(StreamEvent::Exited { code }).await;
            }
            _ = &mut cancel_rx => {
                // Kill the process
                let _ = child.kill().await;
                let _ = events_tx_exit.send(StreamEvent::Exited { code: Some(130) }).await;
            }
        }
    });

    Ok(StreamingExecution {
        events_rx,
        input_handle: InputHandle { tx: input_tx },
        cancel_tx: Some(cancel_tx),
    })
}

/// Execute a command via SSH with streaming output
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

    // Build SSH command
    let mut cmd = Command::new("ssh");
    for arg in ssh.common_ssh_options() {
        cmd.arg(arg);
    }
    // Request PTY for interactive commands (sudo, etc.)
    cmd.arg("-tt");
    cmd.arg(ssh.target());
    cmd.arg(&full_cmd);

    cmd.stdin(Stdio::piped());
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| AppError::command(format!("Failed to spawn SSH: {e}")))?;

    let stdin = child
        .stdin
        .take()
        .ok_or_else(|| AppError::command("Failed to get stdin"))?;
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| AppError::command("Failed to get stdout"))?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| AppError::command("Failed to get stderr"))?;

    // Create channels
    let (events_tx, events_rx) = mpsc::channel::<StreamEvent>(256);
    let (input_tx, mut input_rx) = mpsc::channel::<String>(16);
    let (cancel_tx, cancel_rx) = oneshot::channel::<()>();

    let stdin = Arc::new(Mutex::new(stdin));

    // Spawn stdout reader
    let events_tx_stdout = events_tx.clone();
    let mut stdout_reader = BufReader::new(stdout);
    tokio::spawn(async move {
        let mut line = String::new();
        loop {
            line.clear();
            match stdout_reader.read_line(&mut line).await {
                Ok(0) => break,
                Ok(_) => {
                    let trimmed = line.trim_end_matches(&['\r', '\n'][..]).to_string();

                    if let Some(prompt) = detect_input_prompt(&trimmed) {
                        let _ = events_tx_stdout
                            .send(StreamEvent::InputNeeded { prompt })
                            .await;
                    }

                    let _ = events_tx_stdout
                        .send(StreamEvent::Output {
                            stream: StreamType::Stdout,
                            data: trimmed,
                        })
                        .await;
                }
                Err(_) => break,
            }
        }
    });

    // Spawn stderr reader
    let events_tx_stderr = events_tx.clone();
    let mut stderr_reader = BufReader::new(stderr);
    tokio::spawn(async move {
        let mut line = String::new();
        loop {
            line.clear();
            match stderr_reader.read_line(&mut line).await {
                Ok(0) => break,
                Ok(_) => {
                    let trimmed = line.trim_end_matches(&['\r', '\n'][..]).to_string();

                    if let Some(prompt) = detect_input_prompt(&trimmed) {
                        let _ = events_tx_stderr
                            .send(StreamEvent::InputNeeded { prompt })
                            .await;
                    }

                    let _ = events_tx_stderr
                        .send(StreamEvent::Output {
                            stream: StreamType::Stderr,
                            data: trimmed,
                        })
                        .await;
                }
                Err(_) => break,
            }
        }
    });

    // Spawn input writer
    tokio::spawn(async move {
        while let Some(input) = input_rx.recv().await {
            let mut stdin_guard = stdin.lock().await;
            let data = if input.ends_with('\n') {
                input
            } else {
                format!("{}\n", input)
            };
            if stdin_guard.write_all(data.as_bytes()).await.is_err() {
                break;
            }
            if stdin_guard.flush().await.is_err() {
                break;
            }
        }
    });

    // Spawn process waiter
    let events_tx_exit = events_tx.clone();
    tokio::spawn(async move {
        let mut cancel_rx = cancel_rx;

        tokio::select! {
            result = child.wait() => {
                let code = result.ok().and_then(|s| s.code());
                let _ = events_tx_exit.send(StreamEvent::Exited { code }).await;
            }
            _ = &mut cancel_rx => {
                let _ = child.kill().await;
                let _ = events_tx_exit.send(StreamEvent::Exited { code: Some(130) }).await;
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
}
