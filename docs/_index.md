# trainsh documentation

`trainsh` is a terminal-first workflow system for long-running GPU and automation jobs.

It combines:

- tmux-backed sessions for durable command execution
- remote hosts over SSH, Colab, and Vast.ai
- local and cloud storage backends
- Python recipes with DAG scheduling, retries, timeouts, callbacks, and runtime metadata

## Documentation map

### Get started

- [Installation](installation.md)
- [Quicktour](quicktour.md)
- [Getting started](getting-started.md)

### Tutorials

- [Write your first recipe](tutorials/first-recipe.md)
- [Run remote GPU training](tutorials/remote-gpu-training.md)
- [Build reliable workflows](tutorials/reliable-workflows.md)
- [Schedule and resume runs](tutorials/scheduling-and-resume.md)

### Guides

- [Python recipes](python-recipes.md)
- [Hosts and storage](guides/hosts-and-storage.md)
- [Branching and control flow](guides/branching-and-control-flow.md)
- [SQLite and XCom](guides/sqlite-and-xcom.md)
- [Notifications and callbacks](guides/notifications-and-callbacks.md)

### Concepts

- [Dependency DAG](concepts/dependency-dag.md)
- [tmux sessions](concepts/tmux-sessions.md)
- [Runtime metadata](concepts/runtime-metadata.md)
- [Executors and scheduling](concepts/executors.md)

### Reference

- [Package reference](package-reference/_index.md)
- [CLI reference](cli-reference/_index.md)
- [Examples](examples/_index.md)

### Internals

- [Recipe design](recipe-design.md)
- [Storage design](storage-design.md)
- [Secrets](secrets.md)
- [Documentation system](documentation.md)

## Suggested reading order

1. [Installation](installation.md)
2. [Quicktour](quicktour.md)
3. [Write your first recipe](tutorials/first-recipe.md)
4. [Python recipes](python-recipes.md)
5. [Package reference](package-reference/_index.md)

## Build the site locally

```bash
python scripts/generate_docs.py
python scripts/generate_docs.py --output ~/Projects/Personal/trainsh-home/content/docs
```
