# kitten-trainsh

GPU training workflow automation as a kitty terminal kitten.

Manage remote GPU hosts (Vast.ai, Google Colab, custom SSH), cloud storage (R2, B2, S3, Google Drive), and automate training workflows with recipes.

CLI-only: all operations are available via CLI subcommands (no TUI required).

## Installation

**From GitHub (recommended):**

```bash
bash <(curl -sL https://raw.githubusercontent.com/binbinsh/kitten-trainsh/main/install.sh) --github
```

**From local directory (for development):**

```bash
git clone https://github.com/binbinsh/kitten-trainsh.git
cd kitten-trainsh
bash install.sh
```

**Options:**
- `--github`: Clone from GitHub instead of using local directory
- `--force`: Force overwrite existing files
- `--no-deps`: Skip installing Python dependencies

## Recommended

Add a shell alias for shorter commands:

<span style="color: red; font-weight: bold;"><code>alias trainsh='kitty +kitten trainsh'</code></span>

## Quick Start

```bash
# Show help
trainsh --help

# Set up API keys
trainsh secrets set VAST_API_KEY
trainsh secrets set R2_ACCESS_KEY
trainsh secrets set B2_KEY_ID

# Add a host
trainsh host add

# Add a storage backend
trainsh storage add

# Transfer files
trainsh transfer ~/data host:myserver:/data

# Run a recipe
trainsh recipe run train
```

## Commands (by functionality)

All commands are available via `trainsh ...`.

Frequency tags:,,.

### Host Management

```bash
trainsh host list              # List configured hosts
trainsh host add               # Add new host (SSH/Colab)
trainsh host show <name>       # Show host details
trainsh host ssh <name>        # SSH into host
trainsh host browse <name>     # Browse files on host
trainsh host test <name>       # Test connection
trainsh host remove <name>     # Remove a host
```

### Storage Backends

```bash
trainsh storage list           # List storage backends
trainsh storage add            # Add storage backend
trainsh storage show <name>    # Show storage details
trainsh storage test <name>    # Test connection
trainsh storage remove <name>  # Remove storage
```

### File Transfer

```bash
trainsh transfer <src> <dst>   # Transfer files
trainsh transfer <src> <dst> --delete        # Sync with deletions
trainsh transfer <src> <dst> --exclude '*.ckpt' # Exclude patterns
trainsh transfer <src> <dst> --dry-run       # Preview transfer
```

### Recipes (Automation Workflows)

```bash
trainsh recipe list            # List recipes
trainsh recipe show <name>     # Show recipe details
trainsh recipe run <name>      # Run a recipe
trainsh recipe run <name> --no-visual        # Headless mode
trainsh recipe run <name> --host gpu=vast:12345 # Override host
trainsh recipe run <name> --var MODEL=llama-7b  # Override variable
trainsh recipe run <name> --pick-host gpu    # Pick Vast.ai host
trainsh recipe new <name>      # Create new recipe
trainsh recipe edit <name>     # Edit recipe in editor
trainsh recipe logs            # View execution logs
trainsh recipe logs --last     # Show last execution
trainsh recipe status          # View running sessions
trainsh recipe status --all    # Include completed sessions
```

### Secrets

```bash
trainsh secrets list           # List stored secrets
trainsh secrets set <key>      # Set a secret
trainsh secrets get <key>      # Get a secret
trainsh secrets delete <key>   # Delete a secret
```

### Configuration

```bash
trainsh config show            # Show configuration
trainsh config get <key>       # Get config value
trainsh config set <key> <val> # Set config value
trainsh config reset           # Reset configuration
```

### Google Colab

```bash
trainsh colab list             # List Colab connections
trainsh colab connect          # Add Colab connection
trainsh colab ssh              # SSH into Colab
trainsh colab run <cmd>        # Run command on Colab
```

### Vast.ai

```bash
trainsh vast list              # List your instances
trainsh vast show <id>         # Show instance details
trainsh vast ssh <id>          # SSH into instance
trainsh vast start <id>        # Start instance
trainsh vast stop <id>         # Stop instance
trainsh vast destroy <id>      # Destroy instance
trainsh vast reboot <id>       # Reboot instance
trainsh vast search            # Search for GPU offers
trainsh vast keys              # List SSH keys
trainsh vast attach-key        # Attach local SSH key
```

### Pricing

```bash
trainsh pricing rates          # Show exchange rates
trainsh pricing rates --refresh              # Refresh exchange rates
trainsh pricing currency       # Show display currency
trainsh pricing currency --set CNY           # Set display currency
trainsh pricing colab          # Show Colab pricing
trainsh pricing colab --subscription "Colab Pro:11.99:USD:100" # Set subscription
trainsh pricing vast           # Show Vast.ai costs
trainsh pricing convert 10 USD CNY           # Convert currency
```

### Help and Version

```bash
trainsh --help                 # Show top-level help
trainsh --version              # Show version
trainsh <command> --help       # Show command help
```

Supported secret keys:
- `VAST_API_KEY` - Vast.ai API key
- `HF_TOKEN` - HuggingFace token
- `R2_ACCESS_KEY`, `R2_SECRET_KEY` - Cloudflare R2
- `B2_KEY_ID`, `B2_APPLICATION_KEY` - Backblaze B2
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - Amazon S3
- `GITHUB_TOKEN` - GitHub token
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` - AI APIs

Or add Colab as a host for unified management:
```bash
trainsh host add   # Select "Google Colab" type
```

## Configuration

Config files are stored in `~/.config/kitten-trainsh/`:

```
~/.config/kitten-trainsh/
├── config.toml        # Main settings
├── hosts.toml         # SSH hosts (including Colab)
├── storages.toml      # Storage backends
├── logs/              # Execution logs
└── recipes/           # Recipe files
```

## Recipe DSL Example

```
---
MODEL = "llama-7b"
EPOCHS = 3
---

@gpu = root@vastai-instance -p 22022
@storage = r2:models

# Setup
gpu: cd /workspace && git clone https://github.com/user/repo
gpu: pip install -r requirements.txt

# Training
gpu: python train.py --model ${MODEL} --epochs ${EPOCHS}

# Wait for completion
? gpu : "Training complete"

# Upload results to R2
gpu:/workspace/output -> storage:/${MODEL}/
```

## Requirements

- kitty terminal
- Python 3.11+
- Optional: `rsync`, `rclone`, `cloudflared`

## License

MIT License
