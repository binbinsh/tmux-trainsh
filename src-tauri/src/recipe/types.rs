//! Recipe types and data models
//!
//! This module defines the core data structures for the Recipe system,
//! a flexible workflow engine for composing automation tasks.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

// ============================================================
// Recipe Definition
// ============================================================

/// A Recipe is a complete workflow definition containing steps and metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recipe {
    /// Recipe name
    pub name: String,
    /// Version string (semver recommended)
    #[serde(default)]
    pub version: String,
    /// Optional description
    #[serde(default)]
    pub description: Option<String>,
    /// Target host type requirements (host selected at runtime)
    #[serde(default)]
    pub target: Option<TargetRequirements>,
    /// Global variables that can be interpolated in step parameters
    #[serde(default)]
    pub variables: HashMap<String, String>,
    /// List of steps to execute
    #[serde(default)]
    pub steps: Vec<Step>,
}

/// Target host requirements for a recipe.
/// Defines what type of host the recipe needs; actual host is selected at runtime.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TargetRequirements {
    /// Required host type: any, local, vast, colab, or custom
    #[serde(rename = "type", default)]
    pub host_type: TargetHostType,
    /// Minimum number of GPUs required
    #[serde(default)]
    pub min_gpus: Option<u32>,
    /// Minimum memory in GB
    #[serde(default)]
    pub min_memory_gb: Option<f64>,
    /// Specific GPU type (e.g., "T4", "A100", "H100")
    #[serde(default)]
    pub gpu_type: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum TargetHostType {
    /// Any host (user selects from all hosts + local at runtime)
    #[default]
    Any,
    /// Local machine (no SSH)
    Local,
    /// Vast.ai instance
    Vast,
    /// Google Colab
    Colab,
    /// Custom SSH host
    Custom,
}

/// A step is the basic execution unit in a recipe.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Step {
    /// Unique identifier within the recipe
    pub id: String,
    /// Human-readable name (optional)
    #[serde(default)]
    pub name: Option<String>,
    /// IDs of steps that must complete before this one
    #[serde(default)]
    pub depends_on: Vec<String>,
    /// The operation to perform
    #[serde(flatten)]
    pub operation: Operation,
    /// Retry configuration
    #[serde(default)]
    pub retry: Option<RetryConfig>,
    /// Timeout in seconds (overrides operation default)
    #[serde(default)]
    pub timeout_secs: Option<u64>,
    /// Conditional execution (expression that must be true)
    #[serde(default, rename = "when")]
    pub condition: Option<String>,
    /// Continue recipe even if this step fails
    #[serde(default)]
    pub continue_on_failure: bool,
}

/// Retry configuration for failed steps
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetryConfig {
    /// Maximum number of retry attempts
    #[serde(default = "default_max_retries")]
    pub max_attempts: u32,
    /// Delay between retries in seconds
    #[serde(default = "default_retry_delay")]
    pub delay_secs: u64,
    /// Exponential backoff multiplier
    #[serde(default)]
    pub backoff_multiplier: Option<f64>,
}

fn default_max_retries() -> u32 {
    3
}

fn default_retry_delay() -> u64 {
    5
}

// ============================================================
// Operations
// ============================================================

/// An operation is the action performed by a step.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Operation {
    // Commands (new unified command runner)
    RunCommands(RunCommandsOp),

    // Legacy SSH command (kept for backwards compatibility)
    SshCommand(SshCommandOp),

    // File Transfer (new unified transfer)
    Transfer(TransferOp),

    // Legacy rsync operations (kept for backwards compatibility)
    RsyncUpload(RsyncUploadOp),
    RsyncDownload(RsyncDownloadOp),

    // Vast.ai Operations
    VastStart(VastInstanceOp),
    VastStop(VastInstanceOp),
    VastDestroy(VastInstanceOp),

    // Tmux Operations
    TmuxNew(TmuxNewOp),
    TmuxSend(TmuxSendOp),
    TmuxCapture(TmuxCaptureOp),
    TmuxKill(TmuxKillOp),

    // Google Drive Operations
    GdriveMount(GdriveMountOp),
    GdriveUnmount(GdriveUnmountOp),

    // Git Operations
    GitClone(GitCloneOp),

    // HuggingFace Operations
    HfDownload(HfDownloadOp),

    // Flow Control
    Sleep(SleepOp),
    WaitCondition(WaitConditionOp),
    Assert(AssertOp),

    // Variables
    SetVar(SetVarOp),
    GetValue(GetValueOp),

    // HTTP
    HttpRequest(HttpRequestOp),

    // Notifications
    Notify(NotifyOp),

    // Composite
    Group(GroupOp),
}

// ============================================================
// Operation Parameters
// ============================================================

/// Run commands on target host with optional tmux support.
/// This is the primary way to execute commands in a recipe.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunCommandsOp {
    /// Host ID to connect to (if None, uses recipe target)
    #[serde(default)]
    pub host_id: Option<String>,
    /// Commands to execute (one per line, executed sequentially)
    pub commands: String,
    /// How to run the commands
    #[serde(default)]
    pub tmux_mode: TmuxMode,
    /// Session name for tmux modes (required for new/existing)
    #[serde(default)]
    pub session_name: Option<String>,
    /// Working directory (optional)
    #[serde(default)]
    pub workdir: Option<String>,
    /// Environment variables to set
    #[serde(default)]
    pub env: HashMap<String, String>,
    /// Store stdout in this variable (only works with tmux_mode: none)
    #[serde(default)]
    pub capture_output: Option<String>,
    /// Timeout in seconds (only works with tmux_mode: none)
    #[serde(default)]
    pub timeout_secs: Option<u64>,
}

/// How to run commands via tmux
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TmuxMode {
    /// Run directly via SSH (blocks until complete)
    #[default]
    None,
    /// Create a new tmux session and run commands
    New,
    /// Send commands to an existing tmux session
    Existing,
}

/// Execute SSH command on remote host (legacy, prefer run_commands)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SshCommandOp {
    /// Host ID to connect to
    pub host_id: String,
    /// Command to execute
    pub command: String,
    /// Working directory (optional)
    #[serde(default)]
    pub workdir: Option<String>,
    /// Environment variables to set
    #[serde(default)]
    pub env: HashMap<String, String>,
    /// Store stdout in this variable
    #[serde(default)]
    pub capture_output: Option<String>,
    /// Timeout in seconds
    #[serde(default)]
    pub timeout_secs: Option<u64>,
}

/// Sync local directory to remote
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RsyncUploadOp {
    pub host_id: String,
    pub local_path: String,
    pub remote_path: String,
    #[serde(default)]
    pub excludes: Vec<String>,
    #[serde(default)]
    pub use_gitignore: bool,
    /// Delete files on remote that don't exist locally
    #[serde(default)]
    pub delete: bool,
}

/// Sync remote directory to local
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RsyncDownloadOp {
    pub host_id: String,
    pub remote_path: String,
    pub local_path: String,
    #[serde(default)]
    pub excludes: Vec<String>,
}

/// Unified file transfer operation between any two endpoints.
/// Replaces rsync_upload/rsync_download with a more flexible approach.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TransferOp {
    /// Source endpoint
    pub source: TransferEndpoint,
    /// Destination endpoint
    pub destination: TransferEndpoint,
    /// Explicitly included paths (relative to source root)
    /// If empty, includes everything except excluded patterns
    #[serde(default)]
    pub include_paths: Vec<String>,
    /// Exclude patterns (glob patterns)
    #[serde(default)]
    pub exclude_patterns: Vec<String>,
    /// Load excludes from .gitignore in source
    #[serde(default)]
    pub use_gitignore: bool,
    /// Delete files in destination that don't exist in source
    #[serde(default)]
    pub delete: bool,
}

/// An endpoint for file transfer operations
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransferEndpoint {
    /// Local filesystem
    Local { path: String },
    /// A configured host (uses recipe target if host_id is None)
    Host {
        #[serde(default)]
        host_id: Option<String>,
        path: String,
    },
    /// A configured storage backend (Google Drive, S3, etc.)
    Storage { storage_id: String, path: String },
}

/// Git clone operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GitCloneOp {
    /// Host ID to clone on (if None, uses recipe target)
    #[serde(default)]
    pub host_id: Option<String>,
    /// Repository URL (HTTPS or SSH)
    pub repo_url: String,
    /// Destination path on the host
    pub destination: String,
    /// Branch to checkout (default: default branch)
    #[serde(default)]
    pub branch: Option<String>,
    /// Depth for shallow clone (None = full clone)
    #[serde(default)]
    pub depth: Option<u32>,
    /// Auth token for private repos (use ${secret:name} syntax)
    #[serde(default)]
    pub auth_token: Option<String>,
}

/// HuggingFace model/dataset download operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HfDownloadOp {
    /// Host ID to download on (if None, uses recipe target)
    #[serde(default)]
    pub host_id: Option<String>,
    /// HuggingFace repo ID (e.g., "meta-llama/Llama-2-7b")
    pub repo_id: String,
    /// Destination path on the host
    pub destination: String,
    /// Repo type: model, dataset, or space
    #[serde(default)]
    pub repo_type: HfRepoType,
    /// Specific files to download (empty = all files)
    #[serde(default)]
    pub files: Vec<String>,
    /// Revision/branch/tag to download (default: main)
    #[serde(default)]
    pub revision: Option<String>,
    /// Auth token for gated models (use ${secret:name} syntax)
    #[serde(default)]
    pub auth_token: Option<String>,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HfRepoType {
    #[default]
    Model,
    Dataset,
    Space,
}

/// Vast.ai instance operation (start/stop/destroy)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VastInstanceOp {}

/// Mount Google Drive on remote host using rclone
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GdriveMountOp {
    /// Host ID to mount on (empty = use target host)
    #[serde(default)]
    pub host_id: Option<String>,
    /// Storage ID referencing a configured Google Drive storage (empty = auto-detect first Google Drive)
    #[serde(default)]
    pub storage_id: Option<String>,
    /// Mount point on the remote host
    #[serde(default = "default_gdrive_mount_path")]
    pub mount_path: String,
    /// Folder in Google Drive to mount (empty for root)
    #[serde(default)]
    pub gdrive_path: Option<String>,
    /// Use VFS cache for better performance (recommended for Colab/Vast)
    #[serde(default = "default_vfs_cache")]
    pub vfs_cache: bool,
    /// Cache mode: off, minimal, writes, full
    #[serde(default = "default_cache_mode")]
    pub cache_mode: String,
    /// Run in background (recommended)
    #[serde(default = "default_background")]
    pub background: bool,
}

fn default_gdrive_mount_path() -> String {
    "/content/drive/MyDrive".to_string()
}

fn default_vfs_cache() -> bool {
    true
}

fn default_cache_mode() -> String {
    "writes".to_string()
}

fn default_background() -> bool {
    true
}

/// Unmount Google Drive from remote host
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GdriveUnmountOp {
    /// Host ID to unmount from
    pub host_id: String,
    /// Mount point to unmount
    pub mount_path: String,
}

/// Create new tmux session and run command
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TmuxNewOp {
    pub host_id: String,
    pub session_name: String,
    #[serde(default)]
    pub command: Option<String>,
    #[serde(default)]
    pub workdir: Option<String>,
}

/// Send keys to tmux session
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TmuxSendOp {
    pub host_id: String,
    pub session_name: String,
    pub keys: String,
}

/// Capture tmux pane content
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TmuxCaptureOp {
    pub host_id: String,
    pub session_name: String,
    /// Number of lines to capture (negative = from end)
    #[serde(default)]
    pub lines: Option<i64>,
    /// Store captured content in this variable
    #[serde(default)]
    pub capture_output: Option<String>,
}

/// Kill tmux session
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TmuxKillOp {
    pub host_id: String,
    pub session_name: String,
}

/// Sleep for a duration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SleepOp {
    pub duration_secs: u64,
}

/// Wait for a condition to be met
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaitConditionOp {
    pub condition: Condition,
    #[serde(default = "default_wait_timeout")]
    pub timeout_secs: u64,
    #[serde(default = "default_poll_interval")]
    pub poll_interval_secs: u64,
}

fn default_wait_timeout() -> u64 {
    300 // 5 minutes
}

fn default_poll_interval() -> u64 {
    10
}

/// Assert a condition (fail if false)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AssertOp {
    pub condition: Condition,
    #[serde(default)]
    pub message: Option<String>,
}

/// Set a variable
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetVarOp {
    pub name: String,
    pub value: String,
}

/// Get a value using pattern matching and store in variable
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GetValueOp {
    /// Source (variable name or command output)
    pub source: ValueSource,
    /// Regex pattern with capture group
    #[serde(default)]
    pub pattern: Option<String>,
    /// Variable name to store result
    pub var_name: String,
}

/// Source for GetValue operation
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueSource {
    /// From a variable
    Var(String),
    /// From command output on host
    Command { host_id: String, command: String },
    /// From step output
    StepOutput(String),
}

/// Make HTTP request
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HttpRequestOp {
    pub method: HttpMethod,
    pub url: String,
    #[serde(default)]
    pub headers: HashMap<String, String>,
    #[serde(default)]
    pub body: Option<String>,
    /// Store response body in this variable
    #[serde(default)]
    pub capture_response: Option<String>,
    #[serde(default)]
    pub timeout_secs: Option<u64>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum HttpMethod {
    Get,
    Post,
    Put,
    Delete,
    Patch,
}

/// Send notification
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NotifyOp {
    pub title: String,
    #[serde(default)]
    pub message: Option<String>,
    /// Notification level
    #[serde(default)]
    pub level: NotifyLevel,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum NotifyLevel {
    #[default]
    Info,
    Success,
    Warning,
    Error,
}

/// Group of operations (sequential or parallel)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GroupOp {
    /// Execution mode
    #[serde(default)]
    pub mode: GroupMode,
    /// Step IDs to include in the group
    pub steps: Vec<String>,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum GroupMode {
    #[default]
    Sequential,
    Parallel,
}

// ============================================================
// Conditions
// ============================================================

/// A condition that can be evaluated to true or false
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Condition {
    /// Check if file exists on remote host
    FileExists(FileExistsCondition),
    /// Check if file contains pattern
    FileContains(FileContainsCondition),
    /// Check if command succeeds (exit code 0)
    CommandSucceeds(CommandCondition),
    /// Check if command output matches pattern
    OutputMatches(OutputMatchesCondition),
    /// Check if variable equals value
    VarEquals(VarEqualsCondition),
    /// Check if variable matches pattern
    VarMatches(VarMatchesCondition),
    /// Check if host is online
    HostOnline(HostOnlineCondition),
    /// Check if tmux session exists
    TmuxAlive(TmuxAliveCondition),
    /// Check GPU availability
    GpuAvailable(GpuAvailableCondition),
    /// Check if Google Drive is mounted at path
    GdriveMounted(GdriveMountedCondition),
    /// Logical NOT
    Not(Box<Condition>),
    /// Logical AND
    And(Vec<Condition>),
    /// Logical OR
    Or(Vec<Condition>),
    /// Always true
    Always,
    /// Always false
    Never,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileExistsCondition {
    pub host_id: String,
    pub path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileContainsCondition {
    pub host_id: String,
    pub path: String,
    pub pattern: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandCondition {
    pub host_id: String,
    pub command: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OutputMatchesCondition {
    pub host_id: String,
    pub command: String,
    pub pattern: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VarEqualsCondition {
    pub name: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VarMatchesCondition {
    pub name: String,
    pub pattern: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HostOnlineCondition {
    pub host_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TmuxAliveCondition {
    pub host_id: String,
    pub session_name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuAvailableCondition {
    pub host_id: String,
    #[serde(default = "default_min_gpus")]
    pub min_count: u32,
}

fn default_min_gpus() -> u32 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GdriveMountedCondition {
    pub host_id: String,
    pub mount_path: String,
}

// ============================================================
// Execution State
// ============================================================

/// Status of a step during execution
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum StepStatus {
    Pending,
    Waiting, // Waiting for dependencies
    Running,
    Success,
    Failed,
    Skipped,
    Retrying,
    Cancelled,
}

/// Summary of a recipe (for listing)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecipeSummary {
    pub path: String,
    pub name: String,
    pub version: String,
    pub description: Option<String>,
    pub step_count: usize,
}

/// Result of recipe validation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationResult {
    pub valid: bool,
    pub errors: Vec<ValidationError>,
    pub warnings: Vec<ValidationWarning>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationError {
    pub step_id: Option<String>,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationWarning {
    pub step_id: Option<String>,
    pub message: String,
}
