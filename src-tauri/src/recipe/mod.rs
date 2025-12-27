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
    
    let runner = interactive::get_runner().await;
    
    // Get terminal manager from app state
    let term_mgr = app.state::<crate::terminal::TerminalManager>();
    
    // Update status to running
    runner.update_status(&exec_id, interactive::InteractiveStatus::Running).await?;
    
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
        runner.set_current_step(&exec_id, Some(step.id.clone())).await?;
        runner.update_step_status(&exec_id, &step.id, types::StepStatus::Running).await?;
        
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
            runner.lock_intervention(&exec_id).await?;
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
            
            // Send commands using heredoc with user's default shell
            // Uses $SHELL env var, falls back to bash if not set
            let heredoc = format!(
                "${{SHELL:-bash}} <<'DOPPIO_EOF'\n{}\necho '{}'\nDOPPIO_EOF\n",
                cmds.trim(),
                DONE_MARKER
            );
            crate::terminal::term_write_inner(&term_mgr, &term_id, &heredoc).await?;
            
            eprintln!("[interactive_recipe] Sent commands:\n{}", cmds);
            
            // Small delay to ensure commands are sent
            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
            
            // Unlock intervention to allow user input (password, confirmation, etc.)
            runner.unlock_intervention(&exec_id).await?;
            let _ = app.emit("recipe:intervention_lock_changed", serde_json::json!({
                "execution_id": exec_id,
                "terminal_id": term_id,
                "locked": false,
            }));
            
            // Update status to WaitingForInput while commands are running
            runner.update_status(&exec_id, interactive::InteractiveStatus::WaitingForInput).await?;
            
            // Wait for the marker to appear (commands completed)
            // No timeout - wait indefinitely until commands finish
            crate::terminal::wait_for_marker(
                &term_mgr,
                &term_id,
                DONE_MARKER,
            ).await;
            
            eprintln!("[interactive_recipe] Commands completed");
            
            // Restore running status
            runner.update_status(&exec_id, interactive::InteractiveStatus::Running).await?;
        }
        
        // Mark step as complete
        runner.update_step_status(&exec_id, &step.id, types::StepStatus::Success).await?;
        eprintln!("[interactive_recipe] Step {} completed", step.id);
        let _ = app.emit("recipe:step_completed", serde_json::json!({
            "execution_id": exec_id,
            "step_id": step.id,
        }));
    }
    
    // All steps completed
    runner.set_current_step(&exec_id, None).await?;
    runner.update_status(&exec_id, interactive::InteractiveStatus::Completed).await?;
    
    // Emit completion event
    let _ = app.emit("recipe:execution_completed", serde_json::json!({
        "execution_id": exec_id,
    }));
    
    Ok(())
}

/// Extract commands from a step's operation
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
        types::Operation::Sleep(op) => {
            Some(format!("sleep {}", op.duration_secs))
        }
        types::Operation::SetVar(_) | types::Operation::GetValue(_) | types::Operation::Assert(_) => {
            // These don't produce terminal commands
            None
        }
        types::Operation::Notify(op) => {
            // Just echo the notification
            let msg = op.message.as_ref().map(|m| interpolate(m, variables)).unwrap_or_default();
            let level_str = format!("{:?}", op.level).to_lowercase();
            Some(format!("echo '[{}] {}: {}'", level_str, interpolate(&op.title, variables), msg))
        }
        _ => {
            // For other operations, we don't have a simple command equivalent
            // They would need full execution support
            None
        }
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

