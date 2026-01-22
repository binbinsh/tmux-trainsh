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
├── config.py            # TOML config loading/saving
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
- `config.toml` - Main settings
- `hosts.toml` - SSH host definitions
- `storages.toml` - Storage backend configs
- `recipes/` - Recipe files
- `jobs/` - Job state for resume

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

**IMPORTANT:** When making code changes, always update documentation to stay in sync:

1. **`trainsh/main.py`** - Update `help_text` variable when:
   - Adding/removing/renaming commands
   - Changing command syntax or options
   - Adding new DSL features

2. **`README.md`** - Update when:
   - Adding/removing/renaming commands (update Commands tables)
   - Changing CLI syntax or options
   - Adding new features or DSL syntax
   - Changing configuration file structure

3. **Keep in sync:**
   - `help_text` in `main.py` should be a concise summary of README content
   - Command tables in README should match actual CLI commands
   - DSL syntax in both files should match `core/dsl_parser.py` implementation
