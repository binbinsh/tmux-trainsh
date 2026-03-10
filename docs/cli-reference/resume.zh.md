# 恢复

恢复某个 recipe 最近一次中断或失败的运行。

## 何时使用

- 从最近一次持久化的运行时状态继续执行。
- 在中断后恢复执行，而不需要手工重建 tmux 状态。

## 命令

```bash
train resume --help
```

## CLI 帮助输出

```text
Usage: train resume <name> [options]

Options:
  --var NAME=VALUE  Override variable while resuming

Host overrides are not supported when resuming.
```

## 说明

- `resume` 会恢复已保存的主机解析和 tmux 状态，只支持 `--var` 覆盖。
