# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

tmux-trainsh is a Python CLI tool for GPU training workflow automation. It manages remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage backends (R2, B2, S3, GDrive), and automates training workflows using a custom DSL in `.recipe` files.

## Development Commands

```bash
# Install for development
uv pip install -e .

# Run the CLI
python -m trainsh
# or after installation:
train help

# Run tests
python tests/test_commands.py
```

## Architecture

### Package Structure

```
trainsh/
├── main.py              # CLI entry point, command routing
├── config.py            # YAML config loading/saving
├── constants.py         # Paths, defaults, secret key names
├── commands/            # CLI subcommands (host, vast, storage, recipe, etc.)
├── core/
│   ├── models.py        # Data models (Host, Storage, Recipe, VastInstance, etc.)
│   ├── dsl_parser.py    # Recipe DSL parser (.recipe files)
│   ├── dsl_executor.py  # Recipe execution engine
│   ├── secrets.py       # OS keychain integration
│   ├── job_state.py     # Job persistence for resume capability
│   └── tmux_session.py  # Remote tmux session management
├── services/
│   ├── vast_api.py      # Vast.ai API client
│   ├── ssh.py           # SSH connection handling
│   ├── transfer_engine.py # File transfer (rsync/rclone)
│   └── pricing.py       # Currency conversion, cost calculation
└── utils/
```

### Key Concepts

**Recipe DSL**: The `.recipe` format defines training workflows with:
- Definitions: `var`, `host`, `storage` declarations
- Execute commands: `@session > command` syntax
- Wait conditions: `wait @session "pattern"` or `wait @session idle`
- Transfers: `@src:path -> @dst:path`
- Control: `vast.pick`, `tmux.open`, `vast.wait`, etc.

**Execution Model**: Recipes create remote tmux sessions for command persistence. The executor tracks session state and supports job resume after interruption.

**Host Types**: SSH, Vast.ai instances, Google Colab (via cloudflared tunnel), Local

**Storage Types**: Local, SSH/SFTP, R2, B2, S3, GCS, Google Drive, SMB

### Configuration

All config stored in `~/.config/tmux-trainsh/`:
- `config.yaml` - Main settings
- `hosts.yaml` - SSH host definitions
- `storages.yaml` - Storage backend configs
- `recipes/` - Recipe files
- `jobs/` - Job state for resume (YAML)

### Secrets

Secrets are stored in OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service). Reference in recipes with `${secret:NAME}` syntax.

## DSL Parser Notes

The DSL parser (`core/dsl_parser.py`) handles:
- Multiline commands via `\` continuation or heredocs
- Variable interpolation: `$VAR` and `${VAR}`
- Secret references: `${secret:NAME}` (passed through, resolved at runtime)
- Duration parsing: `30s`, `5m`, `2h`

Step types: CONTROL, EXECUTE, TRANSFER, WAIT

## Testing

Tests verify all README commands are importable and produce expected output:
```bash
python tests/test_commands.py
```

## Documentation Updates

Documentation is auto-generated from two registries. **Do not edit README sections manually.**

### Single Sources of Truth

1. **`DSL_SYNTAX`** in `trainsh/core/dsl_parser.py` — all recipe DSL documentation.
   - When adding/changing DSL features, update this list.
   - `generate_syntax_reference()` renders it as markdown.
   - `train recipe syntax` prints it to the terminal.

2. **`COMMANDS_REGISTRY`** in `trainsh/main.py` — all CLI commands and subcommands.
   - When adding/removing/renaming commands, update this list.
   - `generate_commands_markdown()` renders the Commands section for README.
   - `usage` and `help_text` are auto-generated from this registry.

### Workflow

```bash
# After changing DSL_SYNTAX or COMMANDS_REGISTRY:
python scripts/update_readme.py          # Regenerate README.md sections
python scripts/update_readme.py --check  # Verify README is up to date (used by pre-commit)
```

### Pre-commit Hook

Install with `bash scripts/install-hooks.sh`. The hook (`scripts/pre-commit-check.sh`) validates:
1. Every `CONTROL_COMMANDS` entry exists in `DSL_SYNTAX`
2. Every routed command in `main.py` exists in `COMMANDS_REGISTRY`
3. README.md is not stale (runs `update_readme.py --check`)
