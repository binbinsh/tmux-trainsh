# Recipe System Design

> Status note (current CLI): this document includes legacy TOML design details.
> The actively maintained runtime in this repo is the Python `.py` recipe API described in `README.md`.
> Current tmux behavior in runtime:
> - `tmux.open @host as name` creates detached tmux sessions (local/remote).
> - Remote tmux operations are executed over SSH via tmux CLI (no remote Python/libtmux required).
> - Commands sent to remote tmux continue running even if local `train` exits.
> - `train status --last` shows the latest running job and attach commands.
> - Session naming is unified as `train_<job_name>_<index>` for live/bridge/window sessions (`index` is allocation order).

## Overview

This document is historical design context. The current product path is Python recipes under `~/.config/tmux-trainsh/recipes/*.py`.

The Recipe system replaces the fixed 6-step Task/Session workflow with a flexible, composable workflow engine that supports:

- **Atomic operations**: Basic building blocks (SSH commands, file sync, Vast.ai operations, etc.)
- **Operation groups**: Compositions of atomic operations or other groups
- **Dependency graphs**: Steps can depend on other steps, enabling parallel execution
- **Execution control**: Pause, resume, cancel, and retry steps
- **Persistence**: Save/load recipes as YAML files

## Core Concepts

### Step

A Step is the basic execution unit in a Recipe. Each step:
- Has a unique ID within the recipe
- Contains an operation (atomic or group)
- Can declare dependencies on other steps
- Tracks execution status and output

### Target Host Type

Recipes define **requirements** for a target host, not a specific host. In the current Python DSL this is normally expressed with host placeholders plus runtime selection:

```python
from trainsh.pyrecipe import *

recipe("gpu-demo")
host("gpu", "placeholder")

pick = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=16)
ready = vast_wait(timeout="5m", after=pick)
```

Later steps reference the resolved host alias, usually through `session(..., on="gpu")` or `shell(..., host="gpu")`.

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

Current equivalent example:

```python
pull_data = transfer("@gpu:/workspace", "./data")
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
| `tmux.open @host as name` | Create detached/persistent tmux session on host |
| `tmux.close @session` | Close tmux session |
| `tmux.config @host` | Apply tmux configuration from config.yaml to remote host |

The `tmux.config` command reads `tmux.options` from your local config and writes them to `~/.tmux.conf` on the remote host.
If a tmux server is already active, it also runs `source-file` to reload immediately; otherwise, the config is applied on next tmux start/attach.

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
| `notify` | Send notification | `title`, `message`, `level`, `channels`, `webhook_url`, `command`, `timeout_secs`, `fail_on_error` |

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

A group runs multiple operations in sequence or parallel. In the current DSL this is usually expressed with normal `after=...` dependencies:

```python
setup_env = main("python setup_env.py")
download_data = main("python download_data.py", after=setup_env)
install_deps = main("pip install -r requirements.txt", after=download_data)
```

### Dependency Graph

Steps can declare dependencies:

```python
sync_code = main("git pull")
sync_data = transfer("@gpu:/data", "./data")
train = main.bg("python train.py", after=[sync_code, sync_data])
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

```python
var("MODEL_NAME", "llama-7b")
var("EPOCHS", "100")
host("gpu", "your-host")

main = session("main", on="gpu")
train = main("python train.py --model $MODEL_NAME --epochs $EPOCHS")
```

Special variables:
- `${step.ID.output}` - Output from a previous step
- `${step.ID.exit_code}` - Exit code from a previous step
- `${env.VAR}` - Environment variable
- `${now}` - Current timestamp

## Current Python DSL Shape

```python
from trainsh.pyrecipe import *

recipe("train-llama", executor="thread_pool", workers=4, callbacks=["console", "sqlite"])
host("gpu", "placeholder")
var("MODEL", "llama-7b")
var("LOCAL_PROJECT", "/Users/me/projects/llm-train")
var("REMOTE_WORKDIR", "/workspace/train")

pick = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=24)
ready = vast_wait(timeout="5m", after=pick)
main = session("main", on="gpu", after=ready)
sync_code = transfer("$LOCAL_PROJECT", "@gpu:$REMOTE_WORKDIR")
train = main.bg("python train.py --model $MODEL", after=sync_code)
main.idle(timeout="8h", after=train)
```

## Execution State (Interactive)

Interactive executions are persisted as YAML under the app data directory:

`<data_dir>/recipe_executions/interactive-<execution_id>.json`

Example (abridged):

```json
{
  "id": "exec-123",
  "recipe_path": "train-llama.yaml",
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
    parser.rs        # YAML parsing
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
    Notice(NotifyOp),
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

```python
from trainsh.pyrecipe import *

recipe("session-migration")
host("gpu", "your-host")
var("RUN_COMMAND", "python train.py")

main = session("main", on="gpu")
sync_source = transfer("./src", "@gpu:/workspace/src")
sync_data = transfer("./data", "@gpu:/workspace/data", after=sync_source)
install_deps = main("pip install -r requirements.txt", after=[sync_source, sync_data])
run = main.bg("$RUN_COMMAND", after=install_deps)
```

This allows gradual migration.
