# Vast

管理 Vast.ai 实例。

## 何时使用

- 列出或启动 GPU 实例。
- 把 recipe 主机关联到 Vast 实例。

## 命令

```bash
train vast --help
```

## CLI 帮助输出

```text
[subcommand] [args...]

Subcommands:
  list              - List your Vast.ai instances
  show <id>         - Show instance details
  ssh <id>          - SSH into instance
  start <id>        - Start instance
  stop <id>         - Stop instance
  rm <id>           - Remove instance
  reboot <id>       - Reboot instance
  search            - Search for GPU offers
  keys              - List SSH keys
  attach-key [path] - Attach local SSH key (default: ~/.ssh/id_rsa.pub)

Examples:
  train vast list
  train vast ssh 12345
  train vast start 12345
```
