//! Persistent recipe execution logs (JSONL).
//!
//! Each interactive recipe execution writes structured log entries to a JSONL file
//! under the app data directory so logs can be replayed and exported.

use std::path::PathBuf;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncBufReadExt, AsyncSeekExt, AsyncWriteExt, BufReader};

use crate::config::doppio_data_dir;
use crate::error::AppError;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum RecipeLogStream {
    System,
    Progress,
    Stdout,
    Stderr,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecipeLogEntry {
    pub timestamp: String,
    pub stream: RecipeLogStream,
    #[serde(default)]
    pub step_id: Option<String>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecipeLogChunk {
    pub execution_id: String,
    pub cursor: u64,
    pub next_cursor: u64,
    pub eof: bool,
    pub entries: Vec<RecipeLogEntry>,
}

fn logs_dir() -> PathBuf {
    doppio_data_dir().join("recipe_executions").join("logs")
}

fn log_path(execution_id: &str) -> PathBuf {
    logs_dir().join(format!("interactive-{}.jsonl", execution_id))
}

pub fn now_rfc3339() -> String {
    Utc::now().to_rfc3339()
}

pub async fn append_entry(execution_id: &str, entry: &RecipeLogEntry) -> Result<(), AppError> {
    if execution_id.trim().is_empty() {
        return Err(AppError::invalid_input("execution_id is required"));
    }

    let dir = logs_dir();
    tokio::fs::create_dir_all(&dir).await?;

    let path = log_path(execution_id);
    let mut f = tokio::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .await?;

    let line = serde_json::to_string(entry)?;
    f.write_all(line.as_bytes()).await?;
    f.write_all(b"\n").await?;
    Ok(())
}

pub async fn read_chunk(
    execution_id: &str,
    cursor: Option<u64>,
    max_bytes: Option<u64>,
) -> Result<RecipeLogChunk, AppError> {
    if execution_id.trim().is_empty() {
        return Err(AppError::invalid_input("execution_id is required"));
    }

    let cursor = cursor.unwrap_or(0);
    let max_bytes = max_bytes.unwrap_or(256 * 1024).max(4 * 1024);

    let path = log_path(execution_id);
    let meta = match tokio::fs::metadata(&path).await {
        Ok(m) => m,
        Err(_) => {
            return Ok(RecipeLogChunk {
                execution_id: execution_id.to_string(),
                cursor,
                next_cursor: cursor,
                eof: true,
                entries: vec![],
            });
        }
    };
    let file_len = meta.len();
    if cursor >= file_len {
        return Ok(RecipeLogChunk {
            execution_id: execution_id.to_string(),
            cursor,
            next_cursor: cursor,
            eof: true,
            entries: vec![],
        });
    }

    let file = tokio::fs::File::open(&path).await?;
    let mut reader = BufReader::new(file);
    reader
        .seek(std::io::SeekFrom::Start(cursor))
        .await
        .map_err(|e| AppError::io(format!("Failed to seek log file: {e}")))?;

    let mut entries = Vec::new();
    let mut bytes_read: u64 = 0;
    while bytes_read < max_bytes {
        let mut line = String::new();
        let n = reader
            .read_line(&mut line)
            .await
            .map_err(|e| AppError::io(format!("Failed to read log file: {e}")))?;
        if n == 0 {
            break;
        }
        bytes_read = bytes_read.saturating_add(n as u64);

        let trimmed = line.trim_end_matches(&['\r', '\n'][..]).trim();
        if trimmed.is_empty() {
            continue;
        }

        match serde_json::from_str::<RecipeLogEntry>(trimmed) {
            Ok(entry) => entries.push(entry),
            Err(_) => entries.push(RecipeLogEntry {
                timestamp: now_rfc3339(),
                stream: RecipeLogStream::System,
                step_id: None,
                message: trimmed.to_string(),
            }),
        }
    }

    let next_cursor = cursor.saturating_add(bytes_read);
    Ok(RecipeLogChunk {
        execution_id: execution_id.to_string(),
        cursor,
        next_cursor,
        eof: next_cursor >= file_len,
        entries,
    })
}

pub async fn clear(execution_id: &str) -> Result<(), AppError> {
    if execution_id.trim().is_empty() {
        return Err(AppError::invalid_input("execution_id is required"));
    }
    let path = log_path(execution_id);
    if tokio::fs::try_exists(&path).await.unwrap_or(false) {
        tokio::fs::remove_file(&path).await?;
    }
    Ok(())
}
