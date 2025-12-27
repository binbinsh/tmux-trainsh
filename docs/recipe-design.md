# Recipe System Design

## Overview

The Recipe system replaces the fixed 6-step Task/Session workflow with a flexible, composable workflow engine that supports:

- **Atomic operations**: Basic building blocks (SSH commands, file sync, Vast.ai operations, etc.)
- **Operation groups**: Compositions of atomic operations or other groups
- **Dependency graphs**: Steps can depend on other steps, enabling parallel execution
- **Execution control**: Pause, resume, retry, skip, and modify steps
- **Persistence**: Save/load recipes as TOML files

## Core Concepts

### Step

A Step is the basic execution unit in a Recipe. Each step:
- Has a unique ID within the recipe
- Contains an operation (atomic or group)
- Can declare dependencies on other steps
- Tracks execution status and output

### Target Host Type

Recipes define **requirements** for a target host, not a specific host. The actual host is selected at runtime:

```toml
[target]
type = "colab"           # Required: colab | vast | custom
min_gpus = 1             # Optional: minimum GPU count
min_memory_gb = 16       # Optional: minimum RAM
gpu_type = "T4"          # Optional: specific GPU type
```

Operations can use `${target}` as the host_id, or leave host_id empty to default to the recipe target.

### Operations

#### Commands

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `run_commands` | Execute commands on target host | `host_id?`, `commands`, `tmux_mode`, `session_name?`, `workdir?` |

The `run_commands` operation supports:
- **Multi-line commands**: Each line is executed sequentially
- **Tmux modes**: `none` (direct, blocking), `new` (new tmux session), `existing` (send to existing session)

#### Transfer

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `transfer` | Transfer files between endpoints | `source`, `destination`, `include_paths?`, `exclude_patterns?` |

Endpoints can be:
- `local`: Local filesystem `{ local: { path: "/path" } }`
- `host`: A configured host `{ host: { host_id?: "...", path: "/remote" } }`
- `storage`: A storage backend `{ storage: { storage_id: "gdrive", path: "/" } }`

#### Git & ML

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `git_clone` | Clone a repository | `host_id?`, `repo_url`, `destination`, `branch?`, `auth_token?` |
| `hf_download` | Download from HuggingFace | `host_id?`, `repo_id`, `destination`, `repo_type?`, `auth_token?` |

#### Vast.ai

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `vast_start` | Start Vast instance | `instance_id` |
| `vast_stop` | Stop Vast instance | `instance_id` |
| `vast_destroy` | Destroy Vast instance | `instance_id` |

#### Tmux

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `tmux_new` | Create new tmux session | `host_id`, `session_name`, `command?` |
| `tmux_send` | Send keys to tmux | `host_id`, `session_name`, `keys` |
| `tmux_capture` | Capture tmux pane content | `host_id`, `session_name`, `lines?` |
| `tmux_kill` | Kill tmux session | `host_id`, `session_name` |

#### Google Drive

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `gdrive_mount` | Mount Google Drive on host | `host_id`, `storage_id`, `mount_path` |
| `gdrive_unmount` | Unmount Google Drive | `host_id`, `mount_path` |

#### Control Flow

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `sleep` | Wait for duration | `duration_secs` |
| `wait_condition` | Wait until condition is met | `condition`, `timeout_secs`, `poll_interval_secs` |
| `assert` | Assert a condition | `condition`, `message` |

#### Utility

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `set_var` | Set a variable | `name`, `value` |
| `get_value` | Get value and store in variable | `source`, `pattern`, `var_name` |
| `http_request` | Make HTTP request | `method`, `url`, `headers`, `body` |
| `notify` | Send notification | `title`, `message` |

#### Legacy (for backwards compatibility)

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `ssh_command` | Execute SSH command | `host_id`, `command`, `timeout_secs` |
| `rsync_upload` | Sync local dir to remote | `host_id`, `local_path`, `remote_path` |
| `rsync_download` | Sync remote dir to local | `host_id`, `remote_path`, `local_path` |

#### Conditions (for wait_condition and assert)

- `file_exists(path)` - Check if file exists on host
- `file_contains(path, pattern)` - Check if file contains pattern
- `command_succeeds(cmd)` - Check if command returns 0
- `output_matches(cmd, pattern)` - Check if command output matches
- `var_equals(name, value)` - Check if variable equals value
- `var_matches(name, pattern)` - Check if variable matches pattern
- `host_online(host_id)` - Check if host is online
- `tmux_alive(session_name)` - Check if tmux session exists
- `gpu_available(min_count)` - Check GPU availability

#### Operation Groups

A group runs multiple operations in sequence or parallel:

```toml
[[step]]
id = "setup"
group.mode = "sequential"  # or "parallel"
group.steps = ["install_deps", "setup_env", "download_data"]
```

### Dependency Graph

Steps can declare dependencies:

```toml
[[step]]
id = "train"
depends_on = ["sync_code", "sync_data"]  # Runs after both complete
operation = { ssh_command = { command = "python train.py" } }
```

The execution engine:
1. Builds a DAG from step dependencies
2. Validates for cycles
3. Executes steps in topological order
4. Runs independent steps in parallel

### Step Status

```
Pending → Running → Success
              ↓
           Failed → Retrying → Success
              ↓
           Skipped
```

### Variables and Interpolation

Variables can be set and referenced:

```toml
[variables]
model_name = "llama-7b"
epochs = "100"
host = "vast-h100"

[[step]]
id = "train"
operation = { ssh_command = { 
  host_id = "${host}",
  command = "python train.py --model ${model_name} --epochs ${epochs}"
}}
```

Special variables:
- `${step.ID.output}` - Output from a previous step
- `${step.ID.exit_code}` - Exit code from a previous step
- `${env.VAR}` - Environment variable
- `${now}` - Current timestamp

## TOML Schema

```toml
[recipe]
name = "train-llama"
version = "1.0.0"
description = "Train LLaMA model on Vast.ai"

[variables]
model = "llama-7b"
local_project = "/Users/me/projects/llm-train"
remote_workdir = "/workspace/train"

[[step]]
id = "start_instance"
name = "Start Vast Instance"
operation = { vast_start = { instance_id = 12345 } }

[[step]]
id = "wait_online"
name = "Wait for Host Online"
depends_on = ["start_instance"]
operation = { wait_condition = { 
  condition = { host_online = { host_id = "vast-12345" } },
  timeout_secs = 300,
  poll_interval_secs = 10
}}

[[step]]
id = "sync_code"
name = "Sync Source Code"
depends_on = ["wait_online"]
operation = { rsync_upload = {
  host_id = "vast-12345",
  local_path = "${local_project}",
  remote_path = "${remote_workdir}",
  excludes = ["*.pth", "wandb/", "__pycache__/"]
}}

[[step]]
id = "install_deps"
name = "Install Dependencies"
depends_on = ["sync_code"]
operation = { ssh_command = {
  host_id = "vast-12345",
  command = "cd ${remote_workdir} && pip install -r requirements.txt"
}}

[[step]]
id = "train"
name = "Run Training"
depends_on = ["install_deps"]
operation = { tmux_new = {
  host_id = "vast-12345",
  session_name = "train",
  command = "cd ${remote_workdir} && python train.py --model ${model}"
}}

[[step]]
id = "monitor"
name = "Wait for Training Complete"
depends_on = ["train"]
operation = { wait_condition = {
  condition = { file_exists = { 
    host_id = "vast-12345",
    path = "${remote_workdir}/output/model.safetensors"
  }},
  timeout_secs = 86400,  # 24 hours
  poll_interval_secs = 60
}}

[[step]]
id = "download"
name = "Download Results"
depends_on = ["monitor"]
operation = { rsync_download = {
  host_id = "vast-12345",
  remote_path = "${remote_workdir}/output",
  local_path = "/Users/me/models/output"
}}

[[step]]
id = "shutdown"
name = "Stop Instance"
depends_on = ["download"]
operation = { vast_stop = { instance_id = 12345 } }
```

## Execution State

Persisted alongside the recipe:

```toml
[execution]
recipe_path = "train-llama.toml"
started_at = "2024-12-26T10:00:00Z"
status = "running"  # pending, running, paused, completed, failed

[[execution.steps]]
id = "start_instance"
status = "success"
started_at = "2024-12-26T10:00:00Z"
completed_at = "2024-12-26T10:00:05Z"
output = "Instance started"

[[execution.steps]]
id = "sync_code"
status = "running"
started_at = "2024-12-26T10:01:00Z"
progress = { files_done = 50, files_total = 100, bytes_done = 1048576, bytes_total = 2097152 }

[[execution.steps]]
id = "train"
status = "pending"
```

## UI Components

### Recipe Editor
- Visual DAG editor for step dependencies
- Form-based step configuration
- Variable management
- Live validation

### Recipe Runner
- Step status visualization
- Real-time logs per step
- Pause/Resume/Retry controls
- Variable override before run

### Recipe Library
- List saved recipes
- Quick run with variable overrides
- Duplicate and modify recipes

## Rust Implementation

### Module Structure

```
src-tauri/src/
  recipe/
    mod.rs           # Module exports
    types.rs         # Recipe, Step, Operation types
    parser.rs        # TOML parsing
    execution.rs     # DAG execution engine
    operations/
      mod.rs
      ssh.rs
      sync.rs
      vast.rs
      tmux.rs
      conditions.rs
```

### Key Types

```rust
pub struct Recipe {
    pub name: String,
    pub version: String,
    pub description: Option<String>,
    pub variables: HashMap<String, String>,
    pub steps: Vec<Step>,
}

pub struct Step {
    pub id: String,
    pub name: Option<String>,
    pub depends_on: Vec<String>,
    pub operation: Operation,
    pub retry: Option<RetryConfig>,
    pub timeout_secs: Option<u64>,
}

pub enum Operation {
    SshCommand(SshCommandOp),
    RsyncUpload(RsyncUploadOp),
    RsyncDownload(RsyncDownloadOp),
    VastStart(VastStartOp),
    VastStop(VastStopOp),
    VastDestroy(VastDestroyOp),
    TmuxNew(TmuxNewOp),
    TmuxSend(TmuxSendOp),
    TmuxCapture(TmuxCaptureOp),
    Sleep(SleepOp),
    WaitCondition(WaitConditionOp),
    Assert(AssertOp),
    SetVar(SetVarOp),
    GetValue(GetValueOp),
    HttpRequest(HttpRequestOp),
    Notify(NotifyOp),
    Group(GroupOp),
}

pub enum StepStatus {
    Pending,
    Running,
    Success,
    Failed(String),
    Skipped,
    Retrying(u32),  // attempt number
}
```

## API

### Tauri Commands

```rust
// Recipe CRUD
recipe_list() -> Vec<RecipeSummary>
recipe_get(path: String) -> Recipe
recipe_save(path: String, recipe: Recipe) -> ()
recipe_delete(path: String) -> ()
recipe_validate(recipe: Recipe) -> ValidationResult

// Execution
recipe_run(path: String, variables: HashMap<String, String>) -> ExecutionId
recipe_pause(exec_id: String) -> ()
recipe_resume(exec_id: String) -> ()
recipe_cancel(exec_id: String) -> ()
recipe_retry_step(exec_id: String, step_id: String) -> ()
recipe_skip_step(exec_id: String, step_id: String) -> ()
recipe_get_execution(exec_id: String) -> Execution
recipe_list_executions() -> Vec<ExecutionSummary>

// Events (emitted to frontend)
recipe:step_started { exec_id, step_id }
recipe:step_progress { exec_id, step_id, progress }
recipe:step_completed { exec_id, step_id, output }
recipe:step_failed { exec_id, step_id, error }
recipe:execution_completed { exec_id }
```

## Migration from Session

The existing Session system can be expressed as a Recipe:

```toml
[recipe]
name = "session-${name}"

[[step]]
id = "sync_source"
operation = { rsync_upload = { ... } }

[[step]]
id = "sync_data"
depends_on = ["sync_source"]
operation = { rsync_upload = { ... } }
when = "${data.enabled}"

[[step]]
id = "install_deps"
depends_on = ["sync_source", "sync_data"]
operation = { ssh_command = { command = "pip install -r requirements.txt" } }

[[step]]
id = "run"
depends_on = ["install_deps"]
operation = { tmux_new = { command = "${run.command}" } }
```

This allows gradual migration while maintaining backwards compatibility.

