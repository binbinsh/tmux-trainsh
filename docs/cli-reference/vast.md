# Vast

Manage Vast.ai instances.

## When to use it

- List or start GPU instances.
- Connect recipe hosts to Vast instances.

## Command

```bash
train vast --help
```

## CLI help output

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
