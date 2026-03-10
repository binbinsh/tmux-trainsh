# Python recipes

`tmux-trainsh` recipes are authored as Python modules.

This page is the authoring guide. For exact method signatures and parameter tables, use the [package reference](package-reference/_index.md).

## Public API

User recipes should keep using:

```python
from trainsh.pyrecipe import *
```

`recipe(...)` binds the active recipe for the module. The rest of the file uses flat top-level helpers such as `var(...)`, `session(...)`, and `sql_query(...)`. `load_python_recipe(path)` loads one `.py` recipe file and returns its recipe object.

## Minimal Example

```python
from trainsh.pyrecipe import *

recipe(
    "example",
    schedule="@every 30m",
    executor="thread_pool",
    workers=4,
    callbacks=["console", "sqlite"],
)

var("MODEL", "llama-7b")
host("gpu", "your-server")

ready = latest_only(fail_if_unknown=False, id="latest_only")
main = session("main", on="gpu", after=ready)
clone = main(
    "cd /tmp && git clone https://github.com/example/project.git project",
)
train = main.bg(
    "cd /tmp/project && python train.py --model $MODEL",
    after=clone,
)
main.wait("training finished", timeout="2h", after=train)
main.idle(timeout="2h", after=train)
storage_wait(
    "artifacts",
    "/models/$MODEL/done.txt",
    after=train,
)
notice("Training finished", after=train)
```

## Features

The Python runtime supports:

- dependency scheduling with `after=...`
- executor aliases such as `sequential`, `thread_pool`, `process_pool`, `local`, `airflow`, `celery`, `dask`, and `debug`
- session-oriented helpers for tmux/session workflows: `session`, `main(...)`, `main.bg(...)`, `main.idle(...)`, `main.wait(...)`, `main.file(...)`, and `main.port(...)`
- Airflow-like step options including `retries`, `retry_delay`, `execution_timeout`, `retry_exponential_backoff`, `trigger_rule`, pools, and callbacks
- control helpers such as `latest_only`, `choose`, `short_circuit`, `skip_if`, `skip_if_not`, and `join`
- storage helpers including `storage_wait`, `storage_upload`, `storage_download`, `storage_copy`, `storage_move`, `storage_sync`, and `storage_remove`
- SQLite helpers including `sql_query`, `sql_exec`, and `sql_script`
- XCom-like helpers including `xcom_push` and `xcom_pull`

## Recommended reading around this page

- [Write your first recipe](tutorials/first-recipe.md)
- [tmux sessions](concepts/tmux-sessions.md)
- [Recipe authoring reference](package-reference/recipe-builder.md)
- [Session API reference](package-reference/session-api.md)

## Scheduling

Scheduler metadata is usually declared directly in `recipe(...)`:

```python
recipe("nightly-train", schedule="@every 15m", owner="ml", tags=["train", "nightly"])
```

Relevant commands:

```bash
train schedule list
train schedule run --once
train schedule run --forever
train schedule status
```

Runtime metadata is stored in `~/.config/tmux-trainsh/runtime.db`.

## Resume

Python recipes can resume from the latest saved checkpoint:

```bash
train resume example
train resume example --var MODEL=llama-70b
```

Resume restores the saved job state, resolved hosts, and tmux session mapping. Host overrides are intentionally not supported during resume; use a fresh `train run ... --host ...` when you need to move the workflow to a different machine.

Recipe files are managed with:

```bash
train recipes list
train recipes show hello
train recipes show feature-tour
train recipes new my-flow --template minimal
train recipes new feature-demo --template feature-tour
train help recipe
```

Common runtime inspection commands:

```bash
train status
train logs
train jobs
```
