# 配置

查看和修改运行时与 tmux 配置。

## 何时使用

- 查看当前配置值。
- 调整或应用 tmux 默认配置。

## 命令

```bash
train config --help
```

## CLI 帮助输出

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
