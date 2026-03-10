# 调度

查看和运行定时 recipe。

## 何时使用

- 列出已配置调度的 recipe。
- 以单次模式或常驻模式运行调度器。

## 命令

```bash
train schedule --help
```

## CLI 帮助输出

```text
Usage:
  train schedule [run] [--forever|--once] [--dag NAME] [--dags-dir PATH]
                 [--force] [--wait] [--include-invalid]
                 [--loop-interval N] [--max-active-runs N]
                 [--max-active-runs-per-dag N] [--iterations N]
                 [--sqlite-db PATH]
  train schedule list [--include-invalid] [--dags-dir PATH] [--sqlite-db PATH] [PATTERN...]
  train schedule status [--rows N] [--sqlite-db PATH]

Notes:
  --force: run all matched dags ignoring schedule
  --wait: when running, wait for started dags to finish
```
