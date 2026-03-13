# AGENTS

## Versioning

- Project versions use packaging-normalized date-based versions.
- Keep `pyproject.toml`, CLI output, and docs aligned to the same normalized string.
- Example: `26.313.2342`

## Pyrecipe Rules

- Keep implementation files across the repository under 800 lines when possible.
- Keep repository file basenames reasonably short, but prefer explicit names over opaque abbreviations.
- Use standard technical abbreviations only when they are already universal in the codebase, such as `tmux`, `ssh`, or `sqlite`.
- Aim for basenames at 28 characters or fewer when possible; exceed that only when a materially clearer name is worth it.
- Keep the Python recipe runtime split across multiple files.
- Keep `trainsh/pyrecipe` implementation files under 800 lines when possible.
- Prefer explicit Python objects over string mini-DSLs.
- Keep the main authoring model centered around:
  - `Recipe`
  - `Host` / `VastHost` / `HostPath`
  - `Storage` / `StoragePath`
  - `recipe.session(...)`
  - `with recipe.linear():`

## Runtime Guarantees

- `.py` recipes still run as: load -> dependency graph from `depends_on` -> executor run.
- Airflow-like retry / timeout / callback / trigger-rule semantics remain supported.
- Supported executor aliases include:
  - `sequential`
  - `thread_pool`
  - `process_pool`
  - `local`
  - `airflow`
  - `celery`
  - `dask`
  - `debug`
- Kubernetes executor remains unsupported.

## Docs And Help

- `train --help`, `train help`, and command-local `--help` must be easy to navigate.
- README is the landing page and overview; the CLI help is the canonical command reference.

## Regression Commands

```bash
python3 tests/test_commands.py
python3 -m unittest tests.test_runtime_persist tests.test_pyrecipe_runtime tests.test_runtime_semantics tests.test_provider_dispatch tests.test_ti_dependencies
uv run --with coverage python scripts/check_runtime_coverage.py
```
