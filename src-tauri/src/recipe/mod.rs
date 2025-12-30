//! Recipe System
//!
//! A flexible workflow engine for composing and executing automation tasks.
//! Recipes define a DAG of steps that can run in parallel with dependency resolution.

pub mod execution;
pub mod interactive;
pub mod operations;
pub mod parser;
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

fn recipe_slug_from_name(name: &str) -> Result<String, AppError> {
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
            "Recipe name must contain at least one alphanumeric character",
        ));
    }

    Ok(out)
}

fn recipe_path_for_name(recipes_dir: &Path, name: &str) -> Result<PathBuf, AppError> {
    Ok(recipes_dir.join(format!("{}.toml", recipe_slug_from_name(name)?)))
}

// ============================================================
// Recipe Store
// ============================================================

/// Manages recipe storage and execution
pub struct RecipeStore {
    recipes_dir: PathBuf,
}

impl RecipeStore {
    pub fn new(data_dir: &Path) -> Self {
        Self {
            recipes_dir: data_dir.join("recipes"),
        }
    }

    fn recipes_dir(&self) -> &PathBuf {
        &self.recipes_dir
    }
}

// ============================================================
// Tauri Commands
// ============================================================

/// List all recipes in the recipes directory
#[tauri::command]
pub async fn recipe_list(
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<Vec<RecipeSummary>, AppError> {
    let store = store.read().await;
    let dir = store.recipes_dir();

    if !dir.exists() {
        return Ok(vec![]);
    }

    let mut summaries = Vec::new();
    let mut entries = tokio::fs::read_dir(dir).await?;

    while let Some(entry) = entries.next_entry().await? {
        let path = entry.path();
        if path.extension().map_or(false, |e| e == "toml") {
            match get_recipe_summary(&path).await {
                Ok(mut summary) => {
                    match recipe_path_for_name(dir, &summary.name) {
                        Ok(desired_path) => {
                            if desired_path != path {
                                if desired_path.exists() {
                                    eprintln!(
                                        "Recipe file name mismatch for {:?} (wanted {:?}) but destination exists; keeping original",
                                        path, desired_path
                                    );
                                } else if let Err(e) = tokio::fs::rename(&path, &desired_path).await
                                {
                                    eprintln!(
                                        "Failed to rename recipe file {:?} -> {:?}: {}",
                                        path, desired_path, e
                                    );
                                } else {
                                    summary.path = desired_path.to_string_lossy().to_string();
                                }
                            }
                        }
                        Err(e) => {
                            eprintln!("Failed to derive recipe filename for {:?}: {}", path, e);
                        }
                    }
                    summaries.push(summary)
                }
                Err(e) => {
                    eprintln!("Failed to load recipe {:?}: {}", path, e);
                }
            }
        }
    }

    // Sort by name
    summaries.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(summaries)
}

/// Get a recipe by path
#[tauri::command]
pub async fn recipe_get(path: String) -> Result<Recipe, AppError> {
    load_recipe(Path::new(&path)).await
}

/// Save a recipe to a file
#[tauri::command]
pub async fn recipe_save(
    path: String,
    recipe: Recipe,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<String, AppError> {
    let store = store.read().await;
    let dir = store.recipes_dir();

    tokio::fs::create_dir_all(dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create recipes directory: {e}")))?;

    let desired_path = recipe_path_for_name(dir, &recipe.name)?;

    let current_path = PathBuf::from(path);
    if current_path.exists() {
        if !current_path.starts_with(dir) {
            return Err(AppError::invalid_input("Invalid recipe path"));
        }

        if current_path != desired_path {
            if desired_path.exists() {
                return Err(AppError::invalid_input(
                    "A recipe with this name already exists",
                ));
            }

            tokio::fs::rename(&current_path, &desired_path)
                .await
                .map_err(|e| AppError::io(format!("Failed to rename recipe file: {e}")))?;
        }
    }

    save_recipe(&desired_path, &recipe).await?;
    Ok(desired_path.to_string_lossy().to_string())
}

/// Delete a recipe file
#[tauri::command]
pub async fn recipe_delete(path: String) -> Result<(), AppError> {
    let p = Path::new(&path);
    if p.exists() {
        tokio::fs::remove_file(p)
            .await
            .map_err(|e| AppError::io(format!("Failed to delete recipe: {e}")))?;
    }
    Ok(())
}

/// Validate a recipe
#[tauri::command]
pub async fn recipe_validate(recipe: Recipe) -> Result<ValidationResult, AppError> {
    Ok(validate_recipe(&recipe))
}

/// Create a new empty recipe file
#[tauri::command]
pub async fn recipe_create(
    name: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<String, AppError> {
    let store = store.read().await;
    let dir = store.recipes_dir();

    tokio::fs::create_dir_all(dir)
        .await
        .map_err(|e| AppError::io(format!("Failed to create recipes directory: {e}")))?;

    let path = recipe_path_for_name(dir, &name)?;
    if path.exists() {
        return Err(AppError::invalid_input(
            "A recipe with this name already exists",
        ));
    }

    let recipe = Recipe {
        name,
        version: "1.0.0".to_string(),
        description: None,
        target: None,
        variables: HashMap::new(),
        steps: vec![],
    };

    save_recipe(&path, &recipe).await?;

    Ok(path.to_string_lossy().to_string())
}

/// Import a recipe from a file
#[tauri::command]
pub async fn recipe_import(
    source_path: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<String, AppError> {
    // Load and validate the recipe first
    let recipe = load_recipe(Path::new(&source_path)).await?;
    let validation = validate_recipe(&recipe);

    if !validation.valid {
        let errors: Vec<String> = validation
            .errors
            .iter()
            .map(|e| e.message.clone())
            .collect();
        return Err(AppError::invalid_input(format!(
            "Invalid recipe: {}",
            errors.join(", ")
        )));
    }

    // Copy to recipes directory
    let store = store.read().await;
    let dir = store.recipes_dir();
    tokio::fs::create_dir_all(dir).await?;

    let dest_path = recipe_path_for_name(dir, &recipe.name)?;
    if dest_path.exists() {
        return Err(AppError::invalid_input(
            "A recipe with this name already exists",
        ));
    }
    save_recipe(&dest_path, &recipe).await?;

    Ok(dest_path.to_string_lossy().to_string())
}

/// Export a recipe to a file
#[tauri::command]
pub async fn recipe_export(recipe_path: String, dest_path: String) -> Result<(), AppError> {
    let recipe = load_recipe(Path::new(&recipe_path)).await?;
    save_recipe(Path::new(&dest_path), &recipe).await
}

/// Duplicate a recipe
#[tauri::command]
pub async fn recipe_duplicate(
    path: String,
    new_name: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<String, AppError> {
    let mut recipe = load_recipe(Path::new(&path)).await?;
    recipe.name = new_name.clone();

    let store = store.read().await;
    let dir = store.recipes_dir();

    let new_path = recipe_path_for_name(dir, &new_name)?;
    if new_path.exists() {
        return Err(AppError::invalid_input(
            "A recipe with this name already exists",
        ));
    }

    save_recipe(&new_path, &recipe).await?;

    Ok(new_path.to_string_lossy().to_string())
}

// ============================================================
// Interactive Execution Commands
// ============================================================

/// Special target value for local execution
const LOCAL_TARGET: &str = "__local__";

/// Start an interactive recipe execution with terminal output
#[tauri::command]
#[allow(clippy::too_many_arguments)]
pub async fn recipe_run_interactive(
    app: tauri::AppHandle,
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    path: String,
    host_id: String,
    variables: HashMap<String, String>,
    cols: Option<u16>,
    rows: Option<u16>,
) -> Result<interactive::InteractiveExecution, AppError> {
    use crate::terminal::TermSessionInfo;
    use tauri::Emitter;

    // Load and validate recipe
    let recipe = load_recipe(Path::new(&path)).await?;
    let validation = validate_recipe(&recipe);
    if !validation.valid {
        let errors: Vec<String> = validation
            .errors
            .iter()
            .map(|e| e.message.clone())
            .collect();
        return Err(AppError::invalid_input(format!(
            "Recipe validation failed: {}",
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
    ) =
        if is_local {
        // Local execution - open a local terminal
        let title = format!("Recipe: {} (Local)", recipe.name);
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
		                "recipe-{}",
		                uuid::Uuid::new_v4()
		                    .to_string()
		                    .split('-')
		                    .next()
		                    .unwrap_or("exec")
		            );

		            // If the recipe contains a `vast_start` step, avoid probing SSH here (it can block the UI for ~20s).
		            // We'll connect the terminal right after `vast_start` succeeds.
		            let defer_connect_after_start = recipe
		                .steps
		                .iter()
		                .any(|s| matches!(s.operation, types::Operation::VastStart(_)));
		            if defer_connect_after_start {
		                let title = format!("Recipe: {} (Waiting for Vast start)", recipe.name);
		                let info = crate::terminal::open_local_inner(
		                    app.clone(),
		                    &term_mgr,
		                    Some(title),
		                    cols.unwrap_or(120),
		                    rows.unwrap_or(32),
		                )
		                .await?;
		                (info, host_id.clone(), Some(tmux_session.clone()), Some(tmux_session))
		            } else {
		                let ssh = match crate::host::resolve_ssh_spec(&host_id).await {
		                    Ok(ssh) => Some(ssh),
		                    Err(e) if e.message.contains("Vast SSH route is not available yet") => None,
		                    Err(e) => return Err(e),
		                };

		                if let Some(ssh) = ssh {
		                    let title = format!("Recipe: {} on {}", recipe.name, inst_label);

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
		                    // Vast instance may be stopped and not exposing SSH metadata yet. Still allow starting the recipe.
		                    let title = format!("Recipe: {} (Waiting for Vast SSH)", recipe.name);
		                    let info = crate::terminal::open_local_inner(
		                        app.clone(),
		                        &term_mgr,
		                        Some(title),
		                        cols.unwrap_or(120),
		                        rows.unwrap_or(32),
		                    )
		                    .await?;
		                    (info, host_id.clone(), Some(tmux_session.clone()), Some(tmux_session))
		                }
		            }
		        } else {
	            let host = get_host(&host_id).await?;
	            let ssh = host
	                .ssh
                .as_ref()
                .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;

            let tmux_session = format!(
                "recipe-{}",
                uuid::Uuid::new_v4()
                    .to_string()
                    .split('-')
                    .next()
                    .unwrap_or("exec")
            );
            let title = format!("Recipe: {} on {}", recipe.name, host.name);

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

    // Merge recipe variables with overrides
    let mut merged_variables = recipe.variables.clone();
    merged_variables.extend(variables.clone());
    // Add target variable if not present
    if !merged_variables.contains_key("target") {
        merged_variables.insert("target".to_string(), effective_host_id.clone());
    }
    if let Some(tmux_session) = connect_after_vast_start {
        merged_variables.insert("_doppio_connect_after_vast_start".to_string(), "1".to_string());
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
            recipe.clone(),
            path.clone(),
            effective_host_id.clone(),
            term_info.id.clone(),
            terminal_meta,
            merged_variables.clone(),
        )
        .await?;

    // Get the execution state
    let execution = runner.get_execution(&exec_id).await?;

    // Emit event with terminal session info
    // Emit event immediately so frontend can show the recipe info
    let _ = app.emit(
        "recipe:interactive_started",
        serde_json::json!({
            "execution_id": exec_id,
            "terminal_id": term_id,
            "recipe_name": recipe.name,
            "host_id": effective_host_id,
            "steps": execution.steps.iter().map(|s| serde_json::json!({
                "step_id": s.step_id,
                "name": s.name,
                "status": s.status,
            })).collect::<Vec<_>>(),
        }),
    );

    // Spawn background task to run the recipe
    let exec_id_clone = exec_id.clone();
    let term_id_clone = term_id.clone();
    let app_clone = app.clone();

    tokio::spawn(async move {
        if let Err(e) = run_interactive_recipe(
            app_clone,
            exec_id_clone,
            term_id_clone,
            recipe,
            merged_variables,
        )
        .await
        {
            eprintln!("[interactive_recipe] Error running recipe: {:?}", e);
        }
    });

    Ok(execution)
}

/// Background task to run an interactive recipe
async fn run_interactive_recipe(
    app: tauri::AppHandle,
    exec_id: String,
    term_id: String,
    recipe: Recipe,
    variables: HashMap<String, String>,
) -> Result<(), AppError> {
    use std::collections::{HashMap, HashSet};
    use tauri::Emitter;
    use tauri::Manager;

    let mut variables = variables;

    let term_mgr = app.state::<crate::terminal::TerminalManager>();
    let history = term_mgr.history(&term_id).await;

    let mut control_rx = interactive::get_runner()
        .await
        .take_control_receiver(&exec_id)
        .await?;

    let step_order = execution::compute_execution_order(&recipe.steps)?;
    let step_index: HashMap<String, usize> = recipe
        .steps
        .iter()
        .enumerate()
        .map(|(index, step)| (step.id.clone(), index))
        .collect();
    let step_map: HashMap<String, Step> = recipe
        .steps
        .iter()
        .cloned()
        .map(|step| (step.id.clone(), step))
        .collect();

    let exec_snapshot = interactive::get_runner().await.get_execution(&exec_id).await?;
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

    for step in &recipe.steps {
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
        "recipe:execution_updated",
        serde_json::json!({
            "execution_id": exec_id,
            "status": "running",
        }),
    );

    tokio::time::sleep(tokio::time::Duration::from_millis(300)).await;

    eprintln!("[interactive_recipe] Starting execution {}", exec_id);

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
                    "recipe:step_skipped",
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
            eprintln!("[interactive_recipe] history step start failed: {}", e);
        }

        let _ = app.emit(
            "recipe:step_started",
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
                    "recipe:step_retrying",
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

            if let Some(cmds) = commands {
                interactive::get_runner()
                    .await
                    .lock_intervention(&exec_id)
                    .await?;
                let _ = app.emit(
                    "recipe:intervention_lock_changed",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "terminal_id": term_id,
                        "locked": true,
                    }),
                );

                let _ = app.emit(
                    "recipe:command_sending",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step.id,
                        "command": cmds,
                    }),
                );

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

                let heredoc = format!(
                    "${{SHELL:-bash}} <<'DOPPIO_EOF'\n{}{}\n__doppio_rc__=$?\necho '{}:'$__doppio_rc__\nDOPPIO_EOF\n",
                    workdir_prefix,
                    cmds.trim(),
                    DONE_MARKER
                );
                crate::terminal::term_write_inner(&term_mgr, &term_id, &heredoc).await?;

                eprintln!("[interactive_recipe] Sent commands:\n{}", cmds);

                tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

                interactive::get_runner()
                    .await
                    .unlock_intervention(&exec_id)
                    .await?;
                let _ = app.emit(
                    "recipe:intervention_lock_changed",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "terminal_id": term_id,
                        "locked": false,
                    }),
                );

                interactive::get_runner()
                    .await
                    .update_status(&exec_id, interactive::InteractiveStatus::WaitingForInput)
                    .await?;

                let exit_code =
                    crate::terminal::wait_for_marker_with_exit_code(&term_mgr, &term_id, DONE_MARKER)
                        .await;
                step_exit_code = Some(exit_code);

                eprintln!(
                    "[interactive_recipe] Commands completed, exit_code: {}",
                    exit_code
                );

                if exit_code != 0 {
                    let error_msg = format!(
                        "\r\n\x1b[31m✗ {} - exit code {}\x1b[0m\r\n",
                        step.id, exit_code
                    );
                    crate::terminal::term_display(&app, &term_id, &error_msg, history.as_deref());
                    step_failed = true;
                    last_error = Some(format!(
                        "Step {} failed with exit code {}",
                        step.id, exit_code
                    ));
                } else {
                    step_failed = false;
                    last_error = None;
                }

                interactive::get_runner()
                    .await
                    .update_status(&exec_id, interactive::InteractiveStatus::Running)
                    .await?;
            } else {
                eprintln!(
                    "[interactive_recipe] Executing operation via backend: {:?}",
                    step.operation
                );

                let op_desc = get_operation_description(&step.operation, &variables);
                let start_msg = format!(
                    "\r\n\x1b[1;36m▶ [Doppio] {}\x1b[0m\r\n\x1b[90m  {}\x1b[0m\r\n",
                    step.id,
                    op_desc.replace('\n', "\r\n  ")
                );
                crate::terminal::term_display(&app, &term_id, &start_msg, history.as_deref());

                let exec_id_clone = exec_id.clone();
                let step_id_clone = step.id.clone();
                let app_handle = app.clone();
                let term_id_clone = term_id.clone();
                let history_for_progress = history.clone();
                let progress_cb: Arc<dyn Fn(&str) + Send + Sync> = Arc::new(move |msg: &str| {
                    let exec_id = exec_id_clone.clone();
                    let step_id = step_id_clone.clone();
                    let app_handle_inner = app_handle.clone();
                    let message = msg.to_string();
                    tauri::async_runtime::spawn(async move {
                        let runner = interactive::get_runner().await;
                        let _ = runner
                            .set_step_progress(&exec_id, &step_id, Some(message.clone()))
                            .await;
                        let _ = app_handle_inner.emit(
                            "recipe:step_progress",
                            serde_json::json!({
                                "execution_id": exec_id,
                                "step_id": step_id,
                                "progress": message,
                            }),
                        );
                    });
                    let live_msg = format!("\x1b[90m  → {}\x1b[0m\r\n", msg);
                    crate::terminal::term_display(
                        &app_handle,
                        &term_id_clone,
                        &live_msg,
                        history_for_progress.as_deref(),
                    );
                });
                progress_cb(&op_desc.lines().next().unwrap_or(&op_desc));

                match execution::execute_step(&step.operation, &variables, Some(progress_cb.clone()))
                    .await
                {
                    Ok(Some(output)) => {
                        let formatted_output = output.replace('\n', "\r\n");
                        let success_msg = format!(
                            "\x1b[32m✓ {}\x1b[0m\r\n{}\r\n",
                            step.id, formatted_output
                        );
                        crate::terminal::term_display(&app, &term_id, &success_msg, history.as_deref());
                        step_failed = false;
                        last_error = None;
                    }
                    Ok(None) => {
                        let success_msg =
                            format!("\x1b[32m✓ {} completed\x1b[0m\r\n", step.id);
                        crate::terminal::term_display(&app, &term_id, &success_msg, history.as_deref());
                        step_failed = false;
                        last_error = None;
                    }
                    Err(e) => {
                        let error_str = e.to_string().replace('\n', "\r\n  ");
                        let error_msg = format!(
                            "\x1b[31m✗ {} failed:\x1b[0m\r\n  \x1b[31m{}\x1b[0m\r\n",
                            step.id, error_str
                        );
                        crate::terminal::term_display(&app, &term_id, &error_msg, history.as_deref());
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
                        "recipe:step_progress",
                        serde_json::json!({
                            "execution_id": exec_id_clone,
                            "step_id": step_id_clone,
                            "progress": serde_json::Value::Null,
                        }),
                    );
                });
            }

            if step_failed && attempt < max_attempts {
                let retry_msg = format!(
                    "\x1b[33m↻ {} retrying in {}s (attempt {}/{})\x1b[0m\r\n",
                    step.id, delay_secs, attempt, max_attempts
                );
                crate::terminal::term_display(&app, &term_id, &retry_msg, history.as_deref());
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
                "recipe:step_failed",
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
                    "recipe:execution_failed",
                    serde_json::json!({
                        "execution_id": exec_id,
                        "error": error_msg,
                    }),
                );
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
                    .ok_or_else(|| AppError::invalid_input("Missing recipe variable: target"))?;
                let tmux_session = variables
                    .get("_doppio_connect_tmux_session")
                    .cloned()
                    .ok_or_else(|| {
                        AppError::invalid_input(
                            "Missing recipe variable: _doppio_connect_tmux_session",
                        )
                    })?;

                let msg = "\r\n\x1b[90m[doppio] Connecting terminal to Vast SSH…\x1b[0m\r\n";
                crate::terminal::term_display(&app, &term_id, msg, history.as_deref());

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
            eprintln!("[interactive_recipe] Step {} completed", step.id);
            let _ = app.emit(
                "recipe:step_completed",
                serde_json::json!({
                    "execution_id": exec_id,
                    "step_id": step.id,
                }),
            );
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
            eprintln!("[interactive_recipe] history step end failed: {}", e);
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
            "recipe:execution_completed",
            serde_json::json!({
                "execution_id": exec_id,
            }),
        );
    }

    Ok(())
}

#[derive(Default)]
struct ControlState {
    paused: bool,
    pause_requested: bool,
    cancel_requested: bool,
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
                "recipe:execution_updated",
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
                "recipe:execution_updated",
                serde_json::json!({
                    "execution_id": exec_id,
                    "status": "cancelled",
                }),
            );
            let _ = app.emit(
                "recipe:execution_cancelled",
                serde_json::json!({
                    "execution_id": exec_id,
                }),
            );
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
            "recipe:execution_updated",
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

async fn open_terminal_for_resume(
    app: tauri::AppHandle,
    term_mgr: &crate::terminal::TerminalManager,
    exec: &interactive::InteractiveExecution,
    recipe: &Recipe,
) -> Result<(crate::terminal::TermSessionInfo, interactive::InteractiveTerminal), AppError> {
    use crate::host::{default_env_vars, get_host, HostType};

    let cols = exec.terminal.cols;
    let rows = exec.terminal.rows;
    let title = if exec.terminal.title.trim().is_empty() {
        format!("Recipe: {}", exec.recipe_name)
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

    let needs_vast_start = recipe.steps.iter().any(|step| {
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
/// Returns None if the operation must be executed via Rust backend
fn extract_commands_from_step(
    step: &types::Step,
    variables: &HashMap<String, String>,
) -> Option<String> {
    match &step.operation {
        types::Operation::RunCommands(op) => Some(parser::interpolate(&op.commands, variables)),
        types::Operation::SshCommand(op) => Some(parser::interpolate(&op.command, variables)),
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

            let mut cmd = format!("git clone {}", repo);
            if let Some(b) = &op.branch {
                cmd.push_str(&format!(" -b {}", parser::interpolate(b, variables)));
            }
            if let Some(d) = op.depth {
                cmd.push_str(&format!(" --depth {}", d));
            }
            cmd.push_str(&format!(" {}", dest));
            Some(cmd)
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
        // GdriveMount/Unmount, Transfer, RsyncUpload/Download, VastStart/Stop/Destroy/VastCopy,
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
            let mut desc = format!(
                "Cloning git repository\n→ Repo: {}\n→ Destination: {}",
                repo, dest
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
        types::Operation::VastCopy(op) => {
            let src = parser::interpolate(&op.src, variables);
            let dst = parser::interpolate(&op.dst, variables);
            format!(
                "Copying data via Vast API\n→ Source: {}\n→ Destination: {}",
                src, dst
            )
        }
        types::Operation::WaitCondition(op) => {
            format!("Waiting for condition (timeout: {}s)", op.timeout_secs)
        }
        types::Operation::HttpRequest(op) => {
            format!("{:?} {}", op.method, parser::interpolate(&op.url, variables))
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

/// Send command to an interactive recipe execution's terminal
#[tauri::command]
pub async fn recipe_interactive_send(
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

/// Send interrupt (Ctrl+C) to an interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_interrupt(
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
pub async fn recipe_interactive_lock(execution_id: String, locked: bool) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    if locked {
        runner.lock_intervention(&execution_id).await
    } else {
        runner.unlock_intervention(&execution_id).await
    }
}

/// Get interactive execution state
#[tauri::command]
pub async fn recipe_interactive_get(
    execution_id: String,
) -> Result<interactive::InteractiveExecution, AppError> {
    let runner = interactive::get_runner().await;
    runner.get_execution(&execution_id).await
}

/// List all interactive executions
#[tauri::command]
pub async fn recipe_interactive_list() -> Result<Vec<interactive::InteractiveExecution>, AppError> {
    let runner = interactive::get_runner().await;
    Ok(runner.list_executions().await)
}

/// Pause an interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_pause(execution_id: String) -> Result<(), AppError> {
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

/// Resume a paused interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_resume(
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

    let recipe = load_recipe(Path::new(&exec.recipe_path)).await?;
    let (term_info, terminal_meta) =
        open_terminal_for_resume(app.clone(), &term_mgr, &exec, &recipe).await?;

    let updated = {
        let runner = interactive::get_runner().await;
        runner
            .update_terminal(&execution_id, Some(term_info.id.clone()), Some(terminal_meta))
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
            run_interactive_recipe(app_clone, exec_id_clone, term_id_clone, recipe, variables).await
        {
            eprintln!("[interactive_recipe] Error running recipe: {:?}", e);
        }
    });

    Ok(updated)
}

/// Cancel an interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_cancel(execution_id: String) -> Result<(), AppError> {
    let active = {
        let runner = interactive::get_runner().await;
        runner.is_active(&execution_id).await?
    };

    if active {
        let runner = interactive::get_runner().await;
        runner
            .send_control(&execution_id, interactive::InteractiveControl::Cancel)
            .await
    } else {
        let runner = interactive::get_runner().await;
        runner
            .update_status(&execution_id, interactive::InteractiveStatus::Cancelled)
            .await
    }
}

/// Mark all steps as complete and finish execution
#[tauri::command]
pub async fn recipe_interactive_mark_complete(execution_id: String) -> Result<(), AppError> {
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

/// Execute a command in the interactive recipe's terminal
/// This is used by the recipe runner to send commands and track progress
#[tauri::command]
pub async fn recipe_interactive_exec_command(
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
        "recipe:command_sending",
        serde_json::json!({
            "execution_id": execution_id,
            "step_id": step_id,
            "command": command,
        }),
    );

    // Send the command with Enter
    let cmd_with_newline = format!("{}\n", command);
    crate::terminal::term_write_inner(&term_mgr, term_id, &cmd_with_newline).await?;

    // Emit event that command was sent
    let _ = app.emit(
        "recipe:command_sent",
        serde_json::json!({
            "execution_id": execution_id,
            "step_id": step_id,
            "command": command,
        }),
    );

    // Unlock intervention after a small delay to let the command be processed
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
    runner.unlock_intervention(&execution_id).await?;

    Ok(())
}
