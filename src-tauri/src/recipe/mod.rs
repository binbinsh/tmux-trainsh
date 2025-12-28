//! Recipe System
//!
//! A flexible workflow engine for composing and executing automation tasks.
//! Recipes define a DAG of steps that can run in parallel with dependency resolution.

pub mod types;
pub mod parser;
pub mod execution;
pub mod operations;
pub mod interactive;

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use tauri::State;
use tokio::sync::RwLock;

use crate::config::doppio_data_dir;
use crate::error::AppError;

pub use types::*;
pub use parser::*;
pub use execution::*;

// ============================================================
// Recipe Store
// ============================================================

/// Manages recipe storage and execution
pub struct RecipeStore {
    runner: RecipeRunner,
    recipes_dir: PathBuf,
}

impl RecipeStore {
    pub fn new(data_dir: &Path) -> Self {
        Self {
            runner: RecipeRunner::new(),
            recipes_dir: data_dir.join("recipes"),
        }
    }
    
    fn recipes_dir(&self) -> &PathBuf {
        &self.recipes_dir
    }
    
    fn executions_dir(&self) -> PathBuf {
        doppio_data_dir().join("recipe_executions")
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
                Ok(summary) => summaries.push(summary),
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
) -> Result<(), AppError> {
    save_recipe(Path::new(&path), &recipe).await
}

/// Delete a recipe file
#[tauri::command]
pub async fn recipe_delete(path: String) -> Result<(), AppError> {
    let p = Path::new(&path);
    if p.exists() {
        tokio::fs::remove_file(p).await
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
    
    tokio::fs::create_dir_all(dir).await
        .map_err(|e| AppError::io(format!("Failed to create recipes directory: {e}")))?;
    
    // Generate filename from name
    let filename = name.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { '-' })
        .collect::<String>();
    let path = dir.join(format!("{}.toml", filename));
    
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

/// Run a recipe
#[tauri::command]
pub async fn recipe_run(
    path: String,
    variables: HashMap<String, String>,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<String, AppError> {
    let recipe = load_recipe(Path::new(&path)).await?;
    
    // Validate first
    let validation = validate_recipe(&recipe);
    if !validation.valid {
        let errors: Vec<String> = validation.errors.iter().map(|e| e.message.clone()).collect();
        return Err(AppError::invalid_input(format!("Recipe validation failed: {}", errors.join(", "))));
    }
    
    let store = store.read().await;
    store.runner.run(recipe, path, variables).await
}

/// Pause an execution
#[tauri::command]
pub async fn recipe_pause(
    execution_id: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<(), AppError> {
    let store = store.read().await;
    store.runner.pause(&execution_id).await
}

/// Resume an execution
#[tauri::command]
pub async fn recipe_resume(
    execution_id: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<(), AppError> {
    let store = store.read().await;
    store.runner.resume(&execution_id).await
}

/// Cancel an execution
#[tauri::command]
pub async fn recipe_cancel(
    execution_id: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<(), AppError> {
    let store = store.read().await;
    store.runner.cancel(&execution_id).await
}

/// Retry a failed step
#[tauri::command]
pub async fn recipe_retry_step(
    execution_id: String,
    step_id: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<(), AppError> {
    let store = store.read().await;
    store.runner.retry_step(&execution_id, &step_id).await
}

/// Skip a step
#[tauri::command]
pub async fn recipe_skip_step(
    execution_id: String,
    step_id: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<(), AppError> {
    let store = store.read().await;
    store.runner.skip_step(&execution_id, &step_id).await
}

/// Get execution details
#[tauri::command]
pub async fn recipe_get_execution(
    execution_id: String,
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<Execution, AppError> {
    let store = store.read().await;
    store.runner.get_execution(&execution_id).await
}

/// List all executions
#[tauri::command]
pub async fn recipe_list_executions(
    store: State<'_, Arc<RwLock<RecipeStore>>>,
) -> Result<Vec<ExecutionSummary>, AppError> {
    let store = store.read().await;
    Ok(store.runner.list_executions().await)
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
        let errors: Vec<String> = validation.errors.iter().map(|e| e.message.clone()).collect();
        return Err(AppError::invalid_input(format!("Invalid recipe: {}", errors.join(", "))));
    }
    
    // Copy to recipes directory
    let store = store.read().await;
    let dir = store.recipes_dir();
    tokio::fs::create_dir_all(dir).await?;
    
    let filename = Path::new(&source_path)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| format!("{}.toml", recipe.name));
    
    let dest_path = dir.join(&filename);
    save_recipe(&dest_path, &recipe).await?;
    
    Ok(dest_path.to_string_lossy().to_string())
}

/// Export a recipe to a file
#[tauri::command]
pub async fn recipe_export(
    recipe_path: String,
    dest_path: String,
) -> Result<(), AppError> {
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
    
    let filename = new_name.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { '-' })
        .collect::<String>();
    let new_path = dir.join(format!("{}.toml", filename));
    
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
        let errors: Vec<String> = validation.errors.iter().map(|e| e.message.clone()).collect();
        return Err(AppError::invalid_input(format!("Recipe validation failed: {}", errors.join(", "))));
    }
    
    // Check if this is local execution
    let is_local = host_id == LOCAL_TARGET;
    
    let (term_info, effective_host_id): (TermSessionInfo, String) = if is_local {
        // Local execution - open a local terminal
        let title = format!("Recipe: {} (Local)", recipe.name);
        let info = crate::terminal::open_local_inner(
            app.clone(),
            &term_mgr,
            Some(title),
            cols.unwrap_or(120),
            rows.unwrap_or(32),
        ).await?;
        (info, LOCAL_TARGET.to_string())
    } else {
        // Remote execution - open SSH tmux session
        use crate::host::get_host;
        
        let host = get_host(&host_id).await?;
        let ssh = host.ssh.as_ref()
            .ok_or_else(|| AppError::invalid_input("Host has no SSH configuration"))?;
        
        let tmux_session = format!("recipe-{}", uuid::Uuid::new_v4().to_string().split('-').next().unwrap_or("exec"));
        let title = format!("Recipe: {} on {}", recipe.name, host.name);
        
        let info: TermSessionInfo = crate::terminal::open_ssh_tmux_inner_static(
            app.clone(),
            &term_mgr,
            ssh.clone(),
            tmux_session.clone(),
            Some(title),
            cols.unwrap_or(120),
            rows.unwrap_or(32),
            Some(crate::host::default_env_vars(&host.host_type)),
        ).await?;
        (info, host_id.clone())
    };
    
    // Merge recipe variables with overrides
    let mut merged_variables = recipe.variables.clone();
    merged_variables.extend(variables.clone());
    // Add target variable if not present
    if !merged_variables.contains_key("target") {
        merged_variables.insert("target".to_string(), effective_host_id.clone());
    }
    
    // Start interactive execution
    let runner = interactive::get_runner().await;
    let (exec_id, term_id) = runner.start(
        recipe.clone(),
        path.clone(),
        effective_host_id.clone(),
        term_info.id.clone(),
        merged_variables.clone(),
    ).await?;
    
    // Get the execution state
    let execution = runner.get_execution(&exec_id).await?;
    
    // Emit event with terminal session info
    // Emit event immediately so frontend can show the recipe info
    let _ = app.emit("recipe:interactive_started", serde_json::json!({
        "execution_id": exec_id,
        "terminal_id": term_id,
        "recipe_name": recipe.name,
        "host_id": effective_host_id,
        "steps": execution.steps.iter().map(|s| serde_json::json!({
            "step_id": s.step_id,
            "name": s.name,
            "status": s.status,
        })).collect::<Vec<_>>(),
    }));
    
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
        ).await {
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
    use tauri::Emitter;
    use tauri::Manager;
    
    // Get terminal manager from app state
    let term_mgr = app.state::<crate::terminal::TerminalManager>();
    let history = term_mgr.history(&term_id).await;
    
    // Update status to running
    interactive::get_runner().await.update_status(&exec_id, interactive::InteractiveStatus::Running).await?;
    
    // Emit execution updated event so frontend can update immediately
    let _ = app.emit("recipe:execution_updated", serde_json::json!({
        "execution_id": exec_id,
        "status": "running",
    }));
    
    // Wait a bit for terminal to be ready
    tokio::time::sleep(tokio::time::Duration::from_millis(300)).await;
    
    eprintln!("[interactive_recipe] Starting execution {}", exec_id);
    
    // Simple marker for detecting completion
    const DONE_MARKER: &str = "___DOPPIO_DONE___";
    
    // Execute each step sequentially with shell prompt integration for completion detection
    for (index, step) in recipe.steps.iter().enumerate() {
        // Update current step
        interactive::get_runner().await.set_current_step(&exec_id, Some(step.id.clone())).await?;
        interactive::get_runner().await.update_step_status(&exec_id, &step.id, types::StepStatus::Running).await?;
        if let Err(e) = crate::terminal::history_step_start(&term_mgr, &term_id, &step.id, index).await {
            eprintln!("[interactive_recipe] history step start failed: {}", e);
        }
        let mut step_failed = false;
        let mut step_exit_code: Option<i32> = None;
        
        // Emit step started event
        let _ = app.emit("recipe:step_started", serde_json::json!({
            "execution_id": exec_id,
            "step_id": step.id,
            "step_index": index,
        }));
        
        // Get commands from the step operation
        let commands = extract_commands_from_step(step, &variables);
        
        if let Some(cmds) = commands {
            // Lock intervention briefly while sending commands (prevent user input interference)
            interactive::get_runner().await.lock_intervention(&exec_id).await?;
            let _ = app.emit("recipe:intervention_lock_changed", serde_json::json!({
                "execution_id": exec_id,
                "terminal_id": term_id,
                "locked": true,
            }));
            
            // Emit command sending event
            let _ = app.emit("recipe:command_sending", serde_json::json!({
                "execution_id": exec_id,
                "step_id": step.id,
                "command": cmds,
            }));
            
            // Check if we need to cd to a workdir
            let workdir_prefix = match &step.operation {
                types::Operation::RunCommands(op) => {
                    if let Some(workdir) = &op.workdir {
                        let workdir_interpolated = parser::interpolate(workdir, &variables);
                        if !workdir_interpolated.is_empty() {
                            // Simple shell escape: wrap in single quotes and escape single quotes
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
            
            // Send commands using heredoc with user's default shell
            // Uses $SHELL env var, falls back to bash if not set
            // Captures exit code and outputs it with the done marker
            let heredoc = format!(
                "${{SHELL:-bash}} <<'DOPPIO_EOF'\n{}{}\n__doppio_rc__=$?\necho '{}:'$__doppio_rc__\nDOPPIO_EOF\n",
                workdir_prefix,
                cmds.trim(),
                DONE_MARKER
            );
            crate::terminal::term_write_inner(&term_mgr, &term_id, &heredoc).await?;
            
            eprintln!("[interactive_recipe] Sent commands:\n{}", cmds);
            
            // Small delay to ensure commands are sent
            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
            
            // Unlock intervention to allow user input (password, confirmation, etc.)
            interactive::get_runner().await.unlock_intervention(&exec_id).await?;
            let _ = app.emit("recipe:intervention_lock_changed", serde_json::json!({
                "execution_id": exec_id,
                "terminal_id": term_id,
                "locked": false,
            }));
            
            // Update status to WaitingForInput while commands are running
            interactive::get_runner().await.update_status(&exec_id, interactive::InteractiveStatus::WaitingForInput).await?;
            
            // Wait for done marker with exit code (format: ___DOPPIO_DONE___:0)
            let exit_code = crate::terminal::wait_for_marker_with_exit_code(
                &term_mgr,
                &term_id,
                DONE_MARKER,
            ).await;
            step_exit_code = Some(exit_code);
            
            eprintln!("[interactive_recipe] Commands completed, exit_code: {}", exit_code);
            
            // Check if commands failed (non-zero exit code)
            if exit_code != 0 {
                // Commands failed
                let error_msg = format!("\r\n\x1b[31m✗ {} - exit code {}\x1b[0m\r\n", step.id, exit_code);
                crate::terminal::term_display(&app, &term_id, &error_msg, history.as_deref());
                
                step_failed = true;
                interactive::get_runner().await.update_step_status(&exec_id, &step.id, types::StepStatus::Failed).await?;
                let _ = app.emit("recipe:step_failed", serde_json::json!({
                    "execution_id": exec_id,
                    "step_id": step.id,
                    "error": format!("Step {} failed with exit code {}", step.id, exit_code),
                }));
                
                if !step.continue_on_failure {
                    interactive::get_runner().await.update_status(&exec_id, interactive::InteractiveStatus::Failed).await?;
                    let _ = app.emit("recipe:execution_failed", serde_json::json!({
                        "execution_id": exec_id,
                        "error": format!("Step {} failed with exit code {}", step.id, exit_code),
                    }));
                    if let Err(e) = crate::terminal::history_step_end(
                        &term_mgr,
                        &term_id,
                        &step.id,
                        index,
                        "failed",
                        step_exit_code,
                    )
                    .await
                    {
                        eprintln!("[interactive_recipe] history step end failed: {}", e);
                    }
                    return Err(AppError::command(format!("Step {} failed with exit code {}", step.id, exit_code)));
                }
            }
            
            // Restore running status
            interactive::get_runner().await.update_status(&exec_id, interactive::InteractiveStatus::Running).await?;
        } else {
            // Operation cannot be converted to terminal commands (e.g., GdriveMount, Transfer, etc.)
            // Execute it directly via backend and show progress in terminal
            eprintln!("[interactive_recipe] Executing operation via backend: {:?}", step.operation);
            
            // Get detailed operation description
            let op_desc = get_operation_description(&step.operation, &variables);
            
            // Show starting message with description directly to xterm.js (no shell echo)
            let start_msg = format!(
                "\r\n\x1b[1;36m▶ [Doppio] {}\x1b[0m\r\n\x1b[90m  {}\x1b[0m\r\n",
                step.id,
                op_desc.replace('\n', "\r\n  ")
            );
            crate::terminal::term_display(&app, &term_id, &start_msg, history.as_deref());
            // Progress reporter to keep sidebar + terminal updated
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
                    let _ = runner.set_step_progress(&exec_id, &step_id, Some(message.clone())).await;
                    let _ = app_handle_inner.emit("recipe:step_progress", serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step_id,
                        "progress": message,
                    }));
                });
                let live_msg = format!("\x1b[90m  → {}\x1b[0m\r\n", msg);
                crate::terminal::term_display(&app_handle, &term_id_clone, &live_msg, history_for_progress.as_deref());
            });
            // Persist initial progress text
            progress_cb(&op_desc.lines().next().unwrap_or(&op_desc));
            
            // Execute the operation using the execution engine
            match execution::execute_step(&step.operation, &variables, Some(progress_cb.clone())).await {
                Ok(Some(output)) => {
                    // Show success with output directly to xterm.js
                    let formatted_output = output.replace('\n', "\r\n");
                    let success_msg = format!("\x1b[32m✓ {}\x1b[0m\r\n{}\r\n", step.id, formatted_output);
                    crate::terminal::term_display(&app, &term_id, &success_msg, history.as_deref());
                }
                Ok(None) => {
                    // Show success without output
                    let success_msg = format!("\x1b[32m✓ {} completed\x1b[0m\r\n", step.id);
                    crate::terminal::term_display(&app, &term_id, &success_msg, history.as_deref());
                }
                Err(e) => {
                    // Show error directly to xterm.js
                    let error_str = e.to_string().replace('\n', "\r\n  ");
                    let error_msg = format!("\x1b[31m✗ {} failed:\x1b[0m\r\n  \x1b[31m{}\x1b[0m\r\n", step.id, error_str);
                    crate::terminal::term_display(&app, &term_id, &error_msg, history.as_deref());
                    
                    step_failed = true;
                    // Update step status to failed
                    interactive::get_runner().await.update_step_status(&exec_id, &step.id, types::StepStatus::Failed).await?;
                    let _ = app.emit("recipe:step_failed", serde_json::json!({
                        "execution_id": exec_id,
                        "step_id": step.id,
                        "error": e.to_string(),
                    }));
                    
                    // Check if step should continue on failure
                    if !step.continue_on_failure {
                        // Stop execution
                        interactive::get_runner().await.update_status(&exec_id, interactive::InteractiveStatus::Failed).await?;
                        let _ = app.emit("recipe:execution_failed", serde_json::json!({
                            "execution_id": exec_id,
                            "error": e.to_string(),
                        }));
                        if let Err(err) = crate::terminal::history_step_end(
                            &term_mgr,
                            &term_id,
                            &step.id,
                            index,
                            "failed",
                            step_exit_code,
                        )
                        .await
                        {
                            eprintln!("[interactive_recipe] history step end failed: {}", err);
                        }
                        return Err(e);
                    }
                }
            }
            
            // Clear progress on completion/failure
            let exec_id_clone = exec_id.clone();
            let step_id_clone = step.id.clone();
            let app_handle = app.clone();
            tauri::async_runtime::spawn(async move {
                let runner = interactive::get_runner().await;
                let _ = runner.set_step_progress(&exec_id_clone, &step_id_clone, None).await;
                let _ = app_handle.emit("recipe:step_progress", serde_json::json!({
                    "execution_id": exec_id_clone,
                    "step_id": step_id_clone,
                    "progress": serde_json::Value::Null,
                }));
            });
        }
        
        if !step_failed {
            // Mark step as complete
            interactive::get_runner().await.update_step_status(&exec_id, &step.id, types::StepStatus::Success).await?;
            eprintln!("[interactive_recipe] Step {} completed", step.id);
            let _ = app.emit("recipe:step_completed", serde_json::json!({
                "execution_id": exec_id,
                "step_id": step.id,
            }));
        }

        let status = if step_failed { "failed" } else { "success" };
        if let Err(e) = crate::terminal::history_step_end(
            &term_mgr,
            &term_id,
            &step.id,
            index,
            status,
            step_exit_code,
        )
        .await
        {
            eprintln!("[interactive_recipe] history step end failed: {}", e);
        }
    }
    
    // All steps completed
    interactive::get_runner().await.set_current_step(&exec_id, None).await?;
    interactive::get_runner().await.update_status(&exec_id, interactive::InteractiveStatus::Completed).await?;
    
    // Emit completion event
    let _ = app.emit("recipe:execution_completed", serde_json::json!({
        "execution_id": exec_id,
    }));
    
    Ok(())
}

/// Extract commands from a step's operation
/// Returns Some(commands) if the operation can be executed as terminal commands
/// Returns None if the operation must be executed via Rust backend
fn extract_commands_from_step(step: &types::Step, variables: &HashMap<String, String>) -> Option<String> {
    fn interpolate(s: &str, vars: &HashMap<String, String>) -> String {
        let mut result = s.to_string();
        for (key, value) in vars {
            result = result.replace(&format!("${{{}}}", key), value);
        }
        result
    }
    
    match &step.operation {
        types::Operation::RunCommands(op) => {
            Some(interpolate(&op.commands, variables))
        }
        types::Operation::SshCommand(op) => {
            Some(interpolate(&op.command, variables))
        }
        types::Operation::GitClone(op) => {
            let repo = interpolate(&op.repo_url, variables);
            let dest = interpolate(&op.destination, variables);
            
            // If auth_token is provided, use backend execution for security
            if op.auth_token.as_ref().map(|t| !interpolate(t, variables).is_empty()).unwrap_or(false) {
                return None;
            }
            
            let mut cmd = format!("git clone {}", repo);
            if let Some(b) = &op.branch {
                cmd.push_str(&format!(" -b {}", interpolate(b, variables)));
            }
            if let Some(d) = op.depth {
                cmd.push_str(&format!(" --depth {}", d));
            }
            cmd.push_str(&format!(" {}", dest));
            Some(cmd)
        }
        types::Operation::HfDownload(op) => {
            let repo_id = interpolate(&op.repo_id, variables);
            let dest = interpolate(&op.destination, variables);
            let repo_type = match op.repo_type {
                types::HfRepoType::Model => "model",
                types::HfRepoType::Dataset => "dataset",
                types::HfRepoType::Space => "space",
            };
            
            let mut cmd = format!("huggingface-cli download {} --local-dir {} --repo-type {}", 
                repo_id, dest, repo_type);
            
            if let Some(revision) = &op.revision {
                cmd.push_str(&format!(" --revision {}", interpolate(revision, variables)));
            }
            
            for file in &op.files {
                cmd.push_str(&format!(" --include {}", file));
            }
            
            // If auth token is set, prepend HF_TOKEN env var
            if let Some(token) = &op.auth_token {
                let token_val = interpolate(token, variables);
                if !token_val.is_empty() {
                    cmd = format!("HF_TOKEN='{}' {}", token_val, cmd);
                }
            }
            
            Some(cmd)
        }
        types::Operation::TmuxNew(op) => {
            let session = interpolate(&op.session_name, variables);
            if let Some(cmd) = &op.command {
                Some(format!("tmux new-session -d -s {} '{}'", session, interpolate(cmd, variables)))
            } else {
                Some(format!("tmux new-session -d -s {}", session))
            }
        }
        types::Operation::TmuxSend(op) => {
            let session = interpolate(&op.session_name, variables);
            let keys = interpolate(&op.keys, variables);
            Some(format!("tmux send-keys -t {} '{}' Enter", session, keys))
        }
        types::Operation::TmuxKill(op) => {
            let session = interpolate(&op.session_name, variables);
            Some(format!("tmux kill-session -t {}", session))
        }
        types::Operation::TmuxCapture(op) => {
            let session = interpolate(&op.session_name, variables);
            let lines = op.lines.unwrap_or(100);
            Some(format!("tmux capture-pane -t {} -p -S -{}", session, lines))
        }
        types::Operation::Sleep(op) => {
            Some(format!("sleep {}", op.duration_secs))
        }
        types::Operation::Notify(op) => {
            let msg = op.message.as_ref().map(|m| interpolate(m, variables)).unwrap_or_default();
            let level_str = format!("{:?}", op.level).to_lowercase();
            Some(format!("echo '[{}] {}: {}'", level_str, interpolate(&op.title, variables), msg))
        }
        // Operations that must use backend execution:
        // GdriveMount/Unmount, Transfer, RsyncUpload/Download, VastStart/Stop/Destroy,
        // WaitCondition, HttpRequest, SetVar, GetValue, Assert, Group
        _ => None,
    }
}

/// Get a human-readable description of an operation for display
fn get_operation_description(operation: &types::Operation, variables: &HashMap<String, String>) -> String {
    fn interpolate(s: &str, vars: &HashMap<String, String>) -> String {
        let mut result = s.to_string();
        for (key, value) in vars {
            result = result.replace(&format!("${{{}}}", key), value);
        }
        result
    }
    
    match operation {
        types::Operation::GdriveMount(op) => {
            let mount_path = if op.mount_path.is_empty() {
                "/content/drive/MyDrive".to_string()
            } else {
                interpolate(&op.mount_path, variables)
            };
            format!(
                "Mounting Google Drive at {}\n→ Installing rclone if needed\n→ Configuring OAuth credentials\n→ Starting rclone mount\n→ Verifying mount",
                mount_path
            )
        }
        types::Operation::GdriveUnmount(op) => {
            format!("Unmounting Google Drive from {}", interpolate(&op.mount_path, variables))
        }
        types::Operation::Transfer(op) => {
            let src = match &op.source {
                types::TransferEndpoint::Local { path } => format!("local:{}", interpolate(path, variables)),
                types::TransferEndpoint::Host { host_id, path } => {
                    let host = host_id.as_ref().map(|h| interpolate(h, variables)).unwrap_or_else(|| "target".to_string());
                    format!("{}:{}", host, interpolate(path, variables))
                }
                types::TransferEndpoint::Storage { storage_id, path } => {
                    format!("storage:{}:{}", interpolate(storage_id, variables), interpolate(path, variables))
                }
            };
            let dst = match &op.destination {
                types::TransferEndpoint::Local { path } => format!("local:{}", interpolate(path, variables)),
                types::TransferEndpoint::Host { host_id, path } => {
                    let host = host_id.as_ref().map(|h| interpolate(h, variables)).unwrap_or_else(|| "target".to_string());
                    format!("{}:{}", host, interpolate(path, variables))
                }
                types::TransferEndpoint::Storage { storage_id, path } => {
                    format!("storage:{}:{}", interpolate(storage_id, variables), interpolate(path, variables))
                }
            };
            format!("Transferring files\n→ Source: {}\n→ Destination: {}", src, dst)
        }
        types::Operation::RsyncUpload(op) => {
            format!("Uploading via rsync\n→ Local: {}\n→ Remote: {}", 
                interpolate(&op.local_path, variables),
                interpolate(&op.remote_path, variables))
        }
        types::Operation::RsyncDownload(op) => {
            format!("Downloading via rsync\n→ Remote: {}\n→ Local: {}",
                interpolate(&op.remote_path, variables),
                interpolate(&op.local_path, variables))
        }
        types::Operation::GitClone(op) => {
            let repo = interpolate(&op.repo_url, variables);
            let dest = interpolate(&op.destination, variables);
            let mut desc = format!("Cloning git repository\n→ Repo: {}\n→ Destination: {}", repo, dest);
            if let Some(b) = &op.branch {
                desc.push_str(&format!("\n→ Branch: {}", interpolate(b, variables)));
            }
            if op.auth_token.is_some() {
                desc.push_str("\n→ Using auth token");
            }
            desc
        }
        types::Operation::HfDownload(op) => {
            let repo_id = interpolate(&op.repo_id, variables);
            let dest = interpolate(&op.destination, variables);
            format!("Downloading from HuggingFace\n→ Repo: {}\n→ Destination: {}", repo_id, dest)
        }
        types::Operation::VastStart(op) => format!("Starting Vast.ai instance #{}", op.instance_id),
        types::Operation::VastStop(op) => format!("Stopping Vast.ai instance #{}", op.instance_id),
        types::Operation::VastDestroy(op) => format!("Destroying Vast.ai instance #{}", op.instance_id),
        types::Operation::WaitCondition(op) => format!("Waiting for condition (timeout: {}s)", op.timeout_secs),
        types::Operation::HttpRequest(op) => format!("{:?} {}", op.method, interpolate(&op.url, variables)),
        types::Operation::SetVar(_) => "Setting variable".to_string(),
        types::Operation::GetValue(_) => "Getting value".to_string(),
        types::Operation::Assert(_) => "Checking assertion".to_string(),
        _ => "Executing operation".to_string(),
    }
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
    
    // Check if intervention is locked
    if execution.intervention_locked {
        return Err(AppError::command("Intervention is currently locked - script is sending commands"));
    }
    
    // Write to the terminal
    crate::terminal::term_write_inner(&term_mgr, &execution.terminal_id, &data).await
}

/// Send interrupt (Ctrl+C) to an interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_interrupt(
    term_mgr: State<'_, crate::terminal::TerminalManager>,
    execution_id: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    let execution = runner.get_execution(&execution_id).await?;
    
    // Send Ctrl+C (ASCII 0x03)
    crate::terminal::term_write_inner(&term_mgr, &execution.terminal_id, "\x03").await
}

/// Lock/unlock intervention for an interactive execution
#[tauri::command]
pub async fn recipe_interactive_lock(
    execution_id: String,
    locked: bool,
) -> Result<(), AppError> {
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
pub async fn recipe_interactive_pause(
    execution_id: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    runner.update_status(&execution_id, interactive::InteractiveStatus::Paused).await
}

/// Resume a paused interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_resume(
    execution_id: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    runner.update_status(&execution_id, interactive::InteractiveStatus::Running).await
}

/// Cancel an interactive recipe execution
#[tauri::command]
pub async fn recipe_interactive_cancel(
    execution_id: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    runner.update_status(&execution_id, interactive::InteractiveStatus::Cancelled).await
}

/// Mark all steps as complete and finish execution
#[tauri::command]
pub async fn recipe_interactive_mark_complete(
    execution_id: String,
) -> Result<(), AppError> {
    let runner = interactive::get_runner().await;
    
    // Get execution and mark all running steps as success
    let execution = runner.get_execution(&execution_id).await?;
    for step in &execution.steps {
        if step.status == types::StepStatus::Running {
            runner.update_step_status(&execution_id, &step.step_id, types::StepStatus::Success).await?;
        }
    }
    
    // Mark execution as completed
    runner.set_current_step(&execution_id, None).await?;
    runner.update_status(&execution_id, interactive::InteractiveStatus::Completed).await
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
    
    // Lock intervention while sending command
    runner.lock_intervention(&execution_id).await?;
    
    // Emit event that we're sending a command
    let _ = app.emit("recipe:command_sending", serde_json::json!({
        "execution_id": execution_id,
        "step_id": step_id,
        "command": command,
    }));
    
    // Send the command with Enter
    let cmd_with_newline = format!("{}\n", command);
    crate::terminal::term_write_inner(&term_mgr, &execution.terminal_id, &cmd_with_newline).await?;
    
    // Emit event that command was sent
    let _ = app.emit("recipe:command_sent", serde_json::json!({
        "execution_id": execution_id,
        "step_id": step_id,
        "command": command,
    }));
    
    // Unlock intervention after a small delay to let the command be processed
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
    runner.unlock_intervention(&execution_id).await?;
    
    Ok(())
}
