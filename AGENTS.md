# AGENTS

## Versioning

- Project versions use `major.yyyy.commit-count`.
- Keep `pyproject.toml`, CLI output, and docs aligned to the same normalized string.
- When preparing a commit, set the version to the next git commit count so the committed tree matches `git rev-list --count HEAD`.
- Example: `1.2026.115`

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
  - `host.tmux(...)`
  - `local.tmux(...)`

## Recipe-First Workflow

- For repeatable automation, prefer Python recipe authoring over ad-hoc `ssh`, `bash`, or manual polling loops.
- For one-off remote commands, prefer `train host run <name> -- <command>` or `train vast run <id> -- <command>` over raw `ssh`.
- Prefer `train run <recipe>` or `train exec <recipe>` for immediate execution.
- Prefer `train exec --code ...` or `train exec <<'EOF' ... EOF` when a temporary one-off recipe is clearer than creating a file.
- Prefer `train recipe show <name>` and `train help` when you need to inspect or recall the recipe surface.
- For Vast automation, prefer `recipe.vast.pick(...)`, `recipe.vast.start(...)`, and `recipe.vast.wait_ready(...)` over manually assembling SSH endpoints.
- Prefer `with local.tmux(...) as tmux:` or `with gpu.tmux(...) as tmux:` for straightforward tmux-backed flows.
- Let tmux blocks chain by file order by default.
- Use explicit `depends_on` only for branch fallback, fan-in/join, or cross-block edges.
- `depends_on=` may be a single handle or a list of handles.
- For hosts saved with `train host add`, prefer using the alias directly in recipes, such as `Host("gpu-box").tmux("main")`.
- Keep Python variables for handles only when they anchor a later stage or branch.
- Reuse a tmux context later by name with `gpu.tmux("work")` instead of carrying one Python variable across the whole file.
- Use `tmux.after(...)` only to set default dependencies for future tmux steps; do not treat it as a retroactive open-step rewrite.

## Storage Guidance

- Treat Hugging Face Buckets as a first-class storage backend, alongside `r2`, `b2`, `gcs`, `s3`, `ssh`, and local storage.
- Prefer a named storage or a Python `Storage(...)` object over hand-written shell calls to `hf buckets`.
- For Python recipes, prefer explicit storage specs such as:
  - `Storage("hf:<namespace>/<bucket>")`
  - `Storage("r2:<bucket>")`
  - `Storage({"type": "hf", "config": {"bucket": "<namespace>/<bucket>"}})`
- For CLI transfers, the direct HF endpoint form is `hf:<namespace>/<bucket>:/path`.
- Prefer the colon path form for HF buckets because the bucket id itself contains `/`.
- For HF bucket authentication, prefer `HF_TOKEN` or a storage-scoped secret like `<STORAGE_NAME>_HF_TOKEN`.
- When moving data between local paths, hosts, and HF buckets, prefer `train transfer` or recipe storage steps over raw `hf buckets sync`.
- For bucket creation in recipes, prefer `recipe.storage_ensure_bucket(...)` instead of shelling out.

## Runtime Guarantees

- `.pyrecipe` recipes still run as: load -> dependency graph from `depends_on` -> executor run.
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
