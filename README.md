# tmux-trainsh

```
   ████████╗██████╗  █████╗ ██╗███╗   ██╗███████╗██╗  ██╗
   ╚══██╔══╝██╔══██╗██╔══██╗██║████╗  ██║██╔════╝██║  ██║
      ██║   ██████╔╝███████║██║██╔██╗ ██║███████╗███████║
      ██║   ██╔══██╗██╔══██║██║██║╚██╗██║╚════██║██╔══██║
      ██║   ██║  ██║██║  ██║██║██║ ╚████║███████║██║  ██║
      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝

   ════════════════════════════════════════════════════════
     🖥️  TMUX   ══▶   ☁️  GPU   ══▶   💾  STORAGE
   ════════════════════════════════════════════════════════
```

[![PyPI version](https://img.shields.io/pypi/v/tmux-trainsh.svg)](https://pypi.org/project/tmux-trainsh/)
[![Downloads](https://static.pepy.tech/badge/tmux-trainsh)](https://pepy.tech/project/tmux-trainsh)

The missing training automation for public cloud GPU and storage.

Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage (R2, B2, S3, GDrive), and automate training workflows with a simple recipe DSL.

## Requirements

- Python 3.11+
- tmux (any version with `wait-for` support)
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

# Set up API keys
train secrets set VAST_API_KEY
train secrets set R2_ACCESS_KEY

# Add a host
train host add

# Add a storage backend
train storage add

# Run a recipe
train run train
```

## Configuration

Config files are stored in `~/.config/tmux-trainsh/`:

```
~/.config/tmux-trainsh/
├── config.toml        # Main settings
├── hosts.toml         # SSH hosts (including Colab)
├── storages.toml      # Storage backends
├── jobs/              # Job state and execution logs
└── recipes/           # Recipe files
```

## Secrets

Supported secret keys:
- `VAST_API_KEY` - Vast.ai API key
- `HF_TOKEN` - HuggingFace token
- `R2_ACCESS_KEY`, `R2_SECRET_KEY` - Cloudflare R2
- `B2_KEY_ID`, `B2_APPLICATION_KEY` - Backblaze B2
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - Amazon S3
- `GITHUB_TOKEN` - GitHub token
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` - AI APIs

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

Or edit `~/.config/tmux-trainsh/config.toml` directly:

```toml
[tmux]
options = [
  "set -g mouse on",
  "set -g history-limit 50000",
  "set -g base-index 1",
  "set -g status-position top",
  "set -g status-left \"[#S] \"",
  "set -g status-right \"#H:#{pane_current_path}\"",
  "bind -n MouseDown1Status select-window -t =",
  # Add any custom tmux options here
]
```

### Apply tmux config in recipes

Use `tmux.config @host` to apply your tmux configuration to remote hosts:

```
# In your .recipe file
host gpu = vast:12345

# Apply tmux config to remote host before opening sessions
tmux.config @gpu

# Then open tmux session with your preferred settings
tmux.open @gpu as work
@work > python train.py
```

## Recipe DSL

Recipe files (`.recipe`) define automated training workflows with a simple DSL.

### Quick Example

```
# Variables
var MODEL = llama-7b
var WORKDIR = /workspace/train

# Hosts (machines)
host gpu = placeholder
host backup = myserver

# Storage
storage output = r2:my-bucket

# Workflow
vast.pick @gpu num_gpus=1 min_gpu_ram=24
vast.wait timeout=5m

# Create a tmux session "work" on the gpu host
tmux.open @gpu as work

# Commands reference the session name, not the host
@work > cd $WORKDIR && git clone https://github.com/user/repo
@work > pip install -r requirements.txt
@work > python train.py --model $MODEL &

wait @work idle timeout=2h

# Transfers reference the host (for SSH connection info)
@gpu:$WORKDIR/model -> @output:/models/$MODEL/
@gpu:$WORKDIR/model -> @backup:/backup/

vast.stop
tmux.close @work
```

### Syntax Reference

#### Definitions

All definitions must appear before workflow commands. Names cannot be duplicated across var/host/storage.

| Type | Syntax | Reference | Description |
|------|--------|-----------|-------------|
| Variable | `var NAME = value` | `$NAME` | Define a variable |
| Host | `host NAME = spec` | `@NAME` | Define a remote host |
| Storage | `storage NAME = spec` | `@NAME` | Define a storage backend |

**Host spec formats:**

| Spec | Description |
|------|-------------|
| `placeholder` | Placeholder, must be filled by `vast.pick` |
| `user@hostname` | SSH host |
| `user@hostname -p PORT` | SSH host with port |
| `user@hostname -i KEY` | SSH host with identity file |
| `user@hostname -J JUMP` | SSH host with jump host |
| `name` | Reference to hosts.toml config |

**Storage spec formats:**

| Spec | Description |
|------|-------------|
| `placeholder` | Placeholder, must be filled at runtime |
| `r2:bucket` | Cloudflare R2 |
| `b2:bucket` | Backblaze B2 |
| `s3:bucket` | Amazon S3 |
| `name` | Reference to storages.toml config |

#### Execute Commands

Run commands in a tmux session (created with `tmux.open`):

```
@session > command
@session > command &
@session timeout=2h > command
```

| Syntax | Description |
|--------|-------------|
| `@session > cmd` | Run command, wait for completion |
| `@session > cmd &` | Run command in background |
| `@session timeout=DURATION > cmd` | Run with custom timeout (default: 10m) |

**Note:** The `@session` references a session name from `tmux.open @host as session`, not the host directly.

**Multiline:** Use shell line continuations (`\`) or heredocs (`<< 'EOF'`) to span commands across lines; the DSL treats them as a single execute step.

**train exec:** `@name` resolves to an existing tmux session first. If none exists, it runs directly on the host named `name` without creating a tmux session.

#### Wait Commands

Wait for conditions in a session:

```
wait @session "pattern" timeout=DURATION
wait @session file=PATH timeout=DURATION
wait @session port=PORT timeout=DURATION
wait @session idle timeout=DURATION
```

| Condition | Description |
|-----------|-------------|
| `"pattern"` | Wait for regex pattern in terminal output |
| `file=PATH` | Wait for file to exist |
| `port=PORT` | Wait for port to be open |
| `idle` | Wait for no child processes (command finished) |

#### Transfer Commands

Transfer files between endpoints:

```
@src:path -> @dst:path
@src:path -> ./local/path
./local/path -> @dst:path
```

#### Control Commands

**tmux session commands:**

The recipe system separates two concepts:
- **Host**: The machine where commands run (defined with `host NAME = spec`)
- **Session**: A persistent tmux session on that host (created with `tmux.open @host as session_name`)

Commands are sent to **sessions**, not hosts directly. This allows multiple sessions on the same host.

```
# WRONG - missing session name
tmux.open @gpu
@gpu > python train.py

# CORRECT - create named session, then use session name
tmux.open @gpu as work
@work > python train.py
tmux.close @work
```

| Command | Description |
|---------|-------------|
| `tmux.open @host as name` | Create tmux session named "name" on host |
| `tmux.close @session` | Close tmux session |
| `tmux.config @host` | Apply tmux configuration to remote host |
| `vast.pick @host [options]` | Interactively select Vast.ai instance |
| `vast.start [id]` | Start Vast.ai instance |
| `vast.stop [id]` | Stop Vast.ai instance |
| `vast.wait [options]` | Wait for instance to be ready |
| `vast.cost [id]` | Show usage cost |
| `notify "message"` | Send notification |
| `sleep DURATION` | Sleep for duration |

**vast.pick options:**

- `num_gpus=N` - Minimum GPU count
- `min_gpu_ram=N` - Minimum GPU memory (GB)
- `gpu=NAME` - GPU model (e.g., RTX_4090)
- `max_dph=N` - Maximum $/hour
- `limit=N` - Max instances to show

**vast.wait options:**

- `timeout=DURATION` - Max wait time (default: 10m)
- `poll=DURATION` - Poll interval (default: 10s)
- `stop_on_fail=BOOL` - Stop instance on timeout

#### Duration Format

- `30s` - 30 seconds
- `5m` - 5 minutes
- `2h` - 2 hours
- `300` - 300 seconds (raw number)

#### Comments

```
# This is a comment
```

#### Variable Interpolation

- `$NAME` - Reference a variable
- `${NAME}` - Reference a variable (alternative)
- `${secret:NAME}` - Reference a secret from secrets store

## Commands

### Frequent

| Command | Description |
|---------|-------------|
| `train exec '<dsl>'` | Execute DSL commands directly |
| `train exec '@session > cmd'` | Run in tmux session; falls back to host if no session exists |
| `train exec '@src:path -> @dst:path'` | Transfer files |
| `train host list` | List configured hosts |
| `train host show <name>` | Show host details |
| `train host ssh <name>` | SSH into host |
| `train transfer <src> <dst>` | Transfer files |
| `train transfer <src> <dst> --delete` | Sync with deletions |
| `train transfer <src> <dst> --exclude '*.ckpt'` | Exclude patterns |
| `train transfer <src> <dst> --dry-run` | Preview transfer |
| `train run <name>` | Run a recipe |
| `train run <name> --host gpu=vast:123` | Override host |
| `train run <name> --var MODEL=llama-7b` | Override variable |
| `train run <name> --pick-host gpu` | Pick Vast.ai host |
| `train recipe list` | List recipes |
| `train recipe show <name>` | Show recipe details |
| `train recipe status` | View running sessions |
| `train recipe status --all` | Include completed sessions |

### Occasional

| Command | Description |
|---------|-------------|
| `train host add` | Add new host (SSH/Colab) |
| `train host browse <name>` | Browse files on host |
| `train host test <name>` | Test connection |
| `train storage list` | List storage backends |
| `train storage show <name>` | Show storage details |
| `train storage add` | Add storage backend |
| `train storage test <name>` | Test connection |
| `train recipe new <name>` | Create new recipe |
| `train recipe edit <name>` | Edit recipe in editor |
| `train recipe run <name>` | Run a recipe (same as `train run`) |
| `train recipe resume <name>` | Resume a failed/interrupted recipe |
| `train recipe resume <name> --check` | Check remote status only |
| `train recipe logs` | View execution logs |
| `train recipe logs --last` | Show last execution |
| `train recipe logs <job-id>` | Show logs for a specific job |
| `train recipe jobs` | View job history |
| `train secrets list` | List stored secrets |
| `train secrets set <key>` | Set a secret |
| `train secrets get <key>` | Get a secret |
| `train secrets delete <key>` | Delete a secret |
| `train config show` | Show configuration |
| `train config get <key>` | Get config value |
| `train config set <key> <val>` | Set config value |
| `train config tmux-setup` | Apply tmux configuration to ~/.tmux.conf |
| `train config tmux-edit` | Edit tmux options in $EDITOR |
| `train config tmux-list` | List current tmux options |
| `train colab list` | List Colab connections |
| `train colab connect` | Add Colab connection |
| `train colab run <cmd>` | Run command on Colab |
| `train colab ssh` | SSH into Colab |
| `train vast list` | List your instances |
| `train vast show <id>` | Show instance details |
| `train vast ssh <id>` | SSH into instance |
| `train vast start <id>` | Start instance |
| `train vast stop <id>` | Stop instance |
| `train vast reboot <id>` | Reboot instance |
| `train vast search` | Search for GPU offers |
| `train vast keys` | List SSH keys |
| `train vast attach-key [path]` | Attach local SSH key |

### Rare

| Command | Description |
|---------|-------------|
| `train host rm <name>` | Remove a host |
| `train storage rm <name>` | Remove storage |
| `train recipe rm <name>` | Remove a recipe |
| `train config reset` | Reset configuration |
| `train vast rm <id>` | Remove instance |
| `train pricing rates` | Show exchange rates |
| `train pricing rates --refresh` | Refresh exchange rates |
| `train pricing currency` | Show display currency |
| `train pricing currency --set CNY` | Set display currency |
| `train pricing colab` | Show Colab pricing |
| `train pricing vast` | Show Vast.ai costs |
| `train pricing convert 10 USD CNY` | Convert currency |
| `train help` | Show top-level help |
| `train version` | Show version |
| `train <command> --help` | Show command help |

## License

MIT License
