# 存储

管理本地路径、R2、B2、S3 等存储后端。

## 何时使用

- 添加对象存储后端。
- 在 recipe 中使用前测试存储别名是否可用。

## 命令

```bash
train storage --help
```

## CLI 帮助输出

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
