# tmux-trainsh

<!-- AUTO-GENERATED FROM trainsh.commands.help_catalog; DO NOT EDIT DIRECTLY. -->

`tmux-trainsh` is a terminal-first workflow runner for GPU and remote automation work.

Current version: `26.319.900`

README is the quick overview and landing page. The canonical command reference stays in the CLI:

```bash
train help
train --help
train recipe --help
train host --help
train transfer --help
```

Those commands are generated from the same canonical help source.

## Install

Install from PyPI with uv:

```bash
uv tool install -U tmux-trainsh
train help
```

Install the latest GitHub version with uv:

```bash
uv tool install -U git+https://github.com/binbinsh/tmux-trainsh
```

Or use the install script:

```bash
curl -LsSf https://raw.githubusercontent.com/binbinsh/tmux-trainsh/main/install.sh | bash
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
train exec nanochat
train recipe status --last
```

## Bundled Examples

Current bundled examples: `aptup, brewup, hello, nanochat`

## Recipe Authoring

Public imports:

```python
from trainsh import Recipe, Host, VastHost, HostPath, Storage, StoragePath, load_python_recipe, local
```

Main authoring model:

- `Recipe`
- `Host` / `VastHost` / `HostPath`
- `Storage` / `StoragePath`
- `host.tmux(...)`
- `local.tmux(...)`

## Runtime Guarantees

- `.pyrecipe` recipes run as: load -> dependency graph from `depends_on` -> executor run
- Airflow-like retry / timeout / callback / trigger-rule semantics remain supported
- Supported executor aliases include `sequential`, `thread_pool`, `process_pool`, `local`, `airflow`, `celery`, `dask`, and `debug`
- Kubernetes executor remains unsupported

## Maintenance

To refresh this file after editing the canonical help catalog:

```bash
python3 scripts/sync_cli_docs.py
```

Regression commands:

```bash
python3 tests/test_commands.py
python3 -m unittest tests.test_runtime_persist tests.test_pyrecipe_runtime tests.test_runtime_semantics tests.test_provider_dispatch tests.test_ti_dependencies
uv run --with coverage python scripts/check_runtime_coverage.py
```
