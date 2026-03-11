```
   ████████╗██████╗  █████╗ ██╗███╗   ██╗███████╗██╗  ██╗
   ╚══██╔══╝██╔══██╗██╔══██╗██║████╗  ██║██╔════╝██║  ██║
      ██║   ██████╔╝███████║██║██╔██╗ ██║███████╗███████║
      ██║   ██╔══██╗██╔══██║██║██║╚██╗██║╚════██║██╔══██║
      ██║   ██║  ██║██║  ██║██║██║ ╚████║███████║██║  ██║
      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝

   ════════════════════════════════════════════════════════
     [TMUX]  ════>  [GPU]  ══════>  [STORAGE]
   ════════════════════════════════════════════════════════
```

[![PyPI version](https://img.shields.io/pypi/v/tmux-trainsh.svg)](https://pypi.org/project/tmux-trainsh/)
[![Downloads](https://static.pepy.tech/badge/tmux-trainsh)](https://pepy.tech/project/tmux-trainsh)

The missing training automation for public cloud GPU and storage.

Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage (R2, B2, GDrive), and automate training workflows with Python recipe modules.

## Requirements

- Python 3.11+
- tmux (any version with `wait-for` support)
- For remote `tmux.open`/`tmux.config`: remote host only needs `tmux` and a normal shell over SSH
- Optional: `rsync`, `rclone`

## Installation

### From PyPI (recommended)

```bash
uv tool install tmux-trainsh
```

### From GitHub

```bash
curl -fsSL https://raw.githubusercontent.com/binbinsh/tmux-trainsh/main/install.sh | bash -s -- --github
```

## Quick Start

```bash
# Show help
train help
train help recipe
train recipes new my-flow --template feature-tour

# Set up API keys
train secrets set VAST_API_KEY
train secrets set R2_CREDENTIALS

# Add a host
train host add

# Add a storage backend
train storage add

# Run a recipe
train run train

# Inspect scheduled recipes
train schedule list

```

## Configuration

Config files are stored in `~/.config/tmux-trainsh/`:

```
~/.config/tmux-trainsh/
├── config.yaml        # Main settings
├── hosts.yaml         # SSH hosts (including Colab)
├── storages.yaml      # Storage backends
├── jobs/              # Job state and execution logs
└── recipes/           # Recipe files
```

## Secrets

Supported secret keys:
- `VAST_API_KEY` - Vast.ai API key
- `HF_TOKEN` - HuggingFace token
- `R2_CREDENTIALS` - Cloudflare R2 S3 API credentials bundle
- `B2_CREDENTIALS` - Backblaze B2 application key bundle
- `GITHUB_TOKEN` - GitHub token
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` - AI APIs

Minimal cloud storage setup:

```bash
# Global R2 credentials
train secrets set R2_CREDENTIALS
# Prompts for:
#   R2 Account ID
#   R2 API Token Access Key ID
#   R2 API Token Secret Access Key

# Global B2 credentials
train secrets set B2_CREDENTIALS
# Prompts for:
#   B2 Application Key ID
#   B2 Application Key

# Add an R2 or B2 storage backend, then test it
train storage add
train storage test <storage-name>
```

You can also scope credentials to one storage backend instead of using global secrets:

```bash
train secrets set ARTIFACTS_R2_CREDENTIALS
train secrets set ARCHIVE_B2_CREDENTIALS
```

R2 bundles follow Cloudflare-style naming and typically include:
- `account_id`
- `access_key_id`
- `secret_access_key`

The S3 API endpoint is auto-derived from `account_id` during normal CLI setup.

B2 bundles follow Backblaze application-key naming and typically include:
- `application_key_id`
- `application_key`

## Tmux Configuration

tmux-trainsh can manage your tmux configuration with optimized defaults:

```bash
# Apply tmux configuration to local machine
train config tmux-setup
```

This generates `~/.tmux.conf` with settings including:
- Mouse support enabled
- Large scrollback buffer (50000 lines)
- Status bar on top with session name, hostname, and current path
- Window numbering starting at 1
- Click-to-switch windows

### Customize tmux settings

Edit all tmux options at once using your default editor:

```bash
# Open tmux options in $EDITOR
train config tmux-edit

# View current options
train config tmux-list

# Apply to local ~/.tmux.conf
train config tmux-setup
```

Or edit `~/.config/tmux-trainsh/config.yaml` directly:

```yaml
tmux:
  auto_bridge: true
  bridge_outside_tmux: true
  auto_enter_tmux: true
  prefer_bridge_exec: true
  bridge_remote_status: "off"   # keep | off | bottom
  options:
    - "set -g mouse on"
    - "set -g history-limit 50000"
    - "set -g base-index 1"
    - "set -g status-position top"
    - "set -g status-left \"[#S] \""
    - "set -g status-right \"#H:#{pane_current_path}\""
    - "bind -n MouseDown1Status select-window -t ="
    # Add any custom tmux options here
```

### Auto bridge splits

When `tmux.open` runs, train can automatically create local tmux splits and attach each split to the matching session:

- Local host: `tmux attach -t <session>`
- Remote host: `ssh -tt <host> 'tmux attach -t <session> || tmux new-session -A -s <session>'`

Behavior:
- If `train run` or `train resume` is launched outside tmux and `auto_enter_tmux = true`, train auto-starts a tmux session and runs the command inside it.
- If `train` is launched inside tmux, splits are created in the current tmux window.
- If launched outside tmux and `bridge_outside_tmux = true`, train creates a detached local bridge session (`train_<job_name>_<index>`) for these splits.
- Local hosts also attach bridge panes to the local recipe tmux session.
- Local and remote tmux lifecycle/IO are handled via tmux CLI calls.
- If `prefer_bridge_exec = true`, execute commands prefer the already-attached bridge pane, reducing repeated external SSH auth prompts.
- Once a command is sent to a remote tmux session, it continues running on the remote host even if the local `train` process stops.
- `bridge_remote_status` controls remote tmux status bar in bridge panes:
  - `off`: hide remote status while attached (default, avoids double top bars)
  - `bottom`: show remote status at bottom
  - `keep`: keep remote tmux config unchanged
- `train resume` rebuilds and reuses these bridge splits from saved state.

Session naming (unified):
- Auto-enter live shell: `train_<job_name>_<index>`
- Detached bridge session: `train_<job_name>_<index>`
- Recipe window session: `train_<job_name>_<index>`
- Window `index` follows `tmux.open` execution order (`0, 1, 2, ...`)

### Apply tmux config in Python recipes

Use `tmux.config @host` to apply your tmux configuration to remote hosts:

```python
from trainsh.pyrecipe import *

recipe("remote-tmux")
host("gpu", "vast:12345")

# Apply tmux config to remote host before opening sessions
tmux_config("gpu")

# Then open tmux session with your preferred settings
work = session("work", on="gpu")
work("python train.py")
```

If no tmux server is running on the remote host, `tmux.config` still writes `~/.tmux.conf`; it will take effect when a tmux session is created/attached.

## Python Recipes

Recipe files (`.py`) define automated training workflows with the Python `trainsh.pyrecipe` API.

### Quick Example

```python
from trainsh.pyrecipe import *

recipe("train-demo")
var("MODEL", "llama-7b")
var("WORKDIR", "/workspace/train")
host("gpu", "placeholder")
host("backup", "myserver")
storage("output", "r2:my-bucket")

pick = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=24)
ready = vast_wait(timeout="5m", after=pick)
work = session("work", on="gpu", after=ready)
clone = work("cd $WORKDIR && git clone https://github.com/user/repo", after=ready)
deps = work("cd $WORKDIR/repo && pip install -r requirements.txt", after=clone)
train = work.bg("cd $WORKDIR/repo && python train.py --model $MODEL", after=deps)
done = work.idle(timeout="2h", after=train)
push = transfer("@gpu:$WORKDIR/model", "@output:/models/$MODEL/", after=done)
backup = transfer("@gpu:$WORKDIR/model", "@backup:/backup/", after=push)
notice("Training finished", after=backup)
vast_stop(after=backup)
work.close(after=backup)
```

### Core Concepts

Python recipes use a few core building blocks:

- `var("MODEL", "llama-7b")` defines variables referenced in commands as `$MODEL`.
- `host("gpu", "user@hostname")` defines a host. `placeholder` is still supported for runtime resolution such as `vast_pick`.
- `storage("output", "r2:bucket")` defines a storage backend for transfer and storage helpers.
- `session("work", on="gpu")` opens a named tmux session on a host and returns a session helper.
- `work(...)`, `work.bg(...)`, `work.idle(...)`, `work.wait(...)`, `work.file(...)`, and `work.port(...)` express the old session workflow directly in Python.
- `transfer("@gpu:/path", "@output:/path")` moves files between local, host, and storage endpoints.
- `latest_only(...)`, `choose(...)`, `join(...)`, `notice(...)`, and `vast_stop(...)` cover the main control flow and lifecycle helpers.

Common host and storage specs remain the same:

- Host specs: `placeholder`, `user@hostname`, `user@hostname -p PORT`, `user@hostname -i KEY`, `user@hostname -J JUMP`, `user@hostname -o ProxyCommand='CMD'`, or a host name from `hosts.yaml`.
- Storage specs: `placeholder`, `r2:bucket`, `b2:bucket`, or a storage name from `storages.yaml`.

Cloudflared Access example:

```python
host(
    "case",
    "root@172.16.0.88 -o ProxyCommand='cloudflared access ssh --hostname ssh-access.example.com'",
)
```

Resume is now Python-native:

```bash
train resume train-demo
train resume train-demo --var MODEL=llama-70b
```

Resume restores the latest saved job state, including tmux session mapping and resolved hosts. Because of that, host overrides are intentionally blocked on resume; use a fresh `train run ... --host ...` when you need a different machine.

Centralized help topics:

```bash
train help
train help recipe
train help run
train help schedule
```

## Python Recipe API

`tmux-trainsh` recipes are authored as Python files and loaded with:

```python
from trainsh.pyrecipe import *
```

Minimal example:

```python
from trainsh.pyrecipe import *

recipe(
    "train-demo",
    schedule="@every 30m",
    executor="thread_pool",
    workers=4,
    callbacks=["console", "sqlite"],
)

host("gpu", "your-server")
ready = latest_only(fail_if_unknown=False, id="latest_only")
main = session("main", on="gpu", after=ready)
sync = main(
    "cd /tmp && git clone https://github.com/example/project.git project",
)
train = main.bg(
    "cd /tmp/project && python train.py",
    after=sync,
)
main.wait("training finished", timeout="2h", after=train)
main.idle(timeout="2h", after=train)
```

The Python API includes:
- dependency scheduling via `after=...`
- executor aliases such as `thread_pool`, `process_pool`, `local`, `airflow`, `celery`, `dask`, `debug`
- direct session helpers for tmux/session workflows: `session(...)`, `main(...)`, `main.bg(...)`, `main.idle(...)`, `main.wait(...)`, `main.file(...)`, `main.port(...)`
- control/provider helpers such as `latest_only`, `choose`, `short_circuit`, `join`, `storage_wait`, `sql_query`, `sql_exec`, `sql_script`, `xcom_push`, and `xcom_pull`
- public recipe authoring via `from trainsh.pyrecipe import *`

Starter paths:
- `train recipes new <name> --template minimal` for a small local recipe
- `train recipes new <name> --template feature-tour` for a fuller example that combines retries, callbacks, session waits, HTTP, SQLite, XCom, `latest_only`, and `storage_wait`
- `train recipes show feature-tour` to inspect the bundled integrated example

More detail: [docs/python-recipes.md](docs/python-recipes.md)

## Scheduler

Python recipes can be discovered as DAG-like jobs and triggered with:

```bash
train schedule list
train schedule run --once
train schedule run --forever
train schedule status
```

Schedules are read from recipe metadata such as:

```python
# schedule: @every 15m
```

The scheduler stores run metadata in `~/.config/tmux-trainsh/runtime.db`, which is also used by runtime features such as `latest_only` and XCom-like state.

## Commands

### Workflow

| Command | Description |
|---------|-------------|
| `train run <name>` | Run a recipe |
| `train resume <name>` | Resume the latest failed/interrupted run |
| `train run <name> --host gpu=vast:123` | Override host |
| `train run <name> --var MODEL=llama-7b` | Override variable |
| `train run <name> --pick-host gpu` | Pick Vast.ai host |
| `train schedule list` | List discovered scheduled recipes |
| `train schedule run --once` | Run one scheduler pass |
| `train schedule status` | Show scheduler runtime history |
| `train status` | View current recipe sessions |
| `train logs` | View recent execution logs |
| `train jobs` | View recent job history |
| `train transfer <src> <dst>` | Transfer files |
| `train transfer <src> <dst> --delete` | Sync with deletions |
| `train transfer <src> <dst> --exclude '*.ckpt'` | Exclude patterns |
| `train transfer <src> <dst> --dry-run` | Preview transfer |

### Recipe Files

| Command | Description |
|---------|-------------|
| `train recipes list` | List recipes and bundled examples |
| `train recipes show <name>` | Show recipe details |
| `train recipes new <name> --template minimal|feature-tour` | Create new recipe |
| `train recipes edit <name>` | Edit recipe in editor |
| `train recipes rm <name>` | Remove a recipe |

### Infrastructure

| Command | Description |
|---------|-------------|
| `train host list` | List configured hosts |
| `train host add` | Add new host (SSH/Colab) |
| `train host edit <name>` | Edit existing host config |
| `train host show <name>` | Show host details |
| `train host ssh <name>` | SSH into host |
| `train host browse <name>` | Browse files on host |
| `train host test <name>` | Test connection |
| `train host rm <name>` | Remove a host |
| `train storage list` | List storage backends |
| `train storage show <name>` | Show storage details |
| `train storage add` | Add storage backend |
| `train storage test <name>` | Test connection |
| `train storage rm <name>` | Remove storage |
| `train secrets list` | List stored secrets |
| `train secrets set <key>` | Set a secret |
| `train secrets get <key>` | Get a secret |
| `train secrets delete <key>` | Delete a secret |

### train config

Configuration and settings

| Command | Description |
|---------|-------------|
| `train config show` | Show configuration |
| `train config get <key>` | Get config value |
| `train config set <key> <val>` | Set config value |
| `train config tmux-setup` | Apply tmux configuration to ~/.tmux.conf |
| `train config tmux-edit` | Edit tmux options in $EDITOR |
| `train config tmux-list` | List current tmux options |
| `train config reset` | Reset configuration |

### Cloud

| Command | Description |
|---------|-------------|
| `train colab list` | List Colab connections |
| `train colab connect` | Add Colab connection |
| `train colab run <cmd>` | Run command on Colab |
| `train colab ssh` | SSH into Colab |

### train vast

Vast.ai instance management

| Command | Description |
|---------|-------------|
| `train vast list` | List your instances |
| `train vast show <id>` | Show instance details |
| `train vast ssh <id>` | SSH into instance |
| `train vast start <id>` | Start instance |
| `train vast stop <id>` | Stop instance |
| `train vast reboot <id>` | Reboot instance |
| `train vast rm <id>` | Remove instance |
| `train vast search` | Search for GPU offers |
| `train vast keys` | List SSH keys |
| `train vast attach-key [path]` | Attach local SSH key |
| `train vast rm <id>` | Remove instance |

### Utility

| Command | Description |
|---------|-------------|
| `train pricing rates` | Show exchange rates |
| `train pricing rates --refresh` | Refresh exchange rates |
| `train pricing currency` | Show display currency |
| `train pricing currency --set CNY` | Set display currency |
| `train pricing colab` | Show Colab pricing |
| `train pricing vast` | Show Vast.ai costs |
| `train pricing convert 10 USD CNY` | Convert currency |
| `train help` | Browse centralized help topics |
| `train help recipe` | Show Python recipe syntax and examples |
| `train version` | Show version |
| `train <command> --help` | Show command help |

## License

MIT License
