# Recipe System Design

## Overview

The Recipe system replaces the fixed 6-step Task/Session workflow with a flexible, composable workflow engine that supports:

- **Atomic operations**: Basic building blocks (SSH commands, file sync, Vast.ai operations, etc.)
- **Operation groups**: Compositions of atomic operations or other groups
- **Dependency graphs**: Steps can depend on other steps, enabling parallel execution
- **Execution control**: Pause, resume, cancel, and retry steps
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
type = "colab" # any | local | vast | colab | custom
min_gpus = 1
min_memory_gb = 16
gpu_type = "T4"
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
| `vast_start` | Start target Vast host | (none; uses `${target}`) |
| `vast_stop` | Stop target Vast host | (none; uses `${target}`) |
| `vast_rm` | Remove target Vast host | (none; uses `${target}`) |
| `vast_copy` | Copy data using Vast copy API | `src`, `dst`, `identity_file?` |

Supported `src`/`dst` formats follow the Vast CLI:
- `[instance_id:]path`
- `C.instance_id:path`
- `target:path` or `C.target:path` (uses the recipe target Vast host)
- `cloud_service:path` (e.g. `drive:/folder/file.txt`)
- `cloud_service.connection_id:path` (e.g. `s3.101:/data`)
- `local:path`

If you use `${target}` as the prefix (for example `C.${target}:/workspace`), it is normalized to the selected target instance ID at runtime.

By default, local rsync transfers use the Vast SSH key configured in Settings. Provide `identity_file` only if you need to override it.

Example (copy from Vast to local without starting the instance):

```toml
[[step]]
id = "pull_data"
vast_copy = { src = "C.6003036:/workspace/", dst = "local:./data" }
```

#### Tmux

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `tmux_new` | Create new tmux session | `host_id`, `session_name`, `command?` |
| `tmux_send` | Send keys to tmux | `host_id`, `session_name`, `keys` |
| `tmux_capture` | Capture tmux pane content | `host_id`, `session_name`, `lines?` |
| `tmux_kill` | Kill tmux session | `host_id`, `session_name` |

**DSL Control Commands:**

| Command | Description |
|---------|-------------|
| `tmux.open @host as name` | Create tmux session on host |
| `tmux.close @session` | Close tmux session |
| `tmux.config @host` | Apply tmux configuration from config.toml to remote host |

The `tmux.config` command reads `tmux.options` from your local config and writes them to `~/.tmux.conf` on the remote host, then reloads tmux.

Example:
```
# Apply your tmux settings to remote host
tmux.config @gpu

# Then open session with your preferred settings
tmux.open @gpu as work
```

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

#### SSH & Rsync

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
group = { mode = "sequential", steps = ["install_deps", "setup_env", "download_data"] }
```

### Dependency Graph

Steps can declare dependencies:

```toml
[[step]]
id = "train"
depends_on = ["sync_code", "sync_data"]
run_commands = { commands = "python train.py" }
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
run_commands = { host_id = "${host}", commands = "python train.py --model ${model_name} --epochs ${epochs}" }
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

[target]
type = "vast"

[variables]
model = "llama-7b"
local_project = "/Users/me/projects/llm-train"
remote_workdir = "/workspace/train"

[[step]]
id = "start_instance"
name = "Start Vast Instance"
vast_start = {}

[[step]]
id = "wait_online"
name = "Wait for Host Online"
depends_on = ["start_instance"]
wait_condition = { condition = { host_online = { host_id = "${target}" } }, timeout_secs = 300, poll_interval_secs = 10 }

[[step]]
id = "sync_code"
name = "Sync Source Code"
depends_on = ["wait_online"]
rsync_upload = { host_id = "${target}", local_path = "${local_project}", remote_path = "${remote_workdir}", excludes = ["*.pth", "wandb/", "__pycache__/"] }
```

## Execution State (Interactive)

Interactive executions are persisted as JSON under the app data directory:

`<data_dir>/recipe_executions/interactive-<execution_id>.json`

Example (abridged):

```json
{
  "id": "exec-123",
  "recipe_path": "train-llama.toml",
  "recipe_name": "train-llama",
  "terminal_id": null,
  "terminal": {
    "title": "Recipe: train-llama",
    "tmux_session": "recipe-acde",
    "cols": 120,
    "rows": 32
  },
  "host_id": "vast:12345",
  "status": "paused",
  "current_step": "train",
  "steps": [
    { "step_id": "start_instance", "status": "success" },
    { "step_id": "train", "status": "pending" }
  ],
  "variables": { "target": "vast:12345" },
  "created_at": "2024-12-26T10:00:00Z",
  "updated_at": "2024-12-26T10:15:00Z"
}
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
    execution.rs     # Shared step execution helpers
    interactive.rs   # Interactive execution + persistence + resume
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
    VastRm(VastRmOp),
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
    Waiting,
    Running,
    Success,
    Failed,
    Skipped,
    Retrying,
    Cancelled,
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
recipe_run_interactive(app: AppHandle, term_mgr: State<TerminalManager>, path: String, host_id: String, variables: HashMap<String, String>, cols?: u16, rows?: u16) -> InteractiveExecution
recipe_interactive_get(execution_id: String) -> InteractiveExecution
recipe_interactive_list() -> Vec<InteractiveExecution>
recipe_interactive_pause(execution_id: String) -> ()
recipe_interactive_resume(app: AppHandle, term_mgr: State<TerminalManager>, execution_id: String) -> InteractiveExecution
recipe_interactive_cancel(execution_id: String) -> ()
recipe_interactive_send(execution_id: String, data: String) -> ()
recipe_interactive_interrupt(execution_id: String) -> ()
recipe_interactive_lock(execution_id: String, locked: bool) -> ()
recipe_interactive_exec_command(execution_id: String, command: String) -> ()
recipe_interactive_mark_complete(execution_id: String, step_id: String) -> ()

// Events (emitted to frontend)
recipe:interactive_started { execution_id, terminal_id, recipe_name, host_id, steps }
recipe:execution_updated { execution_id, status }
recipe:step_started { execution_id, step_id, step_index }
recipe:step_progress { execution_id, step_id, progress }
recipe:step_completed { execution_id, step_id }
recipe:step_failed { execution_id, step_id, error }
recipe:execution_completed { execution_id }
recipe:execution_failed { execution_id, error }
recipe:execution_cancelled { execution_id }
```

## Migration from Session

The existing Session system can be expressed as a Recipe:

```toml
[recipe]
name = "session-${name}"

[[step]]
id = "sync_source"
rsync_upload = { ... }

[[step]]
id = "sync_data"
depends_on = ["sync_source"]
rsync_upload = { ... }
when = "${data.enabled}"

[[step]]
id = "install_deps"
depends_on = ["sync_source", "sync_data"]
run_commands = { commands = "pip install -r requirements.txt" }

[[step]]
id = "run"
depends_on = ["install_deps"]
tmux_new = { command = "${run.command}" }
```

This allows gradual migration.
