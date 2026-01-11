# kitten-trainsh

GPU training workflow automation as a kitty terminal kitten.

Manage remote GPU hosts (Vast.ai, Google Colab, custom SSH), cloud storage (R2, B2, S3, Google Drive), and automate training workflows with recipes.

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

## Quick Start

```bash
# Launch interactive TUI
kitty +kitten trainsh config tui

# Set up API keys
kitty +kitten trainsh secrets set VAST_API_KEY
kitty +kitten trainsh secrets set R2_ACCESS_KEY
kitty +kitten trainsh secrets set B2_KEY_ID

# Add a host
kitty +kitten trainsh host add

# Add a storage backend
kitty +kitten trainsh storage add

# Transfer files
kitty +kitten trainsh transfer ~/data host:myserver:/data
```

## Commands

### Interactive TUI

```bash
kitty +kitten trainsh config tui         # Launch TUI (manage hosts, storage, recipes)
```

### Host Management

Supports SSH hosts and Google Colab notebooks.

```bash
kitty +kitten trainsh host list              # List configured hosts
kitty +kitten trainsh host add               # Add new host (SSH/Colab)
kitty +kitten trainsh host ssh <name>        # SSH into host
kitty +kitten trainsh host browse <name>     # Browse files on host
kitty +kitten trainsh host show <name>       # Show host details
kitty +kitten trainsh host test <name>       # Test connection
kitty +kitten trainsh host remove <name>     # Remove a host
```

### Vast.ai

Manage GPU instances on Vast.ai marketplace.

```bash
kitty +kitten trainsh vast list              # List your instances
kitty +kitten trainsh vast ssh <id>          # SSH into instance
kitty +kitten trainsh vast show <id>         # Show instance details
kitty +kitten trainsh vast start <id>        # Start instance
kitty +kitten trainsh vast stop <id>         # Stop instance
kitty +kitten trainsh vast destroy <id>      # Destroy instance
kitty +kitten trainsh vast reboot <id>       # Reboot instance
kitty +kitten trainsh vast search            # Search for GPU offers
kitty +kitten trainsh vast keys              # List SSH keys
kitty +kitten trainsh vast attach-key        # Attach local SSH key
```

### Google Colab

```bash
kitty +kitten trainsh colab connect          # Add Colab connection
kitty +kitten trainsh colab ssh              # SSH into Colab
kitty +kitten trainsh colab list             # List connections
kitty +kitten trainsh colab run <cmd>        # Run command on Colab
```

Or add Colab as a host for unified management:
```bash
kitty +kitten trainsh host add   # Select "Google Colab" type
```

### Storage Backends

Supports local, SSH/SFTP, Cloudflare R2, Backblaze B2, Amazon S3, Google Drive, GCS, and SMB.

```bash
kitty +kitten trainsh storage list           # List storage backends
kitty +kitten trainsh storage add            # Add storage backend
kitty +kitten trainsh storage show <name>    # Show storage details
kitty +kitten trainsh storage test <name>    # Test connection
kitty +kitten trainsh storage remove <name>  # Remove storage
```

### File Transfer

```bash
kitty +kitten trainsh transfer <src> <dst>   # Transfer files
kitty +kitten trainsh transfer ~/data host:server:/data
kitty +kitten trainsh transfer host:server:/out storage:r2:/backups
```

### Recipes (Automation Workflows)

```bash
kitty +kitten trainsh recipe list            # List recipes
kitty +kitten trainsh recipe run <name>      # Run a recipe
kitty +kitten trainsh recipe new <name>      # Create new recipe
kitty +kitten trainsh recipe edit <name>     # Edit recipe in editor
kitty +kitten trainsh recipe status          # View running recipe sessions
kitty +kitten trainsh recipe logs            # View execution logs
```

### Secrets

```bash
kitty +kitten trainsh secrets list           # List stored secrets
kitty +kitten trainsh secrets set <key>      # Set a secret
kitty +kitten trainsh secrets get <key>      # Get a secret
```

Supported secret keys:
- `VAST_API_KEY` - Vast.ai API key
- `HF_TOKEN` - HuggingFace token
- `R2_ACCESS_KEY`, `R2_SECRET_KEY` - Cloudflare R2
- `B2_KEY_ID`, `B2_APPLICATION_KEY` - Backblaze B2
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` - Amazon S3
- `GITHUB_TOKEN` - GitHub token
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` - AI APIs

### Configuration

```bash
kitty +kitten trainsh config show            # Show configuration
kitty +kitten trainsh config set <key> <val> # Set config value
kitty +kitten trainsh config get <key>       # Get config value
```

### Pricing

```bash
kitty +kitten trainsh pricing rates          # Show exchange rates
kitty +kitten trainsh pricing vast           # Show Vast.ai costs
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
