//! Interactive recipe execution with PTY support
//!
//! This module enables recipe execution through a terminal session,
//! allowing real-time output display and human intervention.

use std::collections::HashMap;
use std::sync::Arc;

use serde::{Deserialize, Serialize};
use tokio::sync::{mpsc, RwLock, Mutex};

use crate::error::AppError;
use super::types::*;

// ============================================================
// Interactive Execution Types
// ============================================================

/// Configuration for interactive execution
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InteractiveConfig {
    /// Terminal session ID to use for output
    pub terminal_id: String,
    /// Host ID for SSH connection
    pub host_id: String,
    /// Whether human intervention is enabled (default: true)
    #[serde(default = "default_intervention")]
    pub allow_intervention: bool,
    /// Timeout in seconds for each command (0 = no timeout)
    #[serde(default)]
    pub command_timeout_secs: u64,
}

fn default_intervention() -> bool {
    true
}

/// State of an interactive execution
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InteractiveExecution {
    /// Unique execution ID
    pub id: String,
    /// Recipe path
    pub recipe_path: String,
    /// Recipe name
    pub recipe_name: String,
    /// Associated terminal session ID
    pub terminal_id: String,
    /// Host ID being used
    pub host_id: String,
    /// Current status
    pub status: InteractiveStatus,
    /// Whether intervention is currently locked (script is typing)
    pub intervention_locked: bool,
    /// Current step being executed
    pub current_step: Option<String>,
    /// Step statuses
    pub steps: Vec<InteractiveStepState>,
    /// Optional progress messages keyed by step_id
    pub step_progress: std::collections::HashMap<String, String>,
    /// Timestamps
    pub created_at: String,
    pub started_at: Option<String>,
    pub completed_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum InteractiveStatus {
    /// Waiting to start
    Pending,
    /// Connecting to host
    Connecting,
    /// Running commands
    Running,
    /// Paused by user or waiting for intervention
    Paused,
    /// Waiting for user input
    WaitingForInput,
    /// Successfully completed
    Completed,
    /// Failed with error
    Failed,
    /// Cancelled by user
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InteractiveStepState {
    pub step_id: String,
    pub name: Option<String>,
    pub status: StepStatus,
    /// Command being executed
    pub command: Option<String>,
}

/// Events emitted during interactive execution
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum InteractiveEvent {
    /// Execution started, terminal session created
    ExecutionStarted {
        execution_id: String,
        terminal_id: String,
    },
    /// Connected to host
    Connected {
        execution_id: String,
        host_id: String,
    },
    /// Step started
    StepStarted {
        execution_id: String,
        step_id: String,
        command: Option<String>,
    },
    /// About to send command (intervention point)
    CommandPending {
        execution_id: String,
        step_id: String,
        command: String,
    },
    /// Command sent to terminal
    CommandSent {
        execution_id: String,
        step_id: String,
        command: String,
    },
    /// Step completed
    StepCompleted {
        execution_id: String,
        step_id: String,
    },
    /// Step failed
    StepFailed {
        execution_id: String,
        step_id: String,
        error: String,
    },
    /// Intervention lock changed
    InterventionLockChanged {
        execution_id: String,
        locked: bool,
    },
    /// Waiting for user to confirm/modify command
    WaitingForConfirmation {
        execution_id: String,
        step_id: String,
        command: String,
    },
    /// Execution paused
    ExecutionPaused {
        execution_id: String,
    },
    /// Execution resumed
    ExecutionResumed {
        execution_id: String,
    },
    /// Execution completed
    ExecutionCompleted {
        execution_id: String,
    },
    /// Execution failed
    ExecutionFailed {
        execution_id: String,
        error: String,
    },
    /// Execution cancelled
    ExecutionCancelled {
        execution_id: String,
    },
}

// ============================================================
// Interactive Execution Manager
// ============================================================

/// Manages interactive recipe executions
pub struct InteractiveRunner {
    /// Active interactive executions
    executions: RwLock<HashMap<String, Arc<InteractiveExecutionState>>>,
    /// Event sender
    event_tx: Option<mpsc::UnboundedSender<InteractiveEvent>>,
}

struct InteractiveExecutionState {
    execution: RwLock<InteractiveExecution>,
    recipe: Recipe,
    /// Control channel
    control_tx: mpsc::Sender<InteractiveControl>,
    /// Whether execution is active
    active: RwLock<bool>,
}

#[derive(Debug, Clone)]
pub enum InteractiveControl {
    /// Pause execution
    Pause,
    /// Resume execution
    Resume,
    /// Cancel execution
    Cancel,
    /// Send interrupt (Ctrl+C) to terminal
    Interrupt,
    /// Confirm pending command
    ConfirmCommand,
    /// Modify and confirm pending command
    ModifyCommand(String),
    /// Skip current step
    SkipStep,
    /// Lock intervention (script is typing)
    LockIntervention,
    /// Unlock intervention (allow human input)
    UnlockIntervention,
}

impl Default for InteractiveRunner {
    fn default() -> Self {
        Self::new()
    }
}

impl InteractiveRunner {
    pub fn new() -> Self {
        Self {
            executions: RwLock::new(HashMap::new()),
            event_tx: None,
        }
    }
    
    pub fn with_event_sender(mut self, tx: mpsc::UnboundedSender<InteractiveEvent>) -> Self {
        self.event_tx = Some(tx);
        self
    }
    
    fn emit(&self, event: InteractiveEvent) {
        if let Some(tx) = &self.event_tx {
            let _ = tx.send(event);
        }
    }
    
    /// Start an interactive recipe execution
    /// Returns (execution_id, terminal_id)
    pub async fn start(
        &self,
        recipe: Recipe,
        recipe_path: String,
        host_id: String,
        terminal_id: String,
        _variable_overrides: HashMap<String, String>,
    ) -> Result<(String, String), AppError> {
        let id = uuid::Uuid::new_v4().to_string();
        let now = chrono::Utc::now().to_rfc3339();
        
        // Initialize step states
        let steps: Vec<InteractiveStepState> = recipe.steps.iter().map(|s| {
            InteractiveStepState {
                step_id: s.id.clone(),
                name: s.name.clone(),
                status: StepStatus::Pending,
                command: None,
            }
        }).collect();
        
        let execution = InteractiveExecution {
            id: id.clone(),
            recipe_path,
            recipe_name: recipe.name.clone(),
            terminal_id: terminal_id.clone(),
            host_id: host_id.clone(),
            status: InteractiveStatus::Pending,
            intervention_locked: false,
            current_step: None,
            steps,
            step_progress: std::collections::HashMap::new(),
            created_at: now,
            started_at: None,
            completed_at: None,
        };
        
        // Create control channel
        let (control_tx, _control_rx) = mpsc::channel(16);
        
        let state = Arc::new(InteractiveExecutionState {
            execution: RwLock::new(execution),
            recipe,
            control_tx,
            active: RwLock::new(true),
        });
        
        // Store execution
        {
            let mut execs = self.executions.write().await;
            execs.insert(id.clone(), state.clone());
        }
        
        // Emit start event
        self.emit(InteractiveEvent::ExecutionStarted {
            execution_id: id.clone(),
            terminal_id: terminal_id.clone(),
        });
        
        Ok((id, terminal_id))
    }
    
    /// Get execution by ID
    pub async fn get_execution(&self, id: &str) -> Result<InteractiveExecution, AppError> {
        let state = {
            let execs = self.executions.read().await;
            execs.get(id)
                .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?
                .clone()
        };
        let exec = state.execution.read().await.clone();
        Ok(exec)
    }
    
    /// Send control signal to execution
    pub async fn send_control(&self, id: &str, control: InteractiveControl) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        state.control_tx.send(control).await
            .map_err(|_| AppError::command("Failed to send control signal"))?;
        
        Ok(())
    }
    
    /// Lock intervention (called when script is sending commands)
    pub async fn lock_intervention(&self, id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        {
            let mut exec = state.execution.write().await;
            exec.intervention_locked = true;
        }
        
        self.emit(InteractiveEvent::InterventionLockChanged {
            execution_id: id.to_string(),
            locked: true,
        });
        
        Ok(())
    }
    
    /// Unlock intervention (allow human input)
    pub async fn unlock_intervention(&self, id: &str) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        {
            let mut exec = state.execution.write().await;
            exec.intervention_locked = false;
        }
        
        self.emit(InteractiveEvent::InterventionLockChanged {
            execution_id: id.to_string(),
            locked: false,
        });
        
        Ok(())
    }
    
    /// Update step status
    pub async fn update_step_status(&self, id: &str, step_id: &str, status: StepStatus) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        let mut exec = state.execution.write().await;
        if let Some(step) = exec.steps.iter_mut().find(|s| s.step_id == step_id) {
            step.status = status;
        }
        
        Ok(())
    }
    
    /// Update or clear step progress message
    pub async fn set_step_progress(&self, id: &str, step_id: &str, progress: Option<String>) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        let mut exec = state.execution.write().await;
        if let Some(msg) = progress {
            exec.step_progress.insert(step_id.to_string(), msg);
        } else {
            exec.step_progress.remove(step_id);
        }
        
        Ok(())
    }
    
    /// Set current step
    pub async fn set_current_step(&self, id: &str, step_id: Option<String>) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        let mut exec = state.execution.write().await;
        exec.current_step = step_id;
        
        Ok(())
    }
    
    /// Update execution status
    pub async fn update_status(&self, id: &str, status: InteractiveStatus) -> Result<(), AppError> {
        let execs = self.executions.read().await;
        let state = execs.get(id)
            .ok_or_else(|| AppError::not_found(format!("Execution not found: {id}")))?;
        
        let mut exec = state.execution.write().await;
        exec.status = status.clone();
        
        if status == InteractiveStatus::Running && exec.started_at.is_none() {
            exec.started_at = Some(chrono::Utc::now().to_rfc3339());
        }
        
        if matches!(status, InteractiveStatus::Completed | InteractiveStatus::Failed | InteractiveStatus::Cancelled) {
            exec.completed_at = Some(chrono::Utc::now().to_rfc3339());
            *state.active.write().await = false;
        }
        
        Ok(())
    }
    
    /// List all interactive executions
    pub async fn list_executions(&self) -> Vec<InteractiveExecution> {
        let execs = self.executions.read().await;
        let mut result = Vec::new();
        
        for state in execs.values() {
            result.push(state.execution.read().await.clone());
        }
        
        result.sort_by(|a, b| b.created_at.cmp(&a.created_at));
        result
    }
}

// ============================================================
// Global Instance
// ============================================================

use std::sync::OnceLock;

static INTERACTIVE_RUNNER: OnceLock<Mutex<InteractiveRunner>> = OnceLock::new();

fn get_runner_inner() -> &'static Mutex<InteractiveRunner> {
    INTERACTIVE_RUNNER.get_or_init(|| Mutex::new(InteractiveRunner::new()))
}

/// Get the global interactive runner
pub async fn get_runner() -> tokio::sync::MutexGuard<'static, InteractiveRunner> {
    get_runner_inner().lock().await
}

/// Initialize the runner with event sender
pub async fn init_runner(tx: mpsc::UnboundedSender<InteractiveEvent>) {
    let mut runner = get_runner_inner().lock().await;
    *runner = InteractiveRunner::new().with_event_sender(tx);
}
