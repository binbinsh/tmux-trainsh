# tmux-trainsh collaboration rules

A terminal-first workflow runner for GPU and remote automation (Python; the CLI is `train`).

## Hard constraints

- The version format is `major.yyyy.commit-count`; before committing, make `pyproject.toml`, the CLI output, and the documentation agree, and make the committed tree match `git rev-list --count HEAD`.
- Prefer writing a Python recipe for repeatable automation over ad-hoc `ssh`/`bash` polling; use `train host run`, `train vast run`, or `train exec` for one-off commands.
- Use named storage or `Storage(...)` objects instead of hand-writing `hf buckets` shell commands.
- Keep individual implementation files under roughly 800 lines.

## Regression commands

```bash
python3 tests/test_commands.py
uv run --with coverage python scripts/check_runtime_coverage.py
```
