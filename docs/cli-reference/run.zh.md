# 运行

立即执行一个 recipe。

## 何时使用

- 按需启动一次工作流。
- 为单次运行覆盖变量或主机映射。

## 命令

```bash
train run --help
```

## CLI 帮助输出

```text
Usage: train run <name> [options]

Options:
  --host NAME=HOST  Override host (e.g., --host gpu=vast:12345)
  --var NAME=VALUE  Override variable
  --pick-host NAME  Interactively select host from vast.ai
  --executor NAME   Executor: sequential|thread_pool|process_pool|local_executor|airflow|celery|dask (aliases supported)
                    kubernetes/executor is intentionally not supported in this runtime
  --max-workers N   Worker count (default: 4)
  --workers N       Alias for --max-workers
  --concurrency N   Alias for --max-workers
  --parallelism N   Alias for --max-workers
  --executor-arg KEY=VALUE
  --executor-kwargs JSON_OR_KV
  --callback NAME   Callback sink: console|sqlite (repeatable or comma-separated)
```
