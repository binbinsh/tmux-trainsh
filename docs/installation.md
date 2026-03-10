# Installation

## Requirements

- Python 3.10 or newer
- `tmux`
- Optional but useful: `rsync`, `rclone`

## Install as a tool

```bash
uv tool install tmux-trainsh
```

This is the simplest path if you only want to use `trainsh`.

## Install for local development

```bash
git clone https://github.com/binbinsh/tmux-trainsh
cd tmux-trainsh
uv pip install -e .
```

To refresh the exported Hugo documentation:

```bash
python scripts/generate_docs.py
```

## Sanity check

Verify the CLI is available:

```bash
train --help
train help recipe
```

Verify `tmux` is installed:

```bash
tmux -V
```

## Next steps

1. [Quicktour](quicktour.md)
2. [Getting started](getting-started.md)
3. [Write your first recipe](tutorials/first-recipe.md)
