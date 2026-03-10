# Transfer

Copy data between hosts and storage backends.

## When to use it

- Move artifacts off a remote host.
- Sync files between local paths and storage backends.

## Command

```bash
train transfer --help
```

## CLI help output

```text
<source> <destination> [options]

Transfer files between local, remote hosts, and cloud storage.

Examples:
  train transfer ~/data host:myserver:/data
  train transfer host:myserver:/models ~/models
  train transfer ~/data storage:gdrive:/backups

Options:
  --host, -H <name>     Remote host name or ID
  --delete, -d          Delete files at destination not in source
  --exclude, -e <pat>   Exclude pattern (can be repeated)
  --dry-run             Show what would be transferred
```
