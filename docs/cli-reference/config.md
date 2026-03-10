# Config

Inspect and update runtime and tmux configuration.

## When to use it

- Inspect current config values.
- Apply or tweak tmux defaults.

## Command

```bash
train config --help
```

## CLI help output

```text
[subcommand] [args...]

Subcommands:
  show             - Show current configuration
  get <key>        - Get a config value (e.g., vast.default_disk_gb)
  set <key> <val>  - Set a config value
  reset            - Reset to default configuration
  tmux-setup       - Apply tmux configuration to ~/.tmux.conf
  tmux-edit        - Edit tmux options in $EDITOR
  tmux-list        - List all tmux options

Examples:
  train config get ui.currency
  train config set ui.currency CNY
  train config tmux-edit
  train config tmux-setup
```
