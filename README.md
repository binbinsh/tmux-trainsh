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

```
---
MODEL = "llama-7b"
EPOCHS = 3
---

@gpu = root@vastai-instance -p 22022
@storage = r2:models

# Open a tmux pane connected to GPU host
> tmux.open @gpu as gpu

# Setup
gpu: cd /workspace && git clone https://github.com/user/repo
gpu: pip install -r requirements.txt

# Training
gpu: python train.py --model ${MODEL} --epochs ${EPOCHS}

# Wait for completion
? gpu : "Training complete" timeout=2h

# Upload results to R2
gpu:/workspace/output -> storage:/${MODEL}/

# Close the pane
> tmux.close gpu
```

## Commands

| Command | Description |
|---------|-------------|
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
