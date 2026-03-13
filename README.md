# tmux-trainsh

`tmux-trainsh` is a terminal-first workflow runner for GPU and remote automation work.

README is the quick overview and entry point. The canonical command reference is in the CLI:

```bash
train --help
train help
train help recipe
train help status
train <command> --help
```

## Install

```bash
uv tool install tmux-trainsh
train --help
```

## Core Entry Points

```bash
train recipe --help
train host --help
train storage --help
train transfer --help
train secrets --help
train config --help
train vast --help
train colab --help
train pricing --help
```

## Quick Start

```bash
train secrets set VAST_API_KEY
train host add
train storage add

train recipe show nanochat
train recipe run nanochat
train recipe status --last
```

Current bundled examples:
`nanochat`, `aptup`, `brewup`, `hello`

## Published Artifacts

The `nanochat` recipe artifacts for this release are published at:

- [binbinsh/tmux-trainsh-nanochat](https://huggingface.co/binbinsh/tmux-trainsh-nanochat)

This repository contains the generated `base` and `sft` checkpoints, the base evaluation CSV, the generated report, and the success marker from the completed `nanochat` run that shipped with this version.

## Recipe Authoring

Public imports:

```python
from trainsh import Recipe, Host, VastHost, HostPath, Storage, StoragePath, load_python_recipe
```

Main authoring model:

- `Recipe`
- `Host` / `VastHost` / `HostPath`
- `Storage` / `StoragePath`
- `recipe.session(...)`
- `with recipe.linear():`

## Runtime Guarantees

- `.py` recipes run as: load -> dependency graph from `depends_on` -> executor run
- Airflow-like retry / timeout / callback / trigger-rule semantics remain supported
- Supported executor aliases include `sequential`, `thread_pool`, `process_pool`, `local`, `airflow`, `celery`, `dask`, and `debug`
- Kubernetes executor remains unsupported

## Testing

```bash
python3 tests/test_commands.py
python3 -m unittest tests.test_runtime_persist tests.test_pyrecipe_runtime tests.test_runtime_semantics tests.test_provider_dispatch tests.test_ti_dependencies
uv run --with coverage python scripts/check_runtime_coverage.py
```
