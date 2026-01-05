//! Skill System
//!
//! A flexible workflow engine for composing and executing automation tasks.
//! Skills define a DAG of steps that can run in parallel with dependency resolution.

pub mod execution;
pub mod interactive;
pub mod operations;
pub mod parser;
pub mod run_logs;
pub mod stream_exec;
pub mod types;

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use tauri::Emitter;
use tauri::State;
use tokio::sync::RwLock;

use crate::config::load_config;
use crate::error::AppError;
use crate::vast::VastClient;

pub use execution::*;
pub use parser::*;
pub use types::*;

fn split_command_output(combined: &str) -> (Option<String>, Option<String>) {
    let s = combined.trim();
    if s.is_empty() {
        return (None, None);
    }
    if let Some((stdout, stderr)) = s.split_once("\n--- stderr ---\n") {
        let out = stdout.trim();
        let err = stderr.trim();
        return (
            (!out.is_empty()).then(|| out.to_string()),
            (!err.is_empty()).then(|| err.to_string()),
        );
    }
    if let Some(rest) = s.strip_prefix("(stderr only)\n") {
        let err = rest.trim();
        return (None, (!err.is_empty()).then(|| err.to_string()));
    }
    (Some(s.to_string()), None)
}

fn redact_secret_placeholders(template: &str) -> String {
    let mut out = String::with_capacity(template.len());
    let mut rest = template;
    loop {
        let Some(start) = rest.find("${secret:") else {
            out.push_str(rest);
            return out;
        };
        out.push_str(&rest[..start]);
        let after = &rest[start + "${secret:".len()..];
        let Some(end) = after.find('}') else {
            out.push_str(&rest[start..]);
            return out;
        };
        out.push_str("[REDACTED]");
        rest = &after[end + 1..];
    }
}

fn interpolate_for_log(template: &str, variables: &HashMap<String, String>) -> String {
    let mut result = redact_secret_placeholders(template);
    for (key, value) in variables {
        let pattern = format!("${{{}}}", key);
        result = result.replace(&pattern, value);
    }
    result
}

fn marker_exit_code_from_line(line: &str, marker_prefix: &str) -> Option<i32> {
    let trimmed = line.trim();
    let rest = trimmed.strip_prefix(marker_prefix)?;
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        return None;
    }
    digits.parse::<i32>().ok()
}

fn find_marker_with_exit_code(buffer: &str, marker_prefix: &str) -> Option<(usize, usize, i32)> {
    let bytes = buffer.as_bytes();
    let mut from = 0usize;
    while let Some(pos) = buffer[from..].find(marker_prefix) {
        let idx = from + pos;
        let at_line_start = idx == 0 || matches!(bytes.get(idx.wrapping_sub(1)), Some(b'\n' | b'\r'));
        if !at_line_start {
            from = idx + marker_prefix.len();
            continue;
        }

        let line_end = buffer[idx..]
            .find('\n')
            .map(|off| idx + off + 1)
            .unwrap_or(buffer.len());
        let line = &buffer[idx..line_end];
        if let Some(code) = marker_exit_code_from_line(line, marker_prefix) {
            return Some((idx, line_end, code));
        }
        from = line_end;
    }
    None
}

async fn stream_terminal_output_until_marker(
    app: &tauri::AppHandle,
    term_mgr: &crate::terminal::TerminalManager,
    log_lock: &tokio::sync::Mutex<()>,
    exec_id: &str,
    term_id: &str,
    step_id: &str,
    begin_marker_line: &str,
    done_marker_prefix: &str,
    start_offset: u64,
    timeout: Option<std::time::Duration>,
) -> Result<i32, AppError> {
    use std::time::Instant;

    let poll_interval = std::time::Duration::from_millis(120);
    let started = Instant::now();
    let mut offset = start_offset;
    let mut buf = String::new();
    let mut capturing = false;

    loop {
        if let Some(timeout) = timeout {
            if started.elapsed() > timeout {
                return Err(AppError::command(format!(
                    "Step timed out after {}s",
                    timeout.as_secs()
                )));
            }
        }

        let chunk = crate::terminal::history_read_range(term_mgr, term_id, offset, 64 * 1024).await?;
        offset = chunk.offset + chunk.data.as_bytes().len() as u64;
        if chunk.data.is_empty() {
            tokio::time::sleep(poll_interval).await;
            continue;
        }

        buf.push_str(&chunk.data);

        if !capturing {
            if let Some(marker_idx) = buf.find(begin_marker_line) {
                let after = &buf[marker_idx..];
                let line_end = after
                    .find('\n')
                    .map(|off| marker_idx + off + 1)
                    .unwrap_or(buf.len());
                buf = buf[line_end..].to_string();
                capturing = true;
            } else if buf.len() > 256 * 1024 {
                buf.clear();
            }
            continue;
        }

        if let Some((marker_start, _marker_end, code)) = find_marker_with_exit_code(&buf, done_marker_prefix) {
            let out = buf[..marker_start].to_string();
            if !out.is_empty() {
                append_skill_log(
                    app,
                    log_lock,
                    exec_id,
                    Some(step_id),
                    run_logs::SkillLogStream::Stdout,
                    out,
                )
                .await;
            }
            return Ok(code);
        }

        if !buf.is_empty() {
            append_skill_log(
                app,
                log_lock,
                exec_id,
                Some(step_id),
                run_logs::SkillLogStream::Stdout,
                std::mem::take(&mut buf),
            )
            .await;
        }
    }
}

fn overlap_suffix_prefix_len(prev: &[String], next: &[String], max_check: usize) -> usize {
    let max = std::cmp::min(std::cmp::min(prev.len(), next.len()), max_check);
    for k in (0..=max).rev() {
        if prev[prev.len().saturating_sub(k)..] == next[..k] {
            return k;
        }
    }
    0
}

fn last_non_empty_line(lines: &[String]) -> Option<&str> {
    lines.iter().rev().find_map(|l| {
        let t = l.trim_end();
        if t.is_empty() {
            None
        } else {
            Some(t)
        }
    })
}

async fn stream_tmux_pane_until_marker(
    app: &tauri::AppHandle,
    log_lock: &tokio::sync::Mutex<()>,
    exec_id: &str,
    host_id: &str,
    tmux_session: &str,
    step_id: &str,
    begin_marker_line: &str,
    done_marker_prefix: &str,
    timeout: Option<std::time::Duration>,
) -> Result<i32, AppError> {
    use std::time::Instant;
    use tauri::Emitter;

    let poll_interval = std::time::Duration::from_millis(250);
    let started = Instant::now();
    let mut capturing = false;
    let mut prev_lines: Vec<String> = vec![];
    let mut last_progress: Option<String> = None;

    loop {
        if let Some(timeout) = timeout {
            if started.elapsed() > timeout {
                return Err(AppError::command(format!(
                    "Step timed out after {}s",
                    timeout.as_secs()
                )));
            }
        }

        // Capture enough scrollback to reliably include the begin/done markers.
        let capture = crate::skill::operations::tmux::capture_pane_advanced(
            host_id,
            tmux_session,
            Some(-5000),
            true,
        )
        .await;

        let capture = match capture {
            Ok(out) => out,
            Err(e) => {
                append_skill_log(
                    app,
                    log_lock,
                    exec_id,
                    Some(step_id),
                    run_logs::SkillLogStream::System,
                    format!("tmux capture-pane failed, falling back to raw terminal stream: {e}"),
                )
                .await;
                return Err(e);
            }
        };

        let mut lines: Vec<String> = capture.lines().map(|l| l.to_string()).collect();

        // Find the begin marker line and start capturing after it.
        if !capturing {
            if let Some(pos) = lines.iter().position(|l| l.trim_end() == begin_marker_line) {
                capturing = true;
                lines = lines.into_iter().skip(pos + 1).collect();
                prev_lines.clear();
                last_progress = None;
            } else {
                tokio::time::sleep(poll_interval).await;
                continue;
            }
        } else {
            // If begin marker scrolled out of window, keep using full capture as best-effort.
            if let Some(pos) = lines.iter().position(|l| l.trim_end() == begin_marker_line) {
                lines = lines.into_iter().skip(pos + 1).collect();
            }
        }

        // Detect completion marker in captured pane.
        let mut exit_code: Option<i32> = None;
        if let Some(pos) = lines
            .iter()
            .position(|l| l.trim_start().starts_with(done_marker_prefix))
        {
            let marker_line = lines[pos].trim();
            if let Some(code) = marker_exit_code_from_line(marker_line, done_marker_prefix) {
                exit_code = Some(code);
            } else {
                exit_code = Some(0);
            }
            lines.truncate(pos);
        }

        // Update live progress from the last non-empty line (excluding markers).
        if let Some(progress) = last_non_empty_line(&lines) {
            if last_progress.as_deref() != Some(progress) {
                last_progress = Some(progress.to_string());
                let runner = interactive::get_runner().await;
                let _ = runner
                    .set_step_progress(exec_id, step_id, Some(progress.to_string()))
                    .await;
                let _ = app.emit(
                    "skill:step_progress",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step_id,
                        "progress": progress,
                    }),
                );
            }
        }

        // Compute appended lines (terminal-like) and avoid spamming for in-place updates.
        let overlap = overlap_suffix_prefix_len(&prev_lines, &lines, 200);
        let mut new_lines: Vec<String> = lines[overlap..].to_vec();

        // If the only change is the last line changing, treat it as progress-only.
        if new_lines.len() == 1
            && overlap == lines.len().saturating_sub(1)
            && prev_lines.len() == lines.len()
        {
            new_lines.clear();
        }

        if !new_lines.is_empty() {
            let mut msg = new_lines.join("\n");
            msg.push('\n');
            append_skill_log(
                app,
                log_lock,
                exec_id,
                Some(step_id),
                run_logs::SkillLogStream::Stdout,
                msg,
            )
            .await;
        }

        prev_lines = lines;

        if let Some(code) = exit_code {
            // Clear progress once done.
            let runner = interactive::get_runner().await;
            let _ = runner.set_step_progress(exec_id, step_id, None).await;
            let _ = app.emit(
                "skill:step_progress",
                serde_json::json!({
                    "execution_id": exec_id,
                    "step_id": step_id,
                    "progress": serde_json::Value::Null,
                }),
            );
            return Ok(code);
        }

        tokio::time::sleep(poll_interval).await;
    }
}

async fn append_skill_log(
    app: &tauri::AppHandle,
    log_lock: &tokio::sync::Mutex<()>,
    execution_id: &str,
    step_id: Option<&str>,
    stream: run_logs::SkillLogStream,
    message: String,
) {
    let entry = run_logs::SkillLogEntry {
        timestamp: run_logs::now_rfc3339(),
        stream,
        step_id: step_id.map(|s| s.to_string()),
        message,
    };

    let _guard = log_lock.lock().await;
    if let Err(e) = run_logs::append_entry(execution_id, &entry).await {
        eprintln!("[skill_log] Failed to append log: {}", e);
        return;
    }
    let _ = app.emit(
        "skill:log_appended",
        serde_json::json!({
            "execution_id": execution_id,
            "entry": entry,
        }),
    );
}

fn skill_slug_from_name(name: &str) -> Result<String, AppError> {
    let mut out = String::new();
    let mut last_was_dash = false;

    for c in name.trim().to_lowercase().chars() {
        if c.is_alphanumeric() {
            out.push(c);
            last_was_dash = false;
            continue;
        }

        if !last_was_dash {
            out.push('-');
            last_was_dash = true;
        }
    }

    let out = out.trim_matches('-').to_string();
    if out.is_empty() {
        return Err(AppError::invalid_input(
            "Skill name must contain at least one alphanumeric character",
        ));
    }

    Ok(out)
}

fn skill_path_for_name(skills_dir: &Path, name: &str) -> Result<PathBuf, AppError> {
    Ok(skills_dir.join(format!("{}.toml", skill_slug_from_name(name)?)))
}

// ============================================================
// Skill Store
// ============================================================

/// Manages skill storage and execution
pub struct SkillStore {
    skills_dir: PathBuf,
}

impl SkillStore {
    pub fn new(data_dir: &Path) -> Self {
        Self {
            skills_dir: data_dir.join("skills"),
        }
    }

    fn skills_dir(&self) -> &PathBuf {
        &self.skills_dir
    }
}

// ============================================================
// Tauri Commands
// ============================================================

/// List all skills in the skills directory
#[tauri::command]
pub async fn skill_list(
    store: State<'_, Arc<RwLock<SkillStore>>>,
) -> Result<Vec<SkillSummary>, AppError> {
    let store = store.read().await;
    let dir = store.skills_dir();

    if !dir.exists() {
        return Ok(vec![]);
    }

    let mut summaries = Vec::new();
    let mut entries = tokio::fs::read_dir(dir).await?;

    while let Some(entry) = entries.next_entry().await? {
        let path = entry.path();
        if path.extension().map_or(false, |e| e == "toml") {
            match get_skill_summary(&path).await {
                Ok(mut summary) => {
                    match skill_path_for_name(dir, &summary.name) {
                        Ok(desired_path) => {
                            if desired_path != path {
                                if desired_path.exists() {
                                    eprintln!(
                                        "Skill file name mismatch for {:?} (wanted {:?}) but destination exists; keeping original",
                                        path, desired_path
                                    );
                                } else if let Err(e) = tokio::fs::rename(&path, &desired_path).await
                                {
                                    eprintln!(
                                        "Failed to rename skill file {:?} -> {:?}: {}",
                                        path, desired_path, e
                                    );
                                } else {
                                    summary.path = desired_path.to_string_lossy().to_string();
                                }
                            }
                        }
                        Err(e) => {
                            eprintln!("Failed to derive skill filename for {:?}: {}", path, e);
                        }
                    }
                    summaries.push(summary)
                }
                Err(e) => {
                    eprintln!("Failed to load skill {:?}: {}", path, e);
                }
            }
        }
    }

    // Sort by name
    summaries.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(summaries)
}

/// Get a skill by path
#[tauri::command]
pub async fn skill_get(path: String) -> Result<Skill, AppError> {
    load_skill(Path::new(&path)).await
}

/// Save a skill to a file
#[tauri::command]
pub async fn skill_save(
    path: String,
    skill: Skill,
    store: State<'_, Arc<RwLock<SkillStore>>>,
) -> Result<String, AppError> {
    let store = store.read().await;
    let dir = store.skills_dir();

    tokio::fs::create_dir_all(dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create skills directory: {e}")))?;

    let desired_path = skill_path_for_name(dir, &skill.name)?;

    let current_path = PathBuf::from(path);
    if current_path.exists() {
        if !current_path.starts_with(dir) {
            return Err(AppError::invalid_input("Invalid skill path"));
        }

        if current_path != desired_path {
            if desired_path.exists() {
                return Err(AppError::invalid_input(
                    "A skill with this name already exists",
                ));
            }

            tokio::fs::rename(&current_path, &desired_path)
                .await
                .map_err(|e| AppError::io(format!("Failed to rename skill file: {e}")))?;
        }
    }

    save_skill(&desired_path, &skill).await?;
    Ok(desired_path.to_string_lossy().to_string())
}

/// Delete a skill file
#[tauri::command]
pub async fn skill_delete(path: String) -> Result<(), AppError> {
    let p = Path::new(&path);
    if p.exists() {
        tokio::fs::remove_file(p)
            .await
            .map_err(|e| AppError::io(format!("Failed to delete skill: {e}")))?;
    }
    Ok(())
}

/// Validate a skill
#[tauri::command]
pub async fn skill_validate(skill: Skill) -> Result<ValidationResult, AppError> {
    Ok(validate_skill(&skill))
}

/// Create a new empty skill file
#[tauri::command]
pub async fn skill_create(
    name: String,
    store: State<'_, Arc<RwLock<SkillStore>>>,
) -> Result<String, AppError> {
    let store = store.read().await;
    let dir = store.skills_dir();

    tokio::fs::create_dir_all(dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create skills directory: {e}")))?;

    let path = skill_path_for_name(dir, &name)?;
    if path.exists() {
        return Err(AppError::invalid_input(
            "A skill with this name already exists",
        ));
    }

    let skill = Skill {
        name,
        version: "1.0.0".to_string(),
        description: None,
        target: None,
        variables: HashMap::new(),
        steps: vec![],
    };

    save_skill(&path, &skill).await?;

    Ok(path.to_string_lossy().to_string())
}

/// Import a skill from a file
#[tauri::command]
pub async fn skill_import(
    source_path: String,
    store: State<'_, Arc<RwLock<SkillStore>>>,
) -> Result<String, AppError> {
    // Load and validate the skill first
    let skill = load_skill(Path::new(&source_path)).await?;
    let validation = validate_skill(&skill);

    if !validation.valid {
        let errors: Vec<String> = validation
            .errors
            .iter()
            .map(|e| e.message.clone())
            .collect();
        return Err(AppError::invalid_input(format!(
            "Invalid skill: {}",
            errors.join(", ")
        )));
    }

    // Copy to skills directory
    let store = store.read().await;
    let dir = store.skills_dir();
    tokio::fs::create_dir_all(dir).await?;

    let dest_path = skill_path_for_name(dir, &skill.name)?;
    if dest_path.exists() {
        return Err(AppError::invalid_input(
            "A skill with this name already exists",
        ));
    }
    save_skill(&dest_path, &skill).await?;

    Ok(dest_path.to_string_lossy().to_string())
}

/// Export a skill to a file
#[tauri::command]
pub async fn skill_export(skill_path: String, dest_path: String) -> Result<(), AppError> {
    let skill = load_skill(Path::new(&skill_path)).await?;
    save_skill(Path::new(&dest_path), &skill).await
}

/// Duplicate a skill
#[tauri::command]
pub async fn skill_duplicate(
    path: String,
    new_name: String,
    store: State<'_, Arc<RwLock<SkillStore>>>,
) -> Result<String, AppError> {
    let mut skill = load_skill(Path::new(&path)).await?;
    skill.name = new_name.clone();

    let store = store.read().await;
    let dir = store.skills_dir();

    let new_path = skill_path_for_name(dir, &new_name)?;
    if new_path.exists() {
        return Err(AppError::invalid_input(
            "A skill with this name already exists",
        ));
    }

    save_skill(&new_path, &skill).await?;

    Ok(new_path.to_string_lossy().to_string())
}

// ============================================================
// Interactive Execution Commands
// ============================================================

/// Special target value for local execution
const LOCAL_TARGET: &str = "__local__";

/// Start an interactive skill execution with terminal output
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn skill_run_interactive(
    app: tauri::AppHandle,
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    path: String,
    host_id: String,
    variables: HashMap<String, String>,
    cols: Option<u16>,
    rows: Option<u16>,
    start_step_id: Option<String>,
    start_immediately: Option<bool>,
) -> Result<interactive::InteractiveExecution, AppError> {
    use crate::terminal::TermSessionInfo;
    use tauri::Emitter;

    // Load and validate skill
    let skill = load_skill(Path::new(&path)).await?;
    let validation = validate_skill(&skill);
    if !validation.valid {
        let errors: Vec<String> = validation
            .errors
            .iter()
            .map(|e| e.message.clone())
            .collect();
        return Err(AppError::invalid_input(format!(
            "Skill validation failed: {}",
            errors.join(", ")
        )));
    }

    // Check if this is local execution
    let is_local = host_id == LOCAL_TARGET;

    let (term_info, effective_host_id, connect_after_vast_start, tmux_session): (
        TermSessionInfo,
        String,
        Option<String>,
        Option<String>,
    ) = if is_local {
        // Local execution - open a local terminal
        let title = format!("Skill: {} (Local)", skill.name);
        let info = crate::terminal::open_local_inner(
            app.clone(),
            &term_mgr,
            Some(title),
            cols.unwrap_or(120),
            rows.unwrap_or(32),
        )
        .await?;
        (info, LOCAL_TARGET.to_string(), None, None)
    } else {
        // Remote execution - open SSH tmux session
        use crate::host::{default_env_vars, get_host, HostType};

        // Special host id format for Vast instances (no persisted host needed)
        if let Some(vast_instance_id) = host_id
            .strip_prefix("vast:")
            .and_then(|s| s.trim().parse::<i64>().ok())
        {
            let cfg = load_config().await?;
            let client = VastClient::from_cfg(&cfg)?;

            let inst = client.get_instance(vast_instance_id).await?;
            let inst_label = inst
                .label
                .clone()
                .filter(|s| !s.trim().is_empty())
                .unwrap_or_else(|| format!("Vast #{}", vast_instance_id));

            let tmux_session = format!(
                "skill-{}",
                uuid::Uuid::new_v4()
                    .to_string()
                    .split('-')
                    .next()
                    .unwrap_or("exec")
            );

            // If the skill contains a `vast_start` step, avoid probing SSH here (it can block the UI for ~20s).
            // We'll connect the terminal right after `vast_start` succeeds.
            let defer_connect_after_start = skill
                .steps
                .iter()
                .any(|s| matches!(s.operation, types::Operation::VastStart(_)));
            if defer_connect_after_start {
                let title = format!("Skill: {} (Waiting for Vast start)", skill.name);
                let info = crate::terminal::open_local_inner(
                    app.clone(),
                    &term_mgr,
                    Some(title),
                    cols.unwrap_or(120),
                    rows.unwrap_or(32),
                )
                .await?;
                (
                    info,
                    host_id.clone(),
                    Some(tmux_session.clone()),
                    Some(tmux_session),
                )
            } else {
                let ssh = match crate::host::resolve_ssh_spec(&host_id).await {
                    Ok(ssh) => Some(ssh),
                    Err(e) if e.message.contains("Vast SSH route is not available yet") => None,
                    Err(e) => return Err(e),
                };

                if let Some(ssh) = ssh {
                    let title = format!("Skill: {} on {}", skill.name, inst_label);

                    let info: TermSessionInfo = crate::terminal::open_ssh_tmux_inner_static(
                        app.clone(),
                        &term_mgr,
                        ssh,
                        tmux_session.clone(),
                        Some(title),
                        cols.unwrap_or(120),
                        rows.unwrap_or(32),
                        Some(default_env_vars(&HostType::Vast)),
                    )
                    .await?;

                    (info, host_id.clone(), None, Some(tmux_session))
                } else {
                    // Vast instance may be stopped and not exposing SSH metadata yet. Still allow starting the skill.
                    let title = format!("Skill: {} (Waiting for Vast SSH)", skill.name);
                    let info = crate::terminal::open_local_inner(
                        app.clone(),
                        &term_mgr,
                        Some(title),
                        cols.unwrap_or(120),
                        rows.unwrap_or(32),
                    )
                    .await?;
                    (
                        info,
                        host_id.clone(),
                        Some(tmux_session.clone()),
                        Some(tmux_session),
                    )
                }
            }
        } else {
            let host = get_host(&host_id).await?;
            let ssh = host
                .ssh
                .as_ref()
                .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;

            let tmux_session = format!(
                "skill-{}",
                uuid::Uuid::new_v4()
                    .to_string()
                    .split('-')
                    .next()
                    .unwrap_or("exec")
            );
            let title = format!("Skill: {} on {}", skill.name, host.name);

            let info: TermSessionInfo = crate::terminal::open_ssh_tmux_inner_static(
                app.clone(),
                &term_mgr,
                ssh.clone(),
                tmux_session.clone(),
                Some(title),
                cols.unwrap_or(120),
                rows.unwrap_or(32),
                Some(default_env_vars(&host.host_type)),
            )
            .await?;
            (info, host_id.clone(), None, Some(tmux_session))
        }
    };

    // Merge skill variables with overrides
    let mut merged_variables = skill.variables.clone();
    merged_variables.extend(variables.clone());
    // Add target variable if not present
    if !merged_variables.contains_key("target") {
        merged_variables.insert("target".to_string(), effective_host_id.clone());
    }
    if let Some(tmux_session) = connect_after_vast_start {
        merged_variables.insert(
            "_doppio_connect_after_vast_start".to_string(),
            "1".to_string(),
        );
        merged_variables.insert("_doppio_connect_tmux_session".to_string(), tmux_session);
    }

    // Start interactive execution
    let terminal_meta = interactive::InteractiveTerminal {
        title: term_info.title.clone(),
        tmux_session: tmux_session.clone(),
        cols: cols.unwrap_or(120),
        rows: rows.unwrap_or(32),
    };

    let runner = interactive::get_runner().await;
    let (exec_id, term_id) = runner
        .start(
            skill.clone(),
            path.clone(),
            effective_host_id.clone(),
            term_info.id.clone(),
            terminal_meta,
            merged_variables.clone(),
        )
        .await?;

    // If this execution is meant to be started manually, mark it inactive until `skill_interactive_start`.
    let auto_start = start_immediately.unwrap_or(true);
    if !auto_start {
        runner.set_active(&exec_id, false).await?;
    }

    if let Some(start_step_id) = start_step_id
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
    {
        let step_order = execution::compute_execution_order(&skill.steps)?;
        let mut skipped_steps = vec![];
        for sid in step_order {
            if sid == start_step_id {
                break;
            }
            skipped_steps.push(sid);
        }

        if !skipped_steps.is_empty() {
            let log_lock = tokio::sync::Mutex::new(());
            append_skill_log(
                &app,
                &log_lock,
                &exec_id,
                None,
                run_logs::SkillLogStream::System,
                format!(
                    "Restarting from step: {start_step_id} (skipping {} step(s))",
                    skipped_steps.len()
                ),
            )
            .await;

            for sid in skipped_steps {
                let _ = runner
                    .update_step_status(&exec_id, &sid, StepStatus::Skipped)
                    .await;
                let _ = app.emit(
                    "skill:step_skipped",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": sid,
                    }),
                );
            }
        }
    }

    // Initialize step statuses (waiting/pending) based on dependencies and any pre-skipped steps.
    {
        use std::collections::HashSet;
        let snapshot = runner.get_execution(&exec_id).await?;
        let mut completed: HashSet<String> = HashSet::new();
        for s in &snapshot.steps {
            if matches!(s.status, StepStatus::Success | StepStatus::Skipped) {
                completed.insert(s.step_id.clone());
            }
        }
        for step in &skill.steps {
            if completed.contains(&step.id) {
                continue;
            }
            let status = if step.depends_on.iter().all(|dep| completed.contains(dep)) {
                StepStatus::Pending
            } else {
                StepStatus::Waiting
            };
            let _ = runner.update_step_status(&exec_id, &step.id, status).await;
        }
    }

    // Get the execution state
    let execution = runner.get_execution(&exec_id).await?;

    // Emit event with terminal session info
    // Emit event immediately so frontend can show the skill info
    let _ = app.emit(
        "skill:interactive_started",
        serde_json::json!({
            "execution_id": exec_id,
            "terminal_id": term_id,
            "skill_name": skill.name,
            "host_id": effective_host_id,
            "steps": execution.steps.iter().map(|s| serde_json::json!({
                "step_id": s.step_id,
                "name": s.name,
                "status": s.status,
            })).collect::<Vec<_>>(),
        }),
    );

    if auto_start {
        // Spawn background task to run the skill
        let exec_id_clone = exec_id.clone();
        let term_id_clone = term_id.clone();
        let app_clone = app.clone();

        tokio::spawn(async move {
            if let Err(e) = run_interactive_skill(
                app_clone,
                exec_id_clone,
                term_id_clone,
                skill,
                merged_variables,
            )
            .await
            {
                eprintln!("[interactive_skill] Error running skill: {:?}", e);
            }
        });
    } else {
        let log_lock = tokio::sync::Mutex::new(());
        append_skill_log(
            &app,
            &log_lock,
            &exec_id,
            None,
            run_logs::SkillLogStream::System,
            "Prepared. Waiting for manual start.".to_string(),
        )
        .await;
    }

    Ok(execution)
}

/// Background task to run an interactive skill
async fn run_interactive_skill(
    app: tauri::AppHandle,
    exec_id: String,
    term_id: String,
    skill: Skill,
    variables: HashMap<String, String>,
) -> Result<(), AppError> {
    use std::collections::{HashMap, HashSet};
    use tauri::Emitter;
    use tauri::Manager;

    let mut variables = variables;

    let term_mgr = app.state::<crate::terminal::TerminalManager>();
    let log_lock = Arc::new(tokio::sync::Mutex::new(()));
    append_skill_log(
        &app,
        log_lock.as_ref(),
        &exec_id,
        None,
        run_logs::SkillLogStream::System,
        format!("Execution started: {}", skill.name),
    )
    .await;

    let mut control_rx = interactive::get_runner()
        .await
        .take_control_receiver(&exec_id)
        .await?;

    let step_order = execution::compute_execution_order(&skill.steps)?;
    let step_index: HashMap<String, usize> = skill
        .steps
        .iter()
        .enumerate()
        .map(|(index, step)| (step.id.clone(), index))
        .collect();
    let step_map: HashMap<String, Step> = skill
        .steps
        .iter()
        .cloned()
        .map(|step| (step.id.clone(), step))
        .collect();

    let exec_snapshot = interactive::get_runner()
        .await
        .get_execution(&exec_id)
        .await?;
    let mut completed: HashSet<String> = HashSet::new();
    for step_state in &exec_snapshot.steps {
        match step_state.status {
            StepStatus::Success | StepStatus::Skipped => {
                completed.insert(step_state.step_id.clone());
            }
            StepStatus::Failed => {
                if let Some(step_def) = step_map.get(&step_state.step_id) {
                    if step_def.continue_on_failure {
                        completed.insert(step_state.step_id.clone());
                    }
                }
            }
            _ => {}
        }
    }

    for step in &skill.steps {
        if completed.contains(&step.id) {
            continue;
        }
        let status = if step.depends_on.iter().all(|dep| completed.contains(dep)) {
            StepStatus::Pending
        } else {
            StepStatus::Waiting
        };
        let _ = interactive::get_runner()
            .await
            .update_step_status(&exec_id, &step.id, status)
            .await;
    }

    interactive::get_runner()
        .await
        .update_status(&exec_id, interactive::InteractiveStatus::Running)
        .await?;

    let _ = app.emit(
        "skill:execution_updated",
        serde_json::json!({
            "execution_id": exec_id,
            "status": "running",
        }),
    );

    tokio::time::sleep(tokio::time::Duration::from_millis(300)).await;

    eprintln!("[interactive_skill] Starting execution {}", exec_id);

    const BEGIN_MARKER: &str = "___DOPPIO_BEGIN___";
    const DONE_MARKER: &str = "___DOPPIO_DONE___";
    let mut control_state = ControlState::default();

    for step_id in step_order {
        if completed.contains(&step_id) {
            continue;
        }

        drain_control_signals(&app, &exec_id, &mut control_rx, &mut control_state).await?;
        wait_if_paused(&app, &exec_id, &mut control_rx, &mut control_state).await?;
        if control_state.cancel_requested {
            let _ = crate::terminal::term_write_inner(&term_mgr, &term_id, "\x03").await;
            interactive::get_runner()
                .await
                .set_current_step(&exec_id, None)
                .await?;
            return Ok(());
        }

        if control_state.skip_steps.remove(&step_id) {
            interactive::get_runner()
                .await
                .update_step_status(&exec_id, &step_id, StepStatus::Skipped)
                .await?;
            let _ = app.emit(
                "skill:step_skipped",
                serde_json::json!({
                    "execution_id": exec_id,
                    "step_id": step_id,
                }),
            );
            append_skill_log(
                &app,
                log_lock.as_ref(),
                &exec_id,
                Some(&step_id),
                run_logs::SkillLogStream::System,
                "Step skipped".to_string(),
            )
            .await;
            completed.insert(step_id.clone());
            continue;
        }

        let step = match step_map.get(&step_id) {
            Some(step) => step.clone(),
            None => continue,
        };
        let step_index = *step_index.get(&step_id).unwrap_or(&0);

        if let Some(condition) = &step.condition {
            let cond_value = parser::interpolate(condition, &variables);
            if cond_value != "true" && cond_value != "1" {
                interactive::get_runner()
                    .await
                    .update_step_status(&exec_id, &step.id, StepStatus::Skipped)
                    .await?;
                let _ = app.emit(
                    "skill:step_skipped",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step.id,
                    }),
                );
                completed.insert(step.id.clone());
                continue;
            }
        }

        interactive::get_runner()
            .await
            .set_current_step(&exec_id, Some(step.id.clone()))
            .await?;
        interactive::get_runner()
            .await
            .update_step_status(&exec_id, &step.id, StepStatus::Running)
            .await?;
        if let Err(e) =
            crate::terminal::history_step_start(&term_mgr, &term_id, &step.id, step_index).await
        {
            eprintln!("[interactive_skill] history step start failed: {}", e);
        }

        let _ = app.emit(
            "skill:step_started",
            serde_json::json!({
                "execution_id": exec_id,
                "step_id": step.id,
                "step_index": step_index,
            }),
        );

        let max_attempts = step.retry.as_ref().map(|r| r.max_attempts).unwrap_or(1);
        let mut delay_secs = step.retry.as_ref().map(|r| r.delay_secs).unwrap_or(5);
        let backoff = step
            .retry
            .as_ref()
            .and_then(|r| r.backoff_multiplier)
            .unwrap_or(1.0);

        let mut attempt = 0;
        let mut step_failed = false;
        let mut step_exit_code: Option<i32> = None;
        let mut last_error: Option<String> = None;

        loop {
            attempt += 1;

            if attempt > 1 {
                interactive::get_runner()
                    .await
                    .update_step_status(&exec_id, &step.id, StepStatus::Retrying)
                    .await?;
                let _ = app.emit(
                    "skill:step_retrying",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step.id,
                        "attempt": attempt,
                    }),
                );
                tokio::time::sleep(tokio::time::Duration::from_secs(delay_secs)).await;
                delay_secs = (delay_secs as f64 * backoff) as u64;
            }

            let commands = extract_commands_from_step(&step, &variables);
            eprintln!(
                "[interactive_skill] Step {} operation {:?} => commands: {:?}",
                step.id,
                std::mem::discriminant(&step.operation),
                commands.as_ref().map(|s| s.len())
            );

            if let Some(cmds) = commands {
                eprintln!("[interactive_skill] Using TERMINAL execution for step {}", step.id);
                interactive::get_runner()
                    .await
                    .lock_intervention(&exec_id)
                    .await?;
                let _ = app.emit(
                    "skill:intervention_lock_changed",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "terminal_id": term_id,
                        "locked": true,
                    }),
                );

                let _ = app.emit(
                    "skill:command_sending",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step.id,
                    }),
                );
                append_skill_log(
                    &app,
                    log_lock.as_ref(),
                    &exec_id,
                    Some(&step.id),
                    run_logs::SkillLogStream::System,
                    "Sending commands to terminal…".to_string(),
                )
                .await;

                if let types::Operation::RunCommands(op) = &step.operation {
                    let preview = interpolate_for_log(&op.commands, &variables);
                    if !preview.trim().is_empty() {
                        append_skill_log(
                            &app,
                            log_lock.as_ref(),
                            &exec_id,
                            Some(&step.id),
                            run_logs::SkillLogStream::System,
                            format!("Commands:\n{}", preview.trim_end()),
                        )
                        .await;
                    }
                }

                let workdir_prefix = match &step.operation {
                    types::Operation::RunCommands(op) => {
                        if let Some(workdir) = &op.workdir {
                            let workdir_interpolated = parser::interpolate(workdir, &variables);
                            if !workdir_interpolated.is_empty() {
                                let escaped = workdir_interpolated.replace('\'', "'\"'\"'");
                                format!("cd '{}'\n", escaped)
                            } else {
                                String::new()
                            }
                        } else {
                            String::new()
                        }
                    }
                    _ => String::new(),
                };

                let start_offset =
                    crate::terminal::history_size_bytes(&term_mgr, &term_id).await.unwrap_or(0);
                let begin_marker_line = format!("{}:{}", BEGIN_MARKER, step.id);
                let done_marker_prefix = format!("{}:", DONE_MARKER);

                let heredoc = format!(
                    "${{SHELL:-bash}} <<'DOPPIO_EOF'\necho '{begin_marker_line}'\ntrap '__doppio_rc__=130; echo {done_marker_prefix}$__doppio_rc__; exit $__doppio_rc__' INT TERM\n{}{}\n__doppio_rc__=$?\necho {done_marker_prefix}$__doppio_rc__\nDOPPIO_EOF\n",
                    workdir_prefix,
                    cmds.trim(),
                );
                let send_result = crate::terminal::term_write_inner(&term_mgr, &term_id, &heredoc).await;

                eprintln!("[interactive_skill] Sent commands for step {}", step.id);

                tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

                interactive::get_runner()
                    .await
                    .unlock_intervention(&exec_id)
                    .await?;
                let _ = app.emit(
                    "skill:intervention_lock_changed",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "terminal_id": term_id,
                        "locked": false,
                    }),
                );

                if let Err(e) = send_result {
                    append_skill_log(
                        &app,
                        log_lock.as_ref(),
                        &exec_id,
                        Some(&step.id),
                        run_logs::SkillLogStream::Stderr,
                        e.to_string(),
                    )
                    .await;
                    step_failed = true;
                    last_error = Some(e.to_string());
                } else {
                    append_skill_log(
                        &app,
                        log_lock.as_ref(),
                        &exec_id,
                        Some(&step.id),
                        run_logs::SkillLogStream::System,
                        "Waiting for command completion…".to_string(),
                    )
                    .await;

                    let timeout = step.timeout_secs.filter(|t| *t > 0).map(std::time::Duration::from_secs);

                    let exec_snapshot = interactive::get_runner().await.get_execution(&exec_id).await?;
                    let host_id_for_logs = exec_snapshot.host_id.clone();
                    let tmux_session_for_logs = exec_snapshot.terminal.tmux_session.clone().unwrap_or_default();

                    let use_tmux_capture = host_id_for_logs != LOCAL_TARGET && !tmux_session_for_logs.trim().is_empty();

                    let mut stream_fut: std::pin::Pin<
                        Box<dyn std::future::Future<Output = Result<i32, AppError>> + Send>,
                    > = if use_tmux_capture {
                        Box::pin(stream_tmux_pane_until_marker(
                            &app,
                            log_lock.as_ref(),
                            &exec_id,
                            &host_id_for_logs,
                            &tmux_session_for_logs,
                            &step.id,
                            &begin_marker_line,
                            &done_marker_prefix,
                            timeout,
                        ))
                    } else {
                        Box::pin(stream_terminal_output_until_marker(
                            &app,
                            &term_mgr,
                            log_lock.as_ref(),
                            &exec_id,
                            &term_id,
                            &step.id,
                            &begin_marker_line,
                            &done_marker_prefix,
                            start_offset,
                            timeout,
                        ))
                    };

                    let result = loop {
                        tokio::select! {
                            res = &mut stream_fut => break res,
                            signal = control_rx.recv() => {
                                if let Some(signal) = signal {
                                    apply_control_signal(&app, &exec_id, signal, &mut control_state).await?;
                                    if control_state.cancel_requested {
                                        let _ = crate::terminal::term_write_inner(&term_mgr, &term_id, "\x03").await;
                                        interactive::get_runner()
                                            .await
                                            .set_current_step(&exec_id, None)
                                            .await?;
                                        return Ok(());
                                    }
                                } else {
                                    break Err(AppError::command("Control channel closed"));
                                }
                            }
                        }
                    };

                    match result {
                        Ok(exit_code) => {
                            step_exit_code = Some(exit_code);
                            eprintln!(
                                "[interactive_skill] Step {} exit_code: {}",
                                step.id, exit_code
                            );

                            if exit_code != 0 {
                                append_skill_log(
                                    &app,
                                    log_lock.as_ref(),
                                    &exec_id,
                                    Some(&step.id),
                                    run_logs::SkillLogStream::Stderr,
                                    format!("Step failed (exit code {exit_code})"),
                                )
                                .await;
                                step_failed = true;
                                last_error = Some(format!(
                                    "Step {} failed with exit code {}",
                                    step.id, exit_code
                                ));
                            } else {
                                step_failed = false;
                                last_error = None;
                            }
                        }
                        Err(e) => {
                            append_skill_log(
                                &app,
                                log_lock.as_ref(),
                                &exec_id,
                                Some(&step.id),
                                run_logs::SkillLogStream::Stderr,
                                e.to_string(),
                            )
                            .await;
                            step_failed = true;
                            last_error = Some(e.to_string());
                        }
                    }
                }

                interactive::get_runner()
                    .await
                    .update_status(&exec_id, interactive::InteractiveStatus::Running)
                    .await?;
            } else {
                eprintln!(
                    "[interactive_skill] Using STREAMING execution for step {} operation: {:?}",
                    step.id,
                    step.operation
                );

                let op_desc = get_operation_description(&step.operation, &variables);
                append_skill_log(
                    &app,
                    log_lock.as_ref(),
                    &exec_id,
                    Some(&step.id),
                    run_logs::SkillLogStream::System,
                    op_desc.clone(),
                )
                .await;

                // Check if this is a RunCommands or SshCommand that should use streaming execution
                let is_streaming_op = matches!(
                    &step.operation,
                    types::Operation::RunCommands(_) | types::Operation::SshCommand(_)
                );

                if is_streaming_op {
                    // Use streaming execution for RunCommands and SshCommand
                    let (command, workdir, target, is_local) = match &step.operation {
                        types::Operation::RunCommands(op) => {
                            let target = op
                                .host_id
                                .as_ref()
                                .map(|h| parser::interpolate(h, &variables))
                                .or_else(|| variables.get("target").cloned())
                                .unwrap_or_else(|| LOCAL_TARGET.to_string());
                            let is_local = target == LOCAL_TARGET;
                            let command = parser::interpolate(&op.commands, &variables);
                            let workdir = op.workdir.as_ref().map(|w| parser::interpolate(w, &variables));
                            (command, workdir, target, is_local)
                        }
                        types::Operation::SshCommand(op) => {
                            let target = parser::interpolate(&op.host_id, &variables);
                            let is_local = target == LOCAL_TARGET;
                            let command = parser::interpolate(&op.command, &variables);
                            let workdir = op.workdir.as_ref().map(|w| parser::interpolate(w, &variables));
                            (command, workdir, target, is_local)
                        }
                        _ => unreachable!(),
                    };

                    if let types::Operation::RunCommands(op) = &step.operation {
                        let preview = interpolate_for_log(&op.commands, &variables);
                        if !preview.trim().is_empty() {
                            append_skill_log(
                                &app,
                                log_lock.as_ref(),
                                &exec_id,
                                Some(&step.id),
                                run_logs::SkillLogStream::System,
                                format!("Commands:\n{}", preview.trim_end()),
                            )
                            .await;
                        }
                    }

                    let timeout = step.timeout_secs.filter(|t| *t > 0).map(std::time::Duration::from_secs);

                    let result = execute_streaming_command(
                        &app,
                        log_lock.as_ref(),
                        &exec_id,
                        &step.id,
                        &command,
                        workdir.as_deref(),
                        is_local,
                        &target,
                        &mut control_rx,
                        &mut control_state,
                        timeout,
                    )
                    .await;

                    match result {
                        Ok(exit_code) => {
                            step_exit_code = Some(exit_code);
                            if exit_code != 0 {
                                append_skill_log(
                                    &app,
                                    log_lock.as_ref(),
                                    &exec_id,
                                    Some(&step.id),
                                    run_logs::SkillLogStream::Stderr,
                                    format!("Command failed (exit code {exit_code})"),
                                )
                                .await;
                                step_failed = true;
                                last_error = Some(format!(
                                    "Step {} failed with exit code {}",
                                    step.id, exit_code
                                ));
                            } else {
                                step_failed = false;
                                last_error = None;
                            }
                        }
                        Err(e) => {
                            append_skill_log(
                                &app,
                                log_lock.as_ref(),
                                &exec_id,
                                Some(&step.id),
                                run_logs::SkillLogStream::Stderr,
                                e.to_string(),
                            )
                            .await;
                            step_failed = true;
                            last_error = Some(e.to_string());
                        }
                    }
                } else {
                    // Use the standard execute_step for other operations
                    let exec_id_clone = exec_id.clone();
                let step_id_clone = step.id.clone();
                let app_handle = app.clone();
                let log_lock_for_progress = log_lock.clone();
                let progress_cb: Arc<dyn Fn(&str) + Send + Sync> = Arc::new(move |msg: &str| {
                    let exec_id = exec_id_clone.clone();
                    let step_id = step_id_clone.clone();
                    let app_handle_inner = app_handle.clone();
                    let log_lock = log_lock_for_progress.clone();
                    let message = msg.to_string();
                    tauri::async_runtime::spawn(async move {
                        let runner = interactive::get_runner().await;
                        let _ = runner
                            .set_step_progress(&exec_id, &step_id, Some(message.clone()))
                            .await;
                        let _ = app_handle_inner.emit(
                            "skill:step_progress",
                            serde_json::json!({
                                "execution_id": exec_id,
                                "step_id": step_id,
                                "progress": message,
                            }),
                        );
                        append_skill_log(
                            &app_handle_inner,
                            log_lock.as_ref(),
                            &exec_id,
                            Some(&step_id),
                            run_logs::SkillLogStream::Progress,
                            message,
                        )
                        .await;
                    });
                });
                progress_cb(&op_desc.lines().next().unwrap_or(&op_desc));

                let mut op_fut = Box::pin(execution::execute_step(
                    &step.operation,
                    &variables,
                    Some(progress_cb.clone()),
                ));

                let result = loop {
                    tokio::select! {
                        res = &mut op_fut => break res,
                        signal = control_rx.recv() => {
                            if let Some(signal) = signal {
                                apply_control_signal(&app, &exec_id, signal, &mut control_state).await?;
                                if control_state.cancel_requested {
                                    interactive::get_runner()
                                        .await
                                        .set_current_step(&exec_id, None)
                                        .await?;
                                    return Ok(());
                                }
                            } else {
                                break Err(AppError::command("Control channel closed"));
                            }
                        }
                    }
                };

                match result {
                    Ok(Some(output)) => {
                        let (stdout, stderr) = split_command_output(&output);
                        if let Some(out) = stdout {
                            append_skill_log(
                                &app,
                                log_lock.as_ref(),
                                &exec_id,
                                Some(&step.id),
                                run_logs::SkillLogStream::Stdout,
                                out,
                            )
                            .await;
                        }
                        if let Some(err) = stderr {
                            append_skill_log(
                                &app,
                                log_lock.as_ref(),
                                &exec_id,
                                Some(&step.id),
                                run_logs::SkillLogStream::Stderr,
                                err,
                            )
                            .await;
                        }
                        step_failed = false;
                        last_error = None;
                    }
                    Ok(None) => {
                        step_failed = false;
                        last_error = None;
                    }
                    Err(e) => {
                        append_skill_log(
                            &app,
                            log_lock.as_ref(),
                            &exec_id,
                            Some(&step.id),
                            run_logs::SkillLogStream::Stderr,
                            e.to_string(),
                        )
                        .await;
                        step_failed = true;
                        last_error = Some(e.to_string());
                    }
                }

                let exec_id_clone = exec_id.clone();
                let step_id_clone = step.id.clone();
                let app_handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    let runner = interactive::get_runner().await;
                    let _ = runner
                        .set_step_progress(&exec_id_clone, &step_id_clone, None)
                        .await;
                    let _ = app_handle.emit(
                        "skill:step_progress",
                        serde_json::json!({
                            "execution_id": exec_id_clone,
                            "step_id": step_id_clone,
                            "progress": serde_json::Value::Null,
                        }),
                    );
                });
                } // Close the else branch for non-streaming ops
            }

            if step_failed && attempt < max_attempts {
                append_skill_log(
                    &app,
                    log_lock.as_ref(),
                    &exec_id,
                    Some(&step.id),
                    run_logs::SkillLogStream::System,
                    format!("Retrying in {delay_secs}s (attempt {attempt}/{max_attempts})"),
                )
                .await;
                continue;
            }
            break;
        }

        if step_failed {
            let error_msg = last_error.unwrap_or_else(|| "Step failed".to_string());
            interactive::get_runner()
                .await
                .update_step_status(&exec_id, &step.id, StepStatus::Failed)
                .await?;
            let _ = app.emit(
                "skill:step_failed",
                serde_json::json!({
                    "execution_id": exec_id,
                    "step_id": step.id,
                    "error": error_msg,
                }),
            );

            if !step.continue_on_failure {
                interactive::get_runner()
                    .await
                    .update_status(&exec_id, interactive::InteractiveStatus::Failed)
                    .await?;
                let _ = app.emit(
                    "skill:execution_failed",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "error": error_msg,
                    }),
                );
                append_skill_log(
                    &app,
                    log_lock.as_ref(),
                    &exec_id,
                    None,
                    run_logs::SkillLogStream::Stderr,
                    format!("Execution failed: {error_msg}"),
                )
                .await;
                let _ = crate::terminal::history_step_end(
                    &term_mgr,
                    &term_id,
                    &step.id,
                    step_index,
                    "failed",
                    step_exit_code,
                )
                .await;
                return Err(AppError::command(error_msg));
            }
        } else {
            if matches!(step.operation, types::Operation::VastStart(_))
                && variables
                    .get("_doppio_connect_after_vast_start")
                    .is_some_and(|v| v == "1")
            {
                use std::time::Duration;

                let target = variables
                    .get("target")
                    .cloned()
                    .ok_or_else(|| AppError::invalid_input("Missing skill variable: target"))?;
                let tmux_session = variables
                    .get("_doppio_connect_tmux_session")
                    .cloned()
                    .ok_or_else(|| {
                        AppError::invalid_input(
                            "Missing skill variable: _doppio_connect_tmux_session",
                        )
                    })?;

                append_skill_log(
                    &app,
                    log_lock.as_ref(),
                    &exec_id,
                    Some(&step.id),
                    run_logs::SkillLogStream::System,
                    "Connecting terminal to Vast SSH…".to_string(),
                )
                .await;

                let ssh =
                    crate::host::resolve_ssh_spec_with_retry(&target, Duration::from_secs(300))
                        .await?;

                let remote_cmd = format!(
                    "tmux start-server; tmux set-option -g history-limit 200000; tmux set-option -t {} history-limit 200000 2>/dev/null; tmux new-session -A -s {}",
                    tmux_session,
                    tmux_session
                );

                fn sh_quote(s: &str) -> String {
                    format!("'{}'", s.replace('\'', "'\"'\"'"))
                }

                let mut line = String::from("exec ssh");
                for opt in ssh.interactive_ssh_options() {
                    line.push(' ');
                    line.push_str(&sh_quote(&opt));
                }
                line.push_str(" -tt ");
                line.push_str(&sh_quote(&ssh.target()));
                line.push(' ');
                line.push_str(&sh_quote(&remote_cmd));
                line.push('\n');

                crate::terminal::term_write_inner(&term_mgr, &term_id, &line).await?;

                variables.remove("_doppio_connect_after_vast_start");
                variables.remove("_doppio_connect_tmux_session");

                tokio::time::sleep(tokio::time::Duration::from_millis(800)).await;
            }

            interactive::get_runner()
                .await
                .update_step_status(&exec_id, &step.id, StepStatus::Success)
                .await?;
            eprintln!("[interactive_skill] Step {} completed", step.id);
            let _ = app.emit(
                "skill:step_completed",
                serde_json::json!({
                    "execution_id": exec_id,
                    "step_id": step.id,
                }),
            );
            append_skill_log(
                &app,
                log_lock.as_ref(),
                &exec_id,
                Some(&step.id),
                run_logs::SkillLogStream::System,
                "Step completed".to_string(),
            )
            .await;
        }

        let status = if step_failed { "failed" } else { "success" };
        if let Err(e) = crate::terminal::history_step_end(
            &term_mgr,
            &term_id,
            &step.id,
            step_index,
            status,
            step_exit_code,
        )
        .await
        {
            eprintln!("[interactive_skill] history step end failed: {}", e);
        }

        if !step_failed || step.continue_on_failure {
            completed.insert(step.id.clone());
        }

        drain_control_signals(&app, &exec_id, &mut control_rx, &mut control_state).await?;
        wait_if_paused(&app, &exec_id, &mut control_rx, &mut control_state).await?;
        if control_state.cancel_requested {
            let _ = crate::terminal::term_write_inner(&term_mgr, &term_id, "\x03").await;
            interactive::get_runner()
                .await
                .set_current_step(&exec_id, None)
                .await?;
            return Ok(());
        }
    }

    interactive::get_runner()
        .await
        .set_current_step(&exec_id, None)
        .await?;

    if !control_state.cancel_requested {
        interactive::get_runner()
            .await
            .update_status(&exec_id, interactive::InteractiveStatus::Completed)
            .await?;
        let _ = app.emit(
            "skill:execution_completed",
            serde_json::json!({
                "execution_id": exec_id,
            }),
        );
        append_skill_log(
            &app,
            log_lock.as_ref(),
            &exec_id,
            None,
            run_logs::SkillLogStream::System,
            "Execution completed".to_string(),
        )
        .await;
    }

    Ok(())
}

#[derive(Default)]
struct ControlState {
    paused: bool,
    pause_requested: bool,
    cancel_requested: bool,
    skip_steps: std::collections::HashSet<String>,
    /// Pending user input for interactive commands
    pending_input: Option<String>,
}

async fn apply_control_signal(
    app: &tauri::AppHandle,
    exec_id: &str,
    signal: interactive::InteractiveControl,
    state: &mut ControlState,
) -> Result<(), AppError> {
    match signal {
        interactive::InteractiveControl::Pause => {
            state.pause_requested = true;
        }
        interactive::InteractiveControl::Resume => {
            state.paused = false;
            state.pause_requested = false;
            interactive::get_runner()
                .await
                .update_status(exec_id, interactive::InteractiveStatus::Running)
                .await?;
            let _ = app.emit(
                "skill:execution_updated",
                serde_json::json!({
                    "execution_id": exec_id,
                    "status": "running",
                }),
            );
        }
        interactive::InteractiveControl::Cancel => {
            state.cancel_requested = true;
            state.paused = false;
            state.pause_requested = false;
            interactive::get_runner()
                .await
                .update_status(exec_id, interactive::InteractiveStatus::Cancelled)
                .await?;
            let _ = app.emit(
                "skill:execution_updated",
                serde_json::json!({
                    "execution_id": exec_id,
                    "status": "cancelled",
                }),
            );
            let _ = app.emit(
                "skill:execution_cancelled",
                serde_json::json!({
                    "execution_id": exec_id,
                }),
            );
        }
        interactive::InteractiveControl::SkipStep(step_id) => {
            let step_id = step_id.trim().to_string();
            if !step_id.is_empty() {
                state.skip_steps.insert(step_id);
            }
        }
        interactive::InteractiveControl::SendInput(input) => {
            state.pending_input = Some(input);
        }
        _ => {}
    }
    Ok(())
}

async fn drain_control_signals(
    app: &tauri::AppHandle,
    exec_id: &str,
    control_rx: &mut tokio::sync::mpsc::Receiver<interactive::InteractiveControl>,
    state: &mut ControlState,
) -> Result<(), AppError> {
    while let Ok(signal) = control_rx.try_recv() {
        apply_control_signal(app, exec_id, signal, state).await?;
    }
    Ok(())
}

async fn wait_if_paused(
    app: &tauri::AppHandle,
    exec_id: &str,
    control_rx: &mut tokio::sync::mpsc::Receiver<interactive::InteractiveControl>,
    state: &mut ControlState,
) -> Result<(), AppError> {
    if state.pause_requested && !state.paused {
        state.paused = true;
        state.pause_requested = false;
        interactive::get_runner()
            .await
            .update_status(exec_id, interactive::InteractiveStatus::Paused)
            .await?;
        let _ = app.emit(
            "skill:execution_updated",
            serde_json::json!({
                "execution_id": exec_id,
                "status": "paused",
            }),
        );
    }

    while state.paused && !state.cancel_requested {
        if let Some(signal) = control_rx.recv().await {
            apply_control_signal(app, exec_id, signal, state).await?;
        } else {
            break;
        }
    }

    Ok(())
}

/// Execute a command using the streaming executor with interactive input support
async fn execute_streaming_command(
    app: &tauri::AppHandle,
    log_lock: &tokio::sync::Mutex<()>,
    exec_id: &str,
    step_id: &str,
    command: &str,
    workdir: Option<&str>,
    is_local: bool,
    host_id: &str,
    control_rx: &mut tokio::sync::mpsc::Receiver<interactive::InteractiveControl>,
    control_state: &mut ControlState,
    timeout: Option<std::time::Duration>,
) -> Result<i32, AppError> {
    use stream_exec::StreamEvent;

    let env = HashMap::new();

    // Start the streaming execution
    let mut execution = if is_local {
        stream_exec::execute_streaming(command, workdir, &env, None).await?
    } else {
        stream_exec::execute_streaming_ssh(host_id, command, workdir, &env).await?
    };

    let start_time = std::time::Instant::now();

    loop {
        // Check for timeout
        if let Some(timeout) = timeout {
            if start_time.elapsed() > timeout {
                execution.cancel();
                return Err(AppError::command(format!(
                    "Command timed out after {}s",
                    timeout.as_secs()
                )));
            }
        }

        tokio::select! {
            // Handle stream events
            event = execution.events_rx.recv() => {
                match event {
                    Some(StreamEvent::Output { data }) => {
                        // PTY output is combined stdout/stderr, log as stdout
                        append_skill_log(
                            app,
                            log_lock,
                            exec_id,
                            Some(step_id),
                            run_logs::SkillLogStream::Stdout,
                            data,
                        )
                        .await;
                    }
                    Some(StreamEvent::InputNeeded { prompt }) => {
                        // Detect if this is a password prompt
                        let is_password = prompt.to_lowercase().contains("password")
                            || prompt.to_lowercase().contains("passphrase");

                        eprintln!(
                            "[execute_streaming_command] InputNeeded detected: prompt={:?}, is_password={}",
                            prompt, is_password
                        );

                        // Update execution status to waiting_for_input
                        let runner = interactive::get_runner().await;
                        if let Err(e) = runner.set_pending_input(exec_id, step_id, &prompt).await {
                            eprintln!("[execute_streaming_command] Failed to set pending input: {e}");
                        }

                        // Emit event with pending_input for optimistic frontend update
                        let payload = serde_json::json!({
                            "execution_id": exec_id,
                            "status": "waiting_for_input",
                            "pending_input": {
                                "step_id": step_id,
                                "prompt": prompt,
                                "is_password": is_password,
                            },
                        });
                        eprintln!("[execute_streaming_command] Emitting skill:execution_updated: {}", payload);
                        let _ = app.emit("skill:execution_updated", payload);
                        append_skill_log(
                            app,
                            log_lock,
                            exec_id,
                            Some(step_id),
                            run_logs::SkillLogStream::System,
                            format!("Waiting for input: {}", prompt),
                        )
                        .await;
                    }
                    Some(StreamEvent::Exited { code }) => {
                        // Clear pending input state
                        let runner = interactive::get_runner().await;
                        if let Err(e) = runner.clear_pending_input(exec_id).await {
                            eprintln!("[execute_streaming_command] Failed to clear pending input: {e}");
                        }
                        let _ = app.emit(
                            "skill:execution_updated",
                            serde_json::json!({
                                "execution_id": exec_id,
                                "status": "running",
                            }),
                        );
                        return Ok(code.unwrap_or(0));
                    }
                    None => {
                        // Channel closed, process must have exited
                        return Ok(0);
                    }
                }
            }

            // Handle control signals
            signal = control_rx.recv() => {
                if let Some(signal) = signal {
                    // Check if it's a SendInput signal before applying
                    if let interactive::InteractiveControl::SendInput(input) = &signal {
                        // Send input directly to the process
                        if let Err(e) = execution.input_handle.send(input.clone()).await {
                            append_skill_log(
                                app,
                                log_lock,
                                exec_id,
                                Some(step_id),
                                run_logs::SkillLogStream::Stderr,
                                format!("Failed to send input: {}", e),
                            )
                            .await;
                        }
                        // Clear pending input state
                        let runner = interactive::get_runner().await;
                        if let Err(e) = runner.clear_pending_input(exec_id).await {
                            eprintln!("[execute_streaming_command] Failed to clear pending input: {e}");
                        }
                        let _ = app.emit(
                            "skill:execution_updated",
                            serde_json::json!({
                                "execution_id": exec_id,
                                "status": "running",
                            }),
                        );
                    } else {
                        apply_control_signal(app, exec_id, signal, control_state).await?;
                        if control_state.cancel_requested {
                            execution.cancel();
                            return Err(AppError::command("Execution cancelled"));
                        }
                    }
                } else {
                    return Err(AppError::command("Control channel closed"));
                }
            }
        }
    }
}

async fn open_terminal_for_resume(
    app: tauri::AppHandle,
    term_mgr: &crate::terminal::TerminalManager,
    exec: &interactive::InteractiveExecution,
    skill: &Skill,
) -> Result<
    (
        crate::terminal::TermSessionInfo,
        interactive::InteractiveTerminal,
    ),
    AppError,
> {
    use crate::host::{default_env_vars, get_host, HostType};

    let cols = exec.terminal.cols;
    let rows = exec.terminal.rows;
    let title = if exec.terminal.title.trim().is_empty() {
        format!("Skill: {}", exec.skill_name)
    } else {
        exec.terminal.title.clone()
    };

    if exec.host_id == LOCAL_TARGET {
        let info = crate::terminal::open_local_inner(
            app.clone(),
            term_mgr,
            Some(title.clone()),
            cols,
            rows,
        )
        .await?;
        let terminal = interactive::InteractiveTerminal {
            title,
            tmux_session: None,
            cols,
            rows,
        };
        return Ok((info, terminal));
    }

    let tmux_session = exec
        .terminal
        .tmux_session
        .clone()
        .ok_or_else(|| AppError::invalid_input("Missing tmux_session for resume"))?;

    let mut step_status = std::collections::HashMap::new();
    for step in &exec.steps {
        step_status.insert(step.step_id.clone(), step.status.clone());
    }

    let needs_vast_start = skill.steps.iter().any(|step| {
        matches!(step.operation, types::Operation::VastStart(_))
            && step_status
                .get(&step.id)
                .map(|s| *s != StepStatus::Success)
                .unwrap_or(true)
    });

    if exec.host_id.starts_with("vast:") && needs_vast_start {
        let info = crate::terminal::open_local_inner(
            app.clone(),
            term_mgr,
            Some(title.clone()),
            cols,
            rows,
        )
        .await?;
        let terminal = interactive::InteractiveTerminal {
            title,
            tmux_session: Some(tmux_session),
            cols,
            rows,
        };
        return Ok((info, terminal));
    }

    if exec.host_id.starts_with("vast:") {
        let ssh = crate::host::resolve_ssh_spec_with_retry(
            &exec.host_id,
            std::time::Duration::from_secs(300),
        )
        .await?;
        let info = crate::terminal::open_ssh_tmux_inner_static(
            app.clone(),
            term_mgr,
            ssh,
            tmux_session.clone(),
            Some(title.clone()),
            cols,
            rows,
            Some(default_env_vars(&HostType::Vast)),
        )
        .await?;
        let terminal = interactive::InteractiveTerminal {
            title,
            tmux_session: Some(tmux_session),
            cols,
            rows,
        };
        return Ok((info, terminal));
    }

    let host = get_host(&exec.host_id).await?;
    let ssh = host
        .ssh
        .as_ref()
        .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
    let info = crate::terminal::open_ssh_tmux_inner_static(
        app.clone(),
        term_mgr,
        ssh.clone(),
        tmux_session.clone(),
        Some(title.clone()),
        cols,
        rows,
        Some(default_env_vars(&host.host_type)),
    )
    .await?;
    let terminal = interactive::InteractiveTerminal {
        title,
        tmux_session: Some(tmux_session),
        cols,
        rows,
    };
    Ok((info, terminal))
}

/// Extract commands from a step's operation
/// Returns Some(commands) if the operation can be executed as terminal commands
/// Returns None if the operation must be executed via Rust backend (streaming executor)
fn extract_commands_from_step(
    step: &types::Step,
    variables: &HashMap<String, String>,
) -> Option<String> {
    match &step.operation {
        // RunCommands and SshCommand now use the streaming executor (backend)
        // This allows capturing output to sidebar and supporting interactive input
        types::Operation::RunCommands(_) => None,
        types::Operation::SshCommand(_) => None,
        types::Operation::GitClone(op) => {
            let repo = parser::interpolate(&op.repo_url, variables);
            let dest = parser::interpolate(&op.destination, variables);

            // If auth_token is provided, use backend execution for security
            if op
                .auth_token
                .as_ref()
                .map(|t| !parser::interpolate(t, variables).is_empty())
                .unwrap_or(false)
            {
                return None;
            }

            // SSH clone needs the local configured private key, which must be provisioned via backend.
            let repo_trimmed = repo.trim();
            if repo_trimmed.starts_with("git@")
                || repo_trimmed.starts_with("ssh://")
                || repo_trimmed.starts_with("git+ssh://")
                || repo_trimmed.starts_with("ssh+git://")
            {
                return None;
            }

            let mut parts: Vec<String> = vec!["git".to_string(), "clone".to_string()];
            if let Some(b) = &op.branch {
                let branch = parser::interpolate(b, variables);
                if !branch.trim().is_empty() {
                    parts.push("-b".to_string());
                    parts.push(branch);
                }
            }
            if let Some(d) = op.depth {
                parts.push("--depth".to_string());
                parts.push(d.to_string());
            }
            parts.push(repo);
            parts.push(dest);
            Some(parts.join(" "))
        }
        types::Operation::HfDownload(op) => {
            let repo_id = parser::interpolate(&op.repo_id, variables);
            let dest = parser::interpolate(&op.destination, variables);
            let repo_type = match op.repo_type {
                types::HfRepoType::Model => "model",
                types::HfRepoType::Dataset => "dataset",
                types::HfRepoType::Space => "space",
            };

            let mut cmd = format!(
                "huggingface-cli download {} --local-dir {} --repo-type {}",
                repo_id, dest, repo_type
            );

            if let Some(revision) = &op.revision {
                cmd.push_str(&format!(
                    " --revision {}",
                    parser::interpolate(revision, variables)
                ));
            }

            for file in &op.files {
                cmd.push_str(&format!(" --include {}", file));
            }

            // If auth token is set, prepend HF_TOKEN env var
            if let Some(token) = &op.auth_token {
                let token_val = parser::interpolate(token, variables);
                if !token_val.is_empty() {
                    cmd = format!("HF_TOKEN='{}' {}", token_val, cmd);
                }
            }

            Some(cmd)
        }
        types::Operation::TmuxNew(op) => {
            let session = parser::interpolate(&op.session_name, variables);
            if let Some(cmd) = &op.command {
                Some(format!(
                    "tmux new-session -d -s {} '{}'",
                    session,
                    parser::interpolate(cmd, variables)
                ))
            } else {
                Some(format!("tmux new-session -d -s {}", session))
            }
        }
        types::Operation::TmuxSend(op) => {
            let session = parser::interpolate(&op.session_name, variables);
            let keys = parser::interpolate(&op.keys, variables);
            Some(format!("tmux send-keys -t {} '{}' Enter", session, keys))
        }
        types::Operation::TmuxKill(op) => {
            let session = parser::interpolate(&op.session_name, variables);
            Some(format!("tmux kill-session -t {}", session))
        }
        types::Operation::TmuxCapture(op) => {
            let session = parser::interpolate(&op.session_name, variables);
            let lines = op.lines.unwrap_or(100);
            Some(format!("tmux capture-pane -t {} -p -S -{}", session, lines))
        }
        types::Operation::Sleep(op) => Some(format!("sleep {}", op.duration_secs)),
        types::Operation::Notify(op) => {
            let msg = op
                .message
                .as_ref()
                .map(|m| parser::interpolate(m, variables))
                .unwrap_or_default();
            let level_str = format!("{:?}", op.level).to_lowercase();
            Some(format!(
                "echo '[{}] {}: {}'",
                level_str,
                parser::interpolate(&op.title, variables),
                msg
            ))
        }
        // Operations that must use backend execution:
        // GdriveMount/Unmount, Transfer, RsyncUpload/Download, VastStart/Stop/Destroy,
        // WaitCondition, HttpRequest, SetVar, GetValue, Assert, Group
        _ => None,
    }
}

/// Get a human-readable description of an operation for display
fn get_operation_description(
    operation: &types::Operation,
    variables: &HashMap<String, String>,
) -> String {
    match operation {
        types::Operation::GdriveMount(op) => {
            let mount_path = if op.mount_path.is_empty() {
                "/content/drive/MyDrive".to_string()
            } else {
                parser::interpolate(&op.mount_path, variables)
            };
            format!(
                "Mounting Google Drive at {}\n→ Installing rclone if needed\n→ Configuring OAuth credentials\n→ Starting rclone mount\n→ Verifying mount",
                mount_path
            )
        }
        types::Operation::GdriveUnmount(op) => {
            format!(
                "Unmounting Google Drive from {}",
                parser::interpolate(&op.mount_path, variables)
            )
        }
        types::Operation::Transfer(op) => {
            let src = match &op.source {
                types::TransferEndpoint::Local { path } => {
                    format!("local:{}", parser::interpolate(path, variables))
                }
                types::TransferEndpoint::Host { host_id, path } => {
                    let host = host_id
                        .as_ref()
                        .map(|h| parser::interpolate(h, variables))
                        .unwrap_or_else(|| "target".to_string());
                    format!("{}:{}", host, parser::interpolate(path, variables))
                }
                types::TransferEndpoint::Storage { storage_id, path } => {
                    format!(
                        "storage:{}:{}",
                        parser::interpolate(storage_id, variables),
                        parser::interpolate(path, variables)
                    )
                }
            };
            let dst = match &op.destination {
                types::TransferEndpoint::Local { path } => {
                    format!("local:{}", parser::interpolate(path, variables))
                }
                types::TransferEndpoint::Host { host_id, path } => {
                    let host = host_id
                        .as_ref()
                        .map(|h| parser::interpolate(h, variables))
                        .unwrap_or_else(|| "target".to_string());
                    format!("{}:{}", host, parser::interpolate(path, variables))
                }
                types::TransferEndpoint::Storage { storage_id, path } => {
                    format!(
                        "storage:{}:{}",
                        parser::interpolate(storage_id, variables),
                        parser::interpolate(path, variables)
                    )
                }
            };
            format!(
                "Transferring files\n→ Source: {}\n→ Destination: {}",
                src, dst
            )
        }
        types::Operation::RsyncUpload(op) => {
            format!(
                "Uploading via rsync\n→ Local: {}\n→ Remote: {}",
                parser::interpolate(&op.local_path, variables),
                parser::interpolate(&op.remote_path, variables)
            )
        }
        types::Operation::RsyncDownload(op) => {
            format!(
                "Downloading via rsync\n→ Remote: {}\n→ Local: {}",
                parser::interpolate(&op.remote_path, variables),
                parser::interpolate(&op.local_path, variables)
            )
        }
        types::Operation::GitClone(op) => {
            let repo = parser::interpolate(&op.repo_url, variables);
            let dest = parser::interpolate(&op.destination, variables);
            let mut repo_display = repo.clone();
            if op.auth_token.is_some() && !repo_display.trim().starts_with("https://") {
                if let Some(rest) = repo_display.trim().strip_prefix("git@") {
                    if let Some((host, path)) = rest.split_once(':') {
                        let host = host.trim();
                        let path = path.trim().trim_start_matches('/');
                        if !host.is_empty() && !path.is_empty() {
                            repo_display = format!("https://{host}/{path}");
                        }
                    }
                }
            }
            let mut desc = format!(
                "Cloning git repository\n→ Repo: {}\n→ Destination: {}",
                repo_display, dest
            );
            if let Some(b) = &op.branch {
                desc.push_str(&format!(
                    "\n→ Branch: {}",
                    parser::interpolate(b, variables)
                ));
            }
            if op.auth_token.is_some() {
                desc.push_str("\n→ Using auth token");
            }
            desc
        }
        types::Operation::HfDownload(op) => {
            let repo_id = parser::interpolate(&op.repo_id, variables);
            let dest = parser::interpolate(&op.destination, variables);
            format!(
                "Downloading from HuggingFace\n→ Repo: {}\n→ Destination: {}",
                repo_id, dest
            )
        }
        types::Operation::VastStart(_) => {
            format!("Starting Vast.ai instance{}", vast_target_hint(variables))
        }
        types::Operation::VastStop(_) => {
            format!("Stopping Vast.ai instance{}", vast_target_hint(variables))
        }
        types::Operation::VastDestroy(_) => {
            format!("Destroying Vast.ai instance{}", vast_target_hint(variables))
        }
        types::Operation::WaitCondition(op) => {
            format!("Waiting for condition (timeout: {}s)", op.timeout_secs)
        }
        types::Operation::HttpRequest(op) => {
            format!(
                "{:?} {}",
                op.method,
                parser::interpolate(&op.url, variables)
            )
        }
        types::Operation::SetVar(_) => "Setting variable".to_string(),
        types::Operation::GetValue(_) => "Getting value".to_string(),
        types::Operation::Assert(_) => "Checking assertion".to_string(),
        _ => "Executing operation".to_string(),
    }
}

fn vast_target_hint(variables: &std::collections::HashMap<String, String>) -> String {
    let Some(target) = variables
        .get("target")
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
    else {
        return "".to_string();
    };
    if let Some(id) = target
        .strip_prefix("vast:")
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        return format!(" (#{} via target)", id);
    }
    format!(" (target: {target})")
}

/// Send command to an interactive skill execution's terminal
#[tauri::command]
pub async fn skill_interactive_send(
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
    data: String,
) -> Result<(), AppError> {
    // Get the terminal ID for this execution
    let runner = interactive::get_runner().await;
    let execution = runner.get_execution(&execution_id).await?;
    let term_id = execution
        .terminal_id
        .as_ref()
        .ok_or_else(|| AppError::invalid_input("Execution has no terminal session"))?;

    // Check if intervention is locked
    if execution.intervention_locked {
        return Err(AppError::command(
            "Intervention is currently locked - script is sending commands",
        ));
    }

    let term_id = execution
        .terminal_id
        .as_ref()
        .ok_or_else(|| AppError::invalid_input("Execution has no terminal session"))?;

    // Write to the terminal
    crate::terminal::term_write_inner(&term_mgr, term_id, &data).await
}

/// Send interrupt (Ctrl+C) to an interactive skill execution
#[tauri::command]
pub async fn skill_interactive_interrupt(
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    let execution = runner.get_execution(&execution_id).await?;

    let term_id = execution
        .terminal_id
        .as_ref()
        .ok_or_else(|| AppError::invalid_input("Execution has no terminal session"))?;

    // Send Ctrl+C (ASCII 0x03)
    crate::terminal::term_write_inner(&term_mgr, term_id, "\x03").await
}

/// Lock/unlock intervention for an interactive execution
#[tauri::command]
pub async fn skill_interactive_lock(execution_id: String, locked: bool) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    if locked {
        runner.lock_intervention(&execution_id).await
    } else {
        runner.unlock_intervention(&execution_id).await
    }
}

/// Get interactive execution state
#[tauri::command]
pub async fn skill_interactive_get(
    execution_id: String,
) -> Result<interactive::InteractiveExecution, AppError> {
    let runner = interactive::get_runner().await;
    runner.get_execution(&execution_id).await
}

/// List all interactive executions
#[tauri::command]
pub async fn skill_interactive_list() -> Result<Vec<interactive::InteractiveExecution>, AppError> {
    let runner = interactive::get_runner().await;
    Ok(runner.list_executions().await)
}

/// Read persisted logs for an interactive execution (JSONL), starting at `cursor`.
#[tauri::command]
pub async fn skill_interactive_log_read(
    execution_id: String,
    cursor: Option<u64>,
    max_bytes: Option<u64>,
) -> Result<run_logs::SkillLogChunk, AppError> {
    run_logs::read_chunk(&execution_id, cursor, max_bytes).await
}

/// Clear persisted logs for an interactive execution.
#[tauri::command]
pub async fn skill_interactive_log_clear(execution_id: String) -> Result<(), AppError> {
    run_logs::clear(&execution_id).await
}

/// Pause an interactive skill execution
#[tauri::command]
pub async fn skill_interactive_pause(execution_id: String) -> Result<(), AppError> {
    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };

    if active {
        let runner = interactive::get_runner().await;
        runner
            .send_control(&execution_id, interactive::InteractiveControl::Pause)
            .await
    } else {
        let runner = interactive::get_runner().await;
        runner
            .update_status(&execution_id, interactive::InteractiveStatus::Paused)
            .await
    }
}

/// Resume a paused interactive skill execution
#[tauri::command]
pub async fn skill_interactive_resume(
    app: tauri::AppHandle,
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
) -> Result<interactive::InteractiveExecution, AppError> {
    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };

    if active {
        let runner = interactive::get_runner().await;
        runner
            .send_control(&execution_id, interactive::InteractiveControl::Resume)
            .await?;
        let runner = interactive::get_runner().await;
        return runner.get_execution(&execution_id).await;
    }

    let exec = {
        let runner = interactive::get_runner().await;
        runner.get_execution(&execution_id).await?
    };

    if matches!(
        exec.status,
        interactive::InteractiveStatus::Completed
            | interactive::InteractiveStatus::Failed
            | interactive::InteractiveStatus::Cancelled
    ) {
        return Err(AppError::invalid_input("Execution is not resumable"));
    }

    let skill = load_skill(Path::new(&exec.skill_path)).await?;
    let (term_info, terminal_meta) =
        open_terminal_for_resume(app.clone(), &term_mgr, &exec, &skill).await?;

    let updated = {
        let runner = interactive::get_runner().await;
        runner
            .update_terminal(
                &execution_id,
                Some(term_info.id.clone()),
                Some(terminal_meta),
            )
            .await?
    };
    {
        let runner = interactive::get_runner().await;
        runner.set_active(&execution_id, true).await?;
    }

    let exec_id_clone = execution_id.clone();
    let term_id_clone = term_info.id.clone();
    let app_clone = app.clone();
    let variables = updated.variables.clone();
    tokio::spawn(async move {
        if let Err(e) =
            run_interactive_skill(app_clone, exec_id_clone, term_id_clone, skill, variables).await
        {
            eprintln!("[interactive_skill] Error running skill: {:?}", e);
        }
    });

    Ok(updated)
}

/// Start a prepared (pending) interactive skill execution
#[tauri::command]
pub async fn skill_interactive_start(
    app: tauri::AppHandle,
    _term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
) -> Result<interactive::InteractiveExecution, AppError> {
    use tauri::Emitter;

    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };
    if active {
        let runner = interactive::get_runner().await;
        return runner.get_execution(&execution_id).await;
    }

    let exec = {
        let runner = interactive::get_runner().await;
        runner.get_execution(&execution_id).await?
    };

    if exec.terminal_id.is_none() {
        return Err(AppError::invalid_input("Execution has no terminal attached"));
    }

    if matches!(
        exec.status,
        interactive::InteractiveStatus::Completed
            | interactive::InteractiveStatus::Failed
            | interactive::InteractiveStatus::Cancelled
    ) {
        return Err(AppError::invalid_input("Execution is not startable"));
    }

    let skill = load_skill(Path::new(&exec.skill_path)).await?;
    {
        let runner = interactive::get_runner().await;
        runner.set_active(&execution_id, true).await?;
        runner
            .update_status(&execution_id, interactive::InteractiveStatus::Running)
            .await?;
    }

    let log_lock = Arc::new(tokio::sync::Mutex::new(()));
    append_skill_log(
        &app,
        log_lock.as_ref(),
        &execution_id,
        None,
        run_logs::SkillLogStream::System,
        "Manual start requested".to_string(),
    )
    .await;

    let _ = app.emit(
        "skill:execution_updated",
        serde_json::json!({
            "execution_id": execution_id,
            "status": "running",
        }),
    );

    let exec_id_clone = execution_id.clone();
    let term_id = exec.terminal_id.clone().unwrap_or_default();
    let app_clone = app.clone();
    let variables = exec.variables.clone();
    tokio::spawn(async move {
        if let Err(e) = run_interactive_skill(app_clone, exec_id_clone, term_id, skill, variables).await {
            eprintln!("[interactive_skill] Error running skill: {:?}", e);
        }
    });

    let runner = interactive::get_runner().await;
    runner.get_execution(&execution_id).await
}

/// Reconnect the terminal session for an interactive execution.
/// This opens a fresh terminal connection and updates `terminal_id` in the execution state.
#[tauri::command]
pub async fn skill_interactive_reconnect_terminal(
    app: tauri::AppHandle,
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
) -> Result<interactive::InteractiveExecution, AppError> {
    use tauri::Emitter;

    let runner = interactive::get_runner().await;
    let active = runner.is_active(&execution_id).await?;
    let mut exec = runner.get_execution(&execution_id).await?;

    if matches!(
        exec.status,
        interactive::InteractiveStatus::Completed
            | interactive::InteractiveStatus::Failed
            | interactive::InteractiveStatus::Cancelled
    ) {
        return Err(AppError::invalid_input("Execution is not reconnectable"));
    }

    // If the execution is running, request a pause first so we don't swap the terminal
    // while a step might be actively streaming markers/output.
    if active
        && matches!(
            exec.status,
            interactive::InteractiveStatus::Running | interactive::InteractiveStatus::Connecting
        )
    {
        let log_lock = tokio::sync::Mutex::new(());
        append_skill_log(
            &app,
            &log_lock,
            &execution_id,
            None,
            run_logs::SkillLogStream::System,
            "Pause requested for terminal reconnect…".to_string(),
        )
        .await;

        runner
            .send_control(&execution_id, interactive::InteractiveControl::Pause)
            .await?;

        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(10);
        loop {
            exec = runner.get_execution(&execution_id).await?;
            if matches!(exec.status, interactive::InteractiveStatus::Paused) {
                break;
            }
            if std::time::Instant::now() >= deadline {
                return Err(AppError::command(
                    "Pause did not take effect in time; try reconnect again when the execution is paused",
                ));
            }
            tokio::time::sleep(std::time::Duration::from_millis(200)).await;
        }
    }

    let skill = load_skill(Path::new(&exec.skill_path)).await?;
    let (term_info, terminal_meta) =
        open_terminal_for_resume(app.clone(), &term_mgr, &exec, &skill).await?;

    let updated = {
        runner
            .update_terminal(
                &execution_id,
                Some(term_info.id.clone()),
                Some(terminal_meta),
            )
            .await?
    };

    let log_lock = tokio::sync::Mutex::new(());
    append_skill_log(
        &app,
        &log_lock,
        &execution_id,
        None,
        run_logs::SkillLogStream::System,
        "Terminal reconnected".to_string(),
    )
    .await;

    let _ = app.emit(
        "skill:execution_updated",
        serde_json::json!({
            "execution_id": execution_id,
            "status": updated.status,
        }),
    );

    Ok(updated)
}

/// Cancel an interactive skill execution
#[tauri::command]
pub async fn skill_interactive_cancel(app: tauri::AppHandle, execution_id: String) -> Result<(), AppError> {
    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };

    if active {
        use tauri::Emitter;
        let runner = interactive::get_runner().await;
        runner
            .send_control(&execution_id, interactive::InteractiveControl::Cancel)
            .await?;
        runner
            .update_status(&execution_id, interactive::InteractiveStatus::Cancelled)
            .await?;
        let log_lock = tokio::sync::Mutex::new(());
        append_skill_log(
            &app,
            &log_lock,
            &execution_id,
            None,
            run_logs::SkillLogStream::System,
            "Execution cancelled".to_string(),
        )
        .await;
        let _ = app.emit(
            "skill:execution_updated",
            serde_json::json!({
                "execution_id": execution_id,
                "status": "cancelled",
            }),
        );
        let _ = app.emit(
            "skill:execution_cancelled",
            serde_json::json!({
                "execution_id": execution_id,
            }),
        );
        Ok(())
    } else {
        let runner = interactive::get_runner().await;
        runner
            .update_status(&execution_id, interactive::InteractiveStatus::Cancelled)
            .await?;
        let log_lock = tokio::sync::Mutex::new(());
        append_skill_log(
            &app,
            &log_lock,
            &execution_id,
            None,
            run_logs::SkillLogStream::System,
            "Execution cancelled".to_string(),
        )
        .await;
        use tauri::Emitter;
        let _ = app.emit(
            "skill:execution_updated",
            serde_json::json!({
                "execution_id": execution_id,
                "status": "cancelled",
            }),
        );
        let _ = app.emit(
            "skill:execution_cancelled",
            serde_json::json!({
                "execution_id": execution_id,
            }),
        );
        Ok(())
    }
}

/// Skip a pending/waiting step in an interactive skill execution
#[tauri::command]
pub async fn skill_interactive_skip_step(
    app: tauri::AppHandle,
    execution_id: String,
    step_id: String,
) -> Result<(), AppError> {
    let step_id = step_id.trim().to_string();
    if step_id.is_empty() {
        return Err(AppError::invalid_input("Missing step_id"));
    }
    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };

    if active {
        let runner = interactive::get_runner().await;
        return runner
            .send_control(&execution_id, interactive::InteractiveControl::SkipStep(step_id))
            .await;
    }

    use tauri::Emitter;
    let runner = interactive::get_runner().await;
    let exec = runner.get_execution(&execution_id).await?;
    let skill = load_skill(Path::new(&exec.skill_path)).await?;

    runner
        .update_step_status(&execution_id, &step_id, StepStatus::Skipped)
        .await?;
    let exec_id_for_emit = execution_id.clone();
    let step_id_for_emit = step_id.clone();
    let _ = app.emit(
        "skill:step_skipped",
        serde_json::json!({
            "execution_id": exec_id_for_emit,
            "step_id": step_id_for_emit,
        }),
    );
    let log_lock = tokio::sync::Mutex::new(());
    append_skill_log(
        &app,
        &log_lock,
        &execution_id,
        Some(&step_id),
        run_logs::SkillLogStream::System,
        "Step skipped".to_string(),
    )
    .await;

    // Recompute pending/waiting statuses for remaining steps.
    use std::collections::HashSet;
    let snapshot = runner.get_execution(&execution_id).await?;
    let mut completed: HashSet<String> = HashSet::new();
    for s in &snapshot.steps {
        if matches!(s.status, StepStatus::Success | StepStatus::Skipped) {
            completed.insert(s.step_id.clone());
        }
    }
    for step in &skill.steps {
        if completed.contains(&step.id) {
            continue;
        }
        let status = if step.depends_on.iter().all(|dep| completed.contains(dep)) {
            StepStatus::Pending
        } else {
            StepStatus::Waiting
        };
        let _ = runner.update_step_status(&execution_id, &step.id, status).await;
    }

    Ok(())
}

async fn recompute_pending_waiting(
    runner: &interactive::InteractiveRunner,
    execution_id: &str,
    skill: &Skill,
    snapshot: &interactive::InteractiveExecution,
) -> Result<(), AppError> {
        use std::collections::HashSet;

        let mut completed: HashSet<String> = HashSet::new();
        for s in &snapshot.steps {
            if matches!(s.status, StepStatus::Success | StepStatus::Skipped) {
                completed.insert(s.step_id.clone());
            }
        }

        for step in &skill.steps {
            let current = snapshot.steps.iter().find(|s| s.step_id == step.id);
            let Some(current) = current else { continue };

            if matches!(
                current.status,
                StepStatus::Running | StepStatus::Retrying | StepStatus::Success | StepStatus::Failed | StepStatus::Cancelled | StepStatus::Skipped
            ) {
                continue;
            }

            let status = if step.depends_on.iter().all(|dep| completed.contains(dep)) {
                StepStatus::Pending
            } else {
                StepStatus::Waiting
            };
            let _ = runner.update_step_status(execution_id, &step.id, status).await;
        }

        Ok(())
}

/// Toggle skip for a step in a prepared (pending) execution.
/// - When active: only allows skipping (cannot unskip while running).
/// - When inactive: toggles between `skipped` and `pending/waiting` and recomputes downstream statuses.
#[tauri::command]
pub async fn skill_interactive_toggle_skip_step(
    app: tauri::AppHandle,
    execution_id: String,
    step_id: String,
) -> Result<(), AppError> {
    use tauri::Emitter;

    let step_id = step_id.trim().to_string();
    if step_id.is_empty() {
        return Err(AppError::invalid_input("Missing step_id"));
    }

    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };

    // If running, treat as "skip" only (one-way).
    if active {
        return skill_interactive_skip_step(app, execution_id, step_id).await;
    }

    let runner = interactive::get_runner().await;
    let exec = runner.get_execution(&execution_id).await?;
    let skill = load_skill(Path::new(&exec.skill_path)).await?;

    let current = exec
        .steps
        .iter()
        .find(|s| s.step_id == step_id)
        .ok_or_else(|| AppError::invalid_input("Unknown step_id"))?
        .status
        .clone();

    if matches!(
        current,
        StepStatus::Running | StepStatus::Retrying | StepStatus::Success | StepStatus::Failed | StepStatus::Cancelled
    ) {
        return Err(AppError::invalid_input("This step cannot be toggled"));
    }

    if current == StepStatus::Skipped {
        // Unskip: recompute status based on dependencies.
        runner
            .update_step_status(&execution_id, &step_id, StepStatus::Waiting)
            .await?;
        let snapshot = runner.get_execution(&execution_id).await?;
        recompute_pending_waiting(&runner, &execution_id, &skill, &snapshot).await?;

        let log_lock = tokio::sync::Mutex::new(());
        append_skill_log(
            &app,
            &log_lock,
            &execution_id,
            Some(&step_id),
            run_logs::SkillLogStream::System,
            "Step unskipped".to_string(),
        )
        .await;
    } else {
        // Skip
        runner
            .update_step_status(&execution_id, &step_id, StepStatus::Skipped)
            .await?;
        let snapshot = runner.get_execution(&execution_id).await?;
        recompute_pending_waiting(&runner, &execution_id, &skill, &snapshot).await?;

        let _ = app.emit(
            "skill:step_skipped",
            serde_json::json!({
                "execution_id": execution_id,
                "step_id": step_id,
            }),
        );
        let log_lock = tokio::sync::Mutex::new(());
        append_skill_log(
            &app,
            &log_lock,
            &execution_id,
            Some(&step_id),
            run_logs::SkillLogStream::System,
            "Step skipped".to_string(),
        )
        .await;
    }

    let _ = app.emit(
        "skill:execution_updated",
        serde_json::json!({
            "execution_id": execution_id,
            "status": exec.status,
        }),
    );

    Ok(())
}

/// Mark all steps as complete and finish execution
#[tauri::command]
pub async fn skill_interactive_mark_complete(execution_id: String) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;

    // Get execution and mark all running steps as success
    let execution = runner.get_execution(&execution_id).await?;
    for step in &execution.steps {
        if step.status == types::StepStatus::Running {
            runner
                .update_step_status(&execution_id, &step.step_id, types::StepStatus::Success)
                .await?;
        }
    }

    // Mark execution as completed
    runner.set_current_step(&execution_id, None).await?;
    runner
        .update_status(&execution_id, interactive::InteractiveStatus::Completed)
        .await
}

/// Execute a command in the interactive skill's terminal
/// This is used by the skill runner to send commands and track progress
#[tauri::command]
pub async fn skill_interactive_exec_command(
    app: tauri::AppHandle,
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
    step_id: String,
    command: String,
) -> Result<(), AppError> {
    use tauri::Emitter;

    let runner = interactive::get_runner().await;
    let execution = runner.get_execution(&execution_id).await?;

    let term_id = execution
        .terminal_id
        .as_ref()
        .ok_or_else(|| AppError::invalid_input("Execution has no terminal session"))?;

    // Lock intervention while sending command
    runner.lock_intervention(&execution_id).await?;

    // Emit event that we're sending a command
    let _ = app.emit(
        "skill:command_sending",
        serde_json::json!({
            "execution_id": execution_id,
            "step_id": step_id,
        }),
    );

    // Send the command with Enter
    let cmd_with_newline = format!("{}\n", command);
    crate::terminal::term_write_inner(&term_mgr, term_id, &cmd_with_newline).await?;

    // Emit event that command was sent
    let _ = app.emit(
        "skill:command_sent",
        serde_json::json!({
            "execution_id": execution_id,
            "step_id": step_id,
        }),
    );

    // Unlock intervention after a small delay to let the command be processed
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
    runner.unlock_intervention(&execution_id).await?;

    Ok(())
}

/// Send user input to an interactive skill execution waiting for input
/// This is used when a command is waiting for password, y/n confirmation, etc.
#[tauri::command]
pub async fn skill_interactive_send_input(
    execution_id: String,
    input: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    runner
        .send_control(&execution_id, interactive::InteractiveControl::SendInput(input))
        .await
}
