# Instructions for tmux-trainsh

tmux-trainsh is a CLI tool for training large language models using various cloud services and internet-based resources. It uses tmux for terminal management.

## General Instructions
- Always query context7 for the most recent docs and best practices.
- Always use `uv` (not pip or conda) for Python. Keep `.venv` in the project root.
- Prefer ast-grep (cmd: `sg`) over regex/string-replace for code manipulation.
- Prefer ripgrep (cmd: `rg`) over grep or find for file searching.
- Always fix issues at the root cause. Do not use workarounds, monkey patches, or dirty hacks.
- No backward compatibility; remove deprecated code paths immediately.
- After changes, clean up dead code, unused imports, and obsolete comments.
- All comments, logs and documentations in English.
- Include all possible end-user commands in the root README.md file, categorize them by frequences.
- Place detailed development documentation in docs/*.md (use lowercase filenames)

## Architecture

### Terminal Management
- Uses tmux for all terminal operations (no kitty dependency)
- `TmuxController` class in `trainsh/core/dsl_executor.py` handles:
  - Creating windows/panes with `tmux new-window` / `tmux split-window`
  - Sending commands with `tmux send-keys`
  - Capturing output with `tmux capture-pane`
  - Command completion detection with `tmux wait-for`

### Recipe DSL
- Control commands: `> tmux.open`, `> tmux.close`, `> notify`, `> vast.*`
- Execute commands: `host: command`
- Transfer commands: `source -> dest`
- Wait commands: `? host: "pattern" timeout=N`

## Reference
- https://man7.org/linux/man-pages/man1/tmux.1.html
- https://github.com/tmux/tmux/wiki
