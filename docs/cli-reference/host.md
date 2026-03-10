# Host

Manage SSH, local, Colab, and Vast-backed hosts.

## When to use it

- Register and test SSH hosts.
- Open an SSH session into a configured host.

## Command

```bash
train host --help
```

## CLI help output

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

Hosts are stored in: ~/.config/tmux-trainsh/hosts.yaml
```
