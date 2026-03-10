# Storage

Manage storage backends such as local paths, R2, B2, and S3.

## When to use it

- Add an object store backend.
- Check whether a storage alias works before using it in recipes.

## Command

```bash
train storage --help
```

## CLI help output

```text
[subcommand] [args...]

Subcommands:
  list             - List configured storage backends
  add              - Add a new storage backend
  show <name>      - Show storage details
  rm <name>        - Remove a storage backend
  test <name>      - Test connection to storage

Supported storage types:
  - local          Local filesystem
  - ssh            SSH/SFTP
  - gdrive         Google Drive
  - r2             Cloudflare R2
  - b2             Backblaze B2
  - s3             Amazon S3 (or compatible)
  - gcs            Google Cloud Storage
  - smb            SMB/CIFS

Storages are stored in: ~/.config/tmux-trainsh/storages.toml
```
