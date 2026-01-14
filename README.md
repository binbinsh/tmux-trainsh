# tmux-trainsh

The missing training automation for public cloud GPU and storage.

Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage (R2, B2, S3, GDrive), and automate training workflows with a simple recipe DSL.

## Requirements

- Python 3.11+
- tmux (any version with `wait-for` support)
- Optional: `rsync`, `rclone`

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/binbinsh/tmux-trainsh/main/install.sh | bash -s -- --github
```

## Quick Start

```bash
# Show help
train --help

# Set up API keys
train secrets set VAST_API_KEY
train secrets set R2_ACCESS_KEY

# Add a host
train host add

# Add a storage backend
train storage add

# Run a recipe
train recipe run train
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

## Recipe DSL

Recipe files (`.recipe`) define automated training workflows with a simple DSL.

### Quick Example

```
# Variables
var MODEL = llama-7b
var WORKDIR = /workspace/train

# Hosts
host gpu = placeholder
host backup = myserver

# Storage
storage output = r2:my-bucket

# Workflow
vast.pick @gpu num_gpus=1 min_gpu_ram=24
vast.wait timeout=5m
tmux.open @gpu

@gpu > cd $WORKDIR && git clone https://github.com/user/repo
@gpu > pip install -r requirements.txt
@gpu > python train.py --model $MODEL &

wait @gpu idle timeout=2h

@gpu:$WORKDIR/model -> @output:/models/$MODEL/
@gpu:$WORKDIR/model -> @backup:/backup/

vast.stop
tmux.close @gpu
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

Run commands on a host:

```
@host > command
@host > command &
@host timeout=2h > command
```

| Syntax | Description |
|--------|-------------|
| `@host > cmd` | Run command, wait for completion |
| `@host > cmd &` | Run command in background |
| `@host timeout=DURATION > cmd` | Run with custom timeout (default: 10m) |

#### Wait Commands

Wait for conditions:

```
wait @host "pattern" timeout=DURATION
wait @host file=PATH timeout=DURATION
wait @host port=PORT timeout=DURATION
wait @host idle timeout=DURATION
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

| Command | Description |
|---------|-------------|
| `tmux.open @host` | Open tmux session on host |
| `tmux.close @host` | Close tmux session |
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

| Command | Description |
|---------|-------------|
| `train exec '<dsl>'` | Execute DSL commands directly |
| `train exec '@host > cmd'` | Run command on remote host |
| `train exec '@src:path -> @dst:path'` | Transfer files |
| `train host list` | List configured hosts |
| `train host add` | Add new host (SSH/Colab) |
| `train host show <name>` | Show host details |
| `train host ssh <name>` | SSH into host |
| `train host browse <name>` | Browse files on host |
| `train host test <name>` | Test connection |
| `train host remove <name>` | Remove a host |
| `train storage list` | List storage backends |
| `train storage add` | Add storage backend |
| `train storage show <name>` | Show storage details |
| `train storage test <name>` | Test connection |
| `train storage remove <name>` | Remove storage |
| `train transfer <src> <dst>` | Transfer files |
| `train transfer <src> <dst> --delete` | Sync with deletions |
| `train transfer <src> <dst> --exclude '*.ckpt'` | Exclude patterns |
| `train transfer <src> <dst> --dry-run` | Preview transfer |
| `train recipe list` | List recipes |
| `train recipe show <name>` | Show recipe details |
| `train recipe run <name>` | Run a recipe |
| `train recipe run <name> --no-visual` | Headless mode |
| `train recipe run <name> --host gpu=vast:123` | Override host |
| `train recipe run <name> --var MODEL=llama-7b` | Override variable |
| `train recipe run <name> --pick-host gpu` | Pick Vast.ai host |
| `train recipe new <name>` | Create new recipe |
| `train recipe edit <name>` | Edit recipe in editor |
| `train recipe logs` | View execution logs |
| `train recipe logs --last` | Show last execution |
| `train recipe status` | View running sessions |
| `train recipe status --all` | Include completed sessions |
| `train recipe resume` | Resume last interrupted recipe |
| `train recipe jobs` | View job history |
| `train secrets list` | List stored secrets |
| `train secrets set <key>` | Set a secret |
| `train secrets get <key>` | Get a secret |
| `train secrets delete <key>` | Delete a secret |
| `train config show` | Show configuration |
| `train config get <key>` | Get config value |
| `train config set <key> <val>` | Set config value |
| `train config reset` | Reset configuration |
| `train colab list` | List Colab connections |
| `train colab connect` | Add Colab connection |
| `train colab ssh` | SSH into Colab |
| `train colab run <cmd>` | Run command on Colab |
| `train vast list` | List your instances |
| `train vast show <id>` | Show instance details |
| `train vast ssh <id>` | SSH into instance |
| `train vast start <id>` | Start instance |
| `train vast stop <id>` | Stop instance |
| `train vast destroy <id>` | Destroy instance |
| `train vast reboot <id>` | Reboot instance |
| `train vast search` | Search for GPU offers |
| `train vast keys` | List SSH keys |
| `train vast attach-key` | Attach local SSH key |
| `train pricing rates` | Show exchange rates |
| `train pricing rates --refresh` | Refresh exchange rates |
| `train pricing currency` | Show display currency |
| `train pricing currency --set CNY` | Set display currency |
| `train pricing colab` | Show Colab pricing |
| `train pricing vast` | Show Vast.ai costs |
| `train pricing convert 10 USD CNY` | Convert currency |
| `train --help` | Show top-level help |
| `train --version` | Show version |
| `train <command> --help` | Show command help |

## License

MIT License
