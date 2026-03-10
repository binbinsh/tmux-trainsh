# 传输

在主机和存储后端之间复制数据。

## 何时使用

- 把产物从远端主机拉回本地。
- 在本地路径和存储后端之间同步文件。

## 命令

```bash
train transfer --help
```

## CLI 帮助输出

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
