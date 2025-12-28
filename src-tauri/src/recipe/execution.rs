//! Recipe execution engine
//!
//! This module implements the DAG-based execution engine that runs recipes
//! with proper dependency resolution and parallel execution.

use std::collections::{HashMap, HashSet};

use tokio::sync::{mpsc, RwLock, Mutex};
use uuid::Uuid;

use crate::error::AppError;
use super::types::*;
use super::parser::interpolate;
use super::operations;

// ============================================================
// Execution Engine
// ============================================================

/// Manages recipe executions
pub struct RecipeRunner {
    /// Active executions
    executions: RwLock<HashMap<String, Arc<ExecutionState>>>,
    /// Event sender for execution events
    event_tx: Option<mpsc::UnboundedSender<RecipeEvent>>,
}

/// Internal execution state with control channels
struct ExecutionState {
    execution: RwLock<Execution>,
    recipe: Recipe,
    /// Control channel for pause/resume/cancel
    control_tx: mpsc::Sender<ControlSignal>,
    /// Flag to track if execution is active
    active: RwLock<bool>,
}

/// Control signals for execution
#[derive(Debug, Clone)]
pub enum ControlSignal {
    Pause,
    Resume,
    Cancel,
    RetryStep(String),
    SkipStep(String),
}

/// Events emitted during execution
#[derive(Debug, Clone, serde::Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RecipeEvent {
    ExecutionStarted { execution_id: String },
    StepStarted { execution_id: String, step_id: String },
    StepProgress { execution_id: String, step_id: String, progress: StepProgress },
    StepCompleted { execution_id: String, step_id: String, output: Option<String> },
    StepFailed { execution_id: String, step_id: String, error: String },
    StepRetrying { execution_id: String, step_id: String, attempt: u32 },
    StepSkipped { execution_id: String, step_id: String },
    ExecutionPaused { execution_id: String },
    ExecutionResumed { execution_id: String },
    ExecutionCompleted { execution_id: String },
    ExecutionFailed { execution_id: String, error: String },
    ExecutionCancelled { execution_id: String },
}

impl Default for RecipeRunner {
    fn default() -> Self {
        Self::new()
    }
}

impl RecipeRunner {
    pub fn new() -> Self {
        Self {
            executions: RwLock::new(HashMap::new()),
            event_tx: None,
        }
    }
    
    pub fn with_event_sender(mut self, tx: mpsc::UnboundedSender<RecipeEvent>) -> Self {
        self.event_tx = Some(tx);
        self
    }
    
    fn emit(&self, event: RecipeEvent) {
        if let Some(tx) = &self.event_tx {
            let _ = tx.send(event);
        }
    }
    
    /// Start a new recipe execution
    pub async fn run(
        &self,
        recipe: Recipe,
        recipe_path: String,
        variable_overrides: HashMap<String, String>,
    ) -> Result<String, AppError> {
        let id = Uuid::new_v4().to_string();
        let now = chrono::Utc::now().to_rfc3339();
        
        // Merge variables
        let mut variables = recipe.variables.clone();
        for (k, v) in variable_overrides {
            variables.insert(k, v);
        }
        
        // Initialize step executions
        let steps: Vec<StepExecution> = recipe.steps.iter().map(|s| StepExecution {
            step_id: s.id.clone(),
            status: StepStatus::Pending,
            started_at: None,
            completed_at: None,
            output: None,
            error: None,
            retry_attempt: 0,
            progress: None,
        }).collect();
        
        let execution = Execution {
            id: id.clone(),
            recipe_path,
            recipe_name: recipe.name.clone(),
            status: ExecutionStatus::Pending,
            variables,
            steps,
            created_at: now.clone(),
            started_at: None,
            completed_at: None,
            error: None,
        };
        
        // Create control channel
        let (control_tx, control_rx) = mpsc::channel(16);
        
        let state = Arc::new(ExecutionState {
            execution: RwLock::new(execution),
            recipe,
            control_tx,
            active: RwLock::new(true),
        });
        
        // Store execution
        {
            let mut execs = self.executions.write().await;
            execs.insert(id.clone(), Arc::clone(&state));
        }
        
        // Clone what we need for the async task
        let exec_id = id.clone();
        let event_tx = self.event_tx.clone();
        
        // Spawn execution task
        tokio::spawn(async move {
            let result = execute_recipe(state.clone(), control_rx, event_tx.clone()).await;
            
            // Update final status
            let mut exec = state.execution.write().await;
            exec.completed_at = Some(chrono::Utc::now().to_rfc3339());
            
            match result {
                Ok(()) => {
                    exec.status = ExecutionStatus::Completed;
                    if let Some(tx) = &event_tx {
                        let _ = tx.send(RecipeEvent::ExecutionCompleted { 
                            execution_id: exec_id 
                        });
                    }
                }
                Err(e) => {
                    exec.status = ExecutionStatus::Failed;
                    exec.error = Some(e.to_string());
                    if let Some(tx) = &event_tx {
                        let _ = tx.send(RecipeEvent::ExecutionFailed { 
                            execution_id: exec_id, 
                            error: e.to_string() 
                        });
                    }
                }
            }
            
            *state.active.write().await = false;
        });
        
        self.emit(RecipeEvent::ExecutionStarted { execution_id: id.clone() });
        
        Ok(id)
    }
    
    /// Get execution by ID
    pub async fn get_execution(&self, id: &str) -> Result<Execution, AppError> {
        let state = {
            let execs = self.executions.read().await;
            execs.get(id)
                .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?
                .clone()
        };
        let execution = state.execution.read().await.clone();
        Ok(execution)
    }
    
    /// List all executions
    pub async fn list_executions(&self) -> Vec<ExecutionSummary> {
        let execs = self.executions.read().await;
        let mut summaries = Vec::new();
        
        for state in execs.values() {
            let exec = state.execution.read().await;
            summaries.push(ExecutionSummary::from(&*exec));
        }
        
        // Sort by created_at descending
        summaries.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        summaries
    }
    
    /// Pause an execution
    pub async fn pause(&self, id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        state.control_tx.send(ControlSignal::Pause).await
            .map_err(|_| AppError::command("Failed to send pause signal"))?;
        
        self.emit(RecipeEvent::ExecutionPaused { execution_id: id.to_string() });
        Ok(())
    }
    
    /// Resume an execution
    pub async fn resume(&self, id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        state.control_tx.send(ControlSignal::Resume).await
            .map_err(|_| AppError::command("Failed to send resume signal"))?;
        
        self.emit(RecipeEvent::ExecutionResumed { execution_id: id.to_string() });
        Ok(())
    }
    
    /// Cancel an execution
    pub async fn cancel(&self, id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        state.control_tx.send(ControlSignal::Cancel).await
            .map_err(|_| AppError::command("Failed to send cancel signal"))?;
        
        self.emit(RecipeEvent::ExecutionCancelled { execution_id: id.to_string() });
        Ok(())
    }
    
    /// Retry a failed step
    pub async fn retry_step(&self, id: &str, step_id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        state.control_tx.send(ControlSignal::RetryStep(step_id.to_string())).await
            .map_err(|_| AppError::command("Failed to send retry signal"))?;
        
        Ok(())
    }
    
    /// Skip a step
    pub async fn skip_step(&self, id: &str, step_id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        state.control_tx.send(ControlSignal::SkipStep(step_id.to_string())).await
            .map_err(|_| AppError::command("Failed to send skip signal"))?;
        
        Ok(())
    }
}

/// Main execution loop
async fn execute_recipe(
    state: Arc<ExecutionState>,
    mut control_rx: mpsc::Receiver<ControlSignal>,
    event_tx: Option<mpsc::UnboundedSender<RecipeEvent>>,
) -> Result<(), AppError> {
    // Update status to running
    {
        let mut exec = state.execution.write().await;
        exec.status = ExecutionStatus::Running;
        exec.started_at = Some(chrono::Utc::now().to_rfc3339());
    }
    
    let execution_id = state.execution.read().await.id.clone();
    
    // Build dependency graph
    let step_order = compute_execution_order(&state.recipe.steps)?;
    
    // Track completed steps
    let completed: Arc<Mutex<HashSet<String>>> = Arc::new(Mutex::new(HashSet::new()));
    
    // Paused flag
    let paused = Arc::new(RwLock::new(false));
    let cancelled = Arc::new(RwLock::new(false));
    
    // Process steps
    let mut pending_steps: HashSet<String> = step_order.into_iter().collect();
    
    loop {
        // Check for control signals (non-blocking)
        while let Ok(signal) = control_rx.try_recv() {
            match signal {
                ControlSignal::Pause => {
                    *paused.write().await = true;
                    let mut exec = state.execution.write().await;
                    exec.status = ExecutionStatus::Paused;
                }
                ControlSignal::Resume => {
                    *paused.write().await = false;
                    let mut exec = state.execution.write().await;
                    exec.status = ExecutionStatus::Running;
                }
                ControlSignal::Cancel => {
                    *cancelled.write().await = true;
                    let mut exec = state.execution.write().await;
                    exec.status = ExecutionStatus::Cancelled;
                    return Ok(());
                }
                ControlSignal::RetryStep(step_id) => {
                    // Re-add step to pending
                    pending_steps.insert(step_id.clone());
                    // Remove from completed
                    completed.lock().await.remove(&step_id);
                    // Update status
                    let mut exec = state.execution.write().await;
                    if let Some(step_exec) = exec.steps.iter_mut().find(|s| s.step_id == step_id) {
                        step_exec.status = StepStatus::Pending;
                        step_exec.error = None;
                    }
                }
                ControlSignal::SkipStep(step_id) => {
                    pending_steps.remove(&step_id);
                    completed.lock().await.insert(step_id.clone());
                    // Update status
                    let mut exec = state.execution.write().await;
                    if let Some(step_exec) = exec.steps.iter_mut().find(|s| s.step_id == step_id) {
                        step_exec.status = StepStatus::Skipped;
                    }
                    if let Some(tx) = &event_tx {
                        let _ = tx.send(RecipeEvent::StepSkipped { 
                            execution_id: execution_id.clone(), 
                            step_id 
                        });
                    }
                }
            }
        }
        
        // If paused, wait a bit
        if *paused.read().await {
            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
            continue;
        }
        
        // Check if all steps are done
        if pending_steps.is_empty() {
            break;
        }
        
        // Find steps that can run (all dependencies satisfied)
        let completed_set = completed.lock().await.clone();
        let runnable: Vec<String> = pending_steps.iter()
            .filter(|step_id| {
                let step = state.recipe.steps.iter().find(|s| &s.id == *step_id).unwrap();
                step.depends_on.iter().all(|dep| completed_set.contains(dep))
            })
            .cloned()
            .collect();
        
        if runnable.is_empty() && !pending_steps.is_empty() {
            // This shouldn't happen if validation passed (no cycles)
            return Err(AppError::command("Deadlock: no runnable steps but pending steps remain"));
        }
        
        // Execute runnable steps in parallel
        let mut handles = Vec::new();
        
        for step_id in runnable {
            pending_steps.remove(&step_id);
            
            let state = Arc::clone(&state);
            let completed = Arc::clone(&completed);
            let cancelled = Arc::clone(&cancelled);
            let event_tx = event_tx.clone();
            let exec_id = execution_id.clone();
            
            let handle = tokio::spawn(async move {
                // Check if cancelled
                if *cancelled.read().await {
                    return;
                }
                
                let step = state.recipe.steps.iter()
                    .find(|s| s.id == step_id)
                    .unwrap()
                    .clone();
                
                // Update status to running
                {
                    let mut exec = state.execution.write().await;
                    if let Some(step_exec) = exec.steps.iter_mut().find(|s| s.step_id == step_id) {
                        step_exec.status = StepStatus::Running;
                        step_exec.started_at = Some(chrono::Utc::now().to_rfc3339());
                    }
                }
                
                if let Some(tx) = &event_tx {
                    let _ = tx.send(RecipeEvent::StepStarted { 
                        execution_id: exec_id.clone(), 
                        step_id: step_id.clone() 
                    });
                }
                
                // Get current variables
                let variables = state.execution.read().await.variables.clone();
                
                // Execute step with retry logic
                let result = execute_step_with_retry(&step, &variables, &event_tx, &exec_id).await;
                
                // Update status
                {
                    let mut exec = state.execution.write().await;
                    if let Some(step_exec) = exec.steps.iter_mut().find(|s| s.step_id == step_id) {
                        step_exec.completed_at = Some(chrono::Utc::now().to_rfc3339());
                        
                        match &result {
                            Ok(output) => {
                                step_exec.status = StepStatus::Success;
                                step_exec.output = output.clone();
                                
                                if let Some(tx) = &event_tx {
                                    let _ = tx.send(RecipeEvent::StepCompleted { 
                                        execution_id: exec_id.clone(), 
                                        step_id: step_id.clone(),
                                        output: output.clone(),
                                    });
                                }
                            }
                            Err(e) => {
                                if step.continue_on_failure {
                                    step_exec.status = StepStatus::Failed;
                                    step_exec.error = Some(e.to_string());
                                } else {
                                    step_exec.status = StepStatus::Failed;
                                    step_exec.error = Some(e.to_string());
                                }
                                
                                if let Some(tx) = &event_tx {
                                    let _ = tx.send(RecipeEvent::StepFailed { 
                                        execution_id: exec_id.clone(), 
                                        step_id: step_id.clone(),
                                        error: e.to_string(),
                                    });
                                }
                            }
                        }
                    }
                }
                
                // Mark as completed (or failed)
                match result {
                    Ok(_) => {
                        completed.lock().await.insert(step_id);
                    }
                    Err(_) if step.continue_on_failure => {
                        // Allow downstream steps to proceed
                        completed.lock().await.insert(step_id);
                    }
                    Err(_) => {
                        // Don't mark as completed, this will cause a "deadlock" detection
                        // which will end the execution with an error
                    }
                }
            });
            
            handles.push(handle);
        }
        
        // Wait for all parallel steps to complete
        for handle in handles {
            let _ = handle.await;
        }
        
        // Short sleep to prevent busy loop
        tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
    }
    
    Ok(())
}

/// Execute a step with retry logic
async fn execute_step_with_retry(
    step: &Step,
    variables: &HashMap<String, String>,
    event_tx: &Option<mpsc::UnboundedSender<RecipeEvent>>,
    exec_id: &str,
) -> Result<Option<String>, AppError> {
    let max_attempts = step.retry.as_ref().map(|r| r.max_attempts).unwrap_or(1);
    let delay_secs = step.retry.as_ref().map(|r| r.delay_secs).unwrap_or(5);
    let backoff = step.retry.as_ref().and_then(|r| r.backoff_multiplier).unwrap_or(1.0);
    
    let mut attempt = 0;
    let mut delay = delay_secs;
    
    loop {
        attempt += 1;
        
        // Check condition if present
        if let Some(condition) = &step.condition {
            let cond_value = interpolate(condition, variables);
            if cond_value != "true" && cond_value != "1" {
                return Ok(None); // Skip this step
            }
        }
        
        let result = execute_step(&step.operation, variables, None).await;
        
        match result {
            Ok(output) => return Ok(output),
            Err(e) if attempt < max_attempts => {
                // Emit retry event
                if let Some(tx) = event_tx {
                    let _ = tx.send(RecipeEvent::StepRetrying { 
                        execution_id: exec_id.to_string(), 
                        step_id: step.id.clone(),
                        attempt,
                    });
                }
                
                // Wait before retry
                tokio::time::sleep(tokio::time::Duration::from_secs(delay)).await;
                delay = (delay as f64 * backoff) as u64;
            }
            Err(e) => return Err(e),
        }
    }
}

/// Execute a single step operation
/// Public so it can be used by interactive recipe execution
pub async fn execute_step(
    operation: &Operation,
    variables: &HashMap<String, String>,
    progress: Option<Arc<dyn Fn(&str) + Send + Sync>>,
) -> Result<Option<String>, AppError> {
    match operation {
        // New unified run_commands operation
        Operation::RunCommands(op) => {
            // Resolve host_id: use explicit host_id, or fall back to ${target} variable
            let target = op.host_id.as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;
            
            let commands = interpolate(&op.commands, variables);
            let workdir = op.workdir.as_ref().map(|w| interpolate(w, variables));
            
            // Check if this is local execution
            let is_local = operations::ssh::is_local_target(&target);
            
            match op.tmux_mode {
                crate::recipe::types::TmuxMode::None => {
                    if is_local {
                        // Execute commands locally (no SSH)
                        operations::ssh::execute_local_command(&commands, workdir.as_deref(), &op.env).await
                    } else {
                        // Execute commands directly via SSH (blocking)
                        operations::ssh::execute_command(&target, &commands, workdir.as_deref(), &op.env).await
                    }
                }
                crate::recipe::types::TmuxMode::New => {
                    if is_local {
                        return Err(AppError::command("Tmux mode 'new' is not supported for local execution"));
                    }
                    // Create a new tmux session and run commands
                    let session_name = op.session_name.as_ref()
                        .map(|s| interpolate(s, variables))
                        .unwrap_or_else(|| "recipe".to_string());
                    operations::tmux::new_session(&target, &session_name, Some(&commands), workdir.as_deref()).await?;
                    Ok(None)
                }
                crate::recipe::types::TmuxMode::Existing => {
                    if is_local {
                        return Err(AppError::command("Tmux mode 'existing' is not supported for local execution"));
                    }
                    // Send commands to existing tmux session
                    let session_name = op.session_name.as_ref()
                        .map(|s| interpolate(s, variables))
                        .ok_or_else(|| AppError::command("session_name required for existing tmux mode"))?;
                    // Send each line as a command
                    for line in commands.lines() {
                        let line = line.trim();
                        if !line.is_empty() && !line.starts_with('#') {
                            let keys = format!("{} Enter", line);
                            operations::tmux::send_keys(&target, &session_name, &keys).await?;
                        }
                    }
                    Ok(None)
                }
            }
        }
        
        // New unified transfer operation
        Operation::Transfer(op) => {
            operations::transfer::execute(op, variables).await
        }
        
        // Git clone operation
        Operation::GitClone(op) => {
            let target = op.host_id.as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;
            
            let is_local = operations::ssh::is_local_target(&target);
            
            let repo_url = interpolate(&op.repo_url, variables);
            let destination = interpolate(&op.destination, variables);
            let branch = op.branch.as_ref().map(|b| interpolate(b, variables));
            // Interpolate auth_token and filter out empty strings
            let auth_token = op.auth_token.as_ref()
                .map(|t| interpolate(t, variables))
                .filter(|t| !t.is_empty());
            
            eprintln!("[git_clone] repo_url={}, auth_token={:?}, local={}", repo_url, auth_token.as_ref().map(|_| "[REDACTED]"), is_local);
            
            // First, add GitHub/GitLab/Bitbucket host keys to known_hosts to avoid "Host key verification failed"
            let add_host_keys = r#"mkdir -p ~/.ssh && chmod 700 ~/.ssh && ssh-keyscan -t ed25519,rsa github.com gitlab.com bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null"#;
            if is_local {
                let _ = operations::ssh::execute_local_command(add_host_keys, None, &std::collections::HashMap::new()).await;
            } else {
                let _ = operations::ssh::execute_command(&target, add_host_keys, None, &std::collections::HashMap::new()).await;
            }
            
            // Check if destination already exists and move it to a backup path
            // Strip trailing slash for consistent handling
            let dest_clean = destination.trim_end_matches('/');
            let check_and_backup = format!(
                r#"dest="{}"; if [ -e "$dest" ]; then backup="${{dest}}.bak.$(date +%Y%m%d_%H%M%S)"; echo "Path exists, moving to $backup"; mv "$dest" "$backup"; fi"#,
                dest_clean
            );
            eprintln!("[git_clone] Running backup check: {}", check_and_backup);
            let backup_result = if is_local {
                operations::ssh::execute_local_command(&check_and_backup, None, &std::collections::HashMap::new()).await
            } else {
                operations::ssh::execute_command(&target, &check_and_backup, None, &std::collections::HashMap::new()).await
            };
            eprintln!("[git_clone] Backup result: {:?}", backup_result);
            
            // Build git clone command
            let mut cmd = if let Some(token) = auth_token {
                // Convert SSH URL to HTTPS URL if needed, and insert token
                let https_url = if repo_url.starts_with("git@github.com:") {
                    // git@github.com:user/repo.git -> https://github.com/user/repo.git
                    repo_url.replacen("git@github.com:", "https://github.com/", 1)
                } else if repo_url.starts_with("git@gitlab.com:") {
                    repo_url.replacen("git@gitlab.com:", "https://gitlab.com/", 1)
                } else if repo_url.starts_with("git@bitbucket.org:") {
                    repo_url.replacen("git@bitbucket.org:", "https://bitbucket.org/", 1)
                } else {
                    repo_url.clone()
                };
                
                // Insert token into HTTPS URL for authentication
                if https_url.starts_with("https://") {
                    let url_with_auth = https_url.replacen("https://", &format!("https://oauth2:{}@", token), 1);
                    format!("git clone {}", url_with_auth)
                } else {
                    // Fallback: use GIT_SSH_COMMAND to avoid host key issues for SSH
                    format!("GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no' git clone {}", repo_url)
                }
            } else {
                // No token - try SSH with relaxed host key checking, or HTTPS as-is
                if repo_url.starts_with("git@") {
                    format!("GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no' git clone {}", repo_url)
                } else {
                    format!("git clone {}", repo_url)
                }
            };
            
            if let Some(b) = branch {
                cmd.push_str(&format!(" -b {}", b));
            }
            
            if let Some(depth) = op.depth {
                cmd.push_str(&format!(" --depth {}", depth));
            }
            
            cmd.push_str(&format!(" {}", destination));
            
            if is_local {
                operations::ssh::execute_local_command(&cmd, None, &std::collections::HashMap::new()).await
            } else {
                operations::ssh::execute_command(&target, &cmd, None, &std::collections::HashMap::new()).await
            }
        }
        
        // HuggingFace download operation
        Operation::HfDownload(op) => {
            let target = op.host_id.as_ref()
                .map(|h| interpolate(h, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host_id specified and no target defined"))?;
            
            let is_local = operations::ssh::is_local_target(&target);
            
            let repo_id = interpolate(&op.repo_id, variables);
            let destination = interpolate(&op.destination, variables);
            let auth_token = op.auth_token.as_ref().map(|t| interpolate(t, variables));
            
            // Build huggingface-cli download command
            let repo_type_str = match op.repo_type {
                crate::recipe::types::HfRepoType::Model => "model",
                crate::recipe::types::HfRepoType::Dataset => "dataset",
                crate::recipe::types::HfRepoType::Space => "space",
            };
            
            let mut cmd = format!("huggingface-cli download {} --local-dir {} --repo-type {}", 
                repo_id, destination, repo_type_str);
            
            if let Some(revision) = &op.revision {
                cmd.push_str(&format!(" --revision {}", interpolate(revision, variables)));
            }
            
            // Add specific files if provided
            for file in &op.files {
                cmd.push_str(&format!(" --include {}", file));
            }
            
            // Set up environment with token if provided
            let mut env = std::collections::HashMap::new();
            if let Some(token) = auth_token {
                env.insert("HF_TOKEN".to_string(), token);
            }
            
            if is_local {
                operations::ssh::execute_local_command(&cmd, None, &env).await
            } else {
                operations::ssh::execute_command(&target, &cmd, None, &env).await
            }
        }
        
        // Legacy ssh_command
        Operation::SshCommand(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let command = interpolate(&op.command, variables);
            let workdir = op.workdir.as_ref().map(|w| interpolate(w, variables));
            
            operations::ssh::execute_command(&host_id, &command, workdir.as_deref(), &op.env).await
        }
        
        Operation::RsyncUpload(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let local_path = interpolate(&op.local_path, variables);
            let remote_path = interpolate(&op.remote_path, variables);
            
            operations::sync::upload(&host_id, &local_path, &remote_path, &op.excludes, op.delete).await?;
            Ok(None)
        }
        
        Operation::RsyncDownload(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let remote_path = interpolate(&op.remote_path, variables);
            let local_path = interpolate(&op.local_path, variables);
            
            operations::sync::download(&host_id, &remote_path, &local_path, &op.excludes).await?;
            Ok(None)
        }
        
        Operation::VastStart(op) => {
            operations::vast::start_instance(op.instance_id).await?;
            Ok(None)
        }
        
        Operation::VastStop(op) => {
            operations::vast::stop_instance(op.instance_id).await?;
            Ok(None)
        }
        
        Operation::VastDestroy(op) => {
            operations::vast::destroy_instance(op.instance_id).await?;
            Ok(None)
        }
        
        Operation::TmuxNew(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            let command = op.command.as_ref().map(|c| interpolate(c, variables));
            let workdir = op.workdir.as_ref().map(|w| interpolate(w, variables));
            
            operations::tmux::new_session(&host_id, &session_name, command.as_deref(), workdir.as_deref()).await?;
            Ok(None)
        }
        
        Operation::TmuxSend(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            let keys = interpolate(&op.keys, variables);
            
            operations::tmux::send_keys(&host_id, &session_name, &keys).await?;
            Ok(None)
        }
        
        Operation::TmuxCapture(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            
            let output = operations::tmux::capture_pane(&host_id, &session_name, op.lines).await?;
            Ok(Some(output))
        }
        
        Operation::TmuxKill(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let session_name = interpolate(&op.session_name, variables);
            
            operations::tmux::kill_session(&host_id, &session_name).await?;
            Ok(None)
        }
        
        Operation::GdriveMount(op) => {
            // Use target host if not specified
            let host_id = op.host_id.as_ref()
                .filter(|s| !s.is_empty())
                .map(|s| interpolate(s, variables))
                .or_else(|| variables.get("target").cloned())
                .ok_or_else(|| AppError::command("No host specified and no target host set"))?;
            
            // Auto-detect Google Drive storage if not specified
            let storage_id = if let Some(sid) = op.storage_id.as_ref().filter(|s| !s.is_empty()) {
                interpolate(sid, variables)
            } else {
                // Find first Google Drive storage
                operations::google_drive::find_gdrive_storage().await?
            };
            
            // Use default mount path if not specified
            let mount_path = if op.mount_path.is_empty() {
                "/content/drive/MyDrive".to_string()
            } else {
                interpolate(&op.mount_path, variables)
            };
            let gdrive_path = op.gdrive_path.as_ref().map(|p| interpolate(p, variables));
            let cache_mode = if op.cache_mode.is_empty() {
                "writes".to_string()
            } else {
                interpolate(&op.cache_mode, variables)
            };
            
            let success_msg = operations::google_drive::mount(
                &host_id,
                &storage_id,
                &mount_path,
                gdrive_path.as_deref(),
                op.vfs_cache,
                &cache_mode,
                op.background,
                progress.clone(),
            ).await?;
            Ok(Some(success_msg))
        }
        
        Operation::GdriveUnmount(op) => {
            let host_id = interpolate(&op.host_id, variables);
            let mount_path = interpolate(&op.mount_path, variables);
            
            operations::google_drive::unmount(&host_id, &mount_path).await?;
            Ok(None)
        }
        
        Operation::Sleep(op) => {
            tokio::time::sleep(tokio::time::Duration::from_secs(op.duration_secs)).await;
            Ok(None)
        }
        
        Operation::WaitCondition(op) => {
            operations::conditions::wait_for(&op.condition, variables, op.timeout_secs, op.poll_interval_secs).await?;
            Ok(None)
        }
        
        Operation::Assert(op) => {
            let result = operations::conditions::evaluate(&op.condition, variables).await?;
            if !result {
                let msg = op.message.as_ref()
                    .map(|m| interpolate(m, variables))
                    .unwrap_or_else(|| "Assertion failed".to_string());
                return Err(AppError::command(msg));
            }
            Ok(None)
        }
        
        Operation::SetVar(_op) => {
            // This is handled specially - variables are updated in the execution state
            // For now, just return success
            Ok(None)
        }
        
        Operation::GetValue(_op) => {
            // This is also handled specially
            Ok(None)
        }
        
        Operation::HttpRequest(op) => {
            let url = interpolate(&op.url, variables);
            let body = op.body.as_ref().map(|b| interpolate(b, variables));
            
            let response = operations::http::request(&op.method, &url, &op.headers, body.as_deref(), op.timeout_secs).await?;
            Ok(Some(response))
        }
        
        Operation::Notify(op) => {
            let title = interpolate(&op.title, variables);
            let message = op.message.as_ref().map(|m| interpolate(m, variables));
            
            operations::notify::send(&title, message.as_deref(), &op.level).await?;
            Ok(None)
        }
        
        Operation::Group(_op) => {
            // Groups are expanded during recipe validation/loading
            // They shouldn't appear here during execution
            Ok(None)
        }
    }
}

/// Compute topological order of steps
fn compute_execution_order(steps: &[Step]) -> Result<Vec<String>, AppError> {
    use std::collections::VecDeque;
    
    // Build adjacency list and in-degree count
    let mut in_degree: HashMap<&str, usize> = HashMap::new();
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    
    for step in steps {
        in_degree.entry(&step.id).or_insert(0);
        adj.entry(&step.id).or_default();
        
        for dep in &step.depends_on {
            adj.entry(dep.as_str()).or_default().push(&step.id);
            *in_degree.entry(&step.id).or_insert(0) += 1;
        }
    }
    
    // Kahn's algorithm
    let mut queue: VecDeque<&str> = in_degree.iter()
        .filter(|(_, &deg)| deg == 0)
        .map(|(&id, _)| id)
        .collect();
    
    let mut order = Vec::new();
    
    while let Some(node) = queue.pop_front() {
        order.push(node.to_string());
        
        if let Some(neighbors) = adj.get(node) {
            for &neighbor in neighbors {
                if let Some(deg) = in_degree.get_mut(neighbor) {
                    *deg -= 1;
                    if *deg == 0 {
                        queue.push_back(neighbor);
                    }
                }
            }
        }
    }
    
    if order.len() != steps.len() {
        return Err(AppError::command("Circular dependency detected in recipe"));
    }
    
    Ok(order)
}
use std::sync::Arc;
