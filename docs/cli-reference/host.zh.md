# 主机

管理 SSH、本地、Colab 和 Vast 主机。

## 何时使用

- 注册并测试 SSH 主机。
- 连接到已配置主机的 SSH 会话。

## 命令

```bash
train host --help
```

## CLI 帮助输出

```text
[subcommand] [args...]

Subcommands:
  list             - List configured hosts
  add              - Add a new host
  edit <name>      - Edit an existing host
  show <name>      - Show host details
  ssh <name>       - SSH into a host
  browse <name>    - Browse files on a host
  rm <name>        - Remove a host
  test <name>      - Test connection to a host

Host types:
  - SSH            Standard SSH host (supports JumpHost/ProxyCommand/cloudflared)
  - Colab          Google Colab notebook (via cloudflared/ngrok)

For Vast.ai instances, use: train vast

Hosts are stored in: ~/.config/tmux-trainsh/hosts.toml
```
