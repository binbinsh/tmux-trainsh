"""Centralized help topics for trainsh CLI."""

from __future__ import annotations

import sys
from typing import Callable, Dict, List

from .help_catalog import render_command_help, render_help_index

INDEX_TEXT = render_help_index()


RECIPE_TEXT = """Python Recipe Syntax

Recipe files live under:
  ~/.config/tmux-trainsh/recipes/*.py

Public import contract:
  from trainsh import Recipe, Host, VastHost, HostPath, Storage, StoragePath

Minimal example:
```python
from trainsh import Host, Recipe

recipe = Recipe("nanochat", callbacks=["console", "sqlite"])
gpu = Host("placeholder", name="gpu")

pick = recipe.vast.pick(
    host="gpu",
    gpu_name="H200",
    num_gpus=8,
    min_gpu_ram=80,
    auto_select=True,
    create_if_missing=True,
)
fallback = recipe.vast.pick(
    host="gpu",
    gpu_name="H100",
    num_gpus=8,
    min_gpu_ram=80,
    auto_select=True,
    create_if_missing=True,
    depends_on=[pick],
    step_options={"trigger_rule": "all_failed"},
)
picked = recipe.on_one_success(id="picked_gpu", depends_on=[pick, fallback])
start = recipe.vast.start(depends_on=[picked])
ready = recipe.vast.wait_ready(timeout="30m", depends_on=[start])

with recipe.linear():
    main = recipe.session("main", host=gpu, depends_on=[ready])
    main.install_uv()
    main.run("cd /workspace/nanochat && bash /workspace/nanochat/runs/trainsh_nanochat.sh", background=True)
    main.file("/workspace/nanochat-data/trainsh_success.txt", timeout="10h")
    main.close()
```

Starter templates
  train recipe show nanochat
  train recipe run nanochat
  Bundled examples currently available:
    train recipe show nanochat
    Other bundled examples: aptup, brewup, hello

Core building blocks
  recipe = Recipe("nanochat")          Declare one recipe object
  gpu = Host("placeholder", name="gpu")
  artifacts = Storage("r2:bucket")     Explicit storage object
  gpu.path("/remote/file")             Typed remote path
  artifacts.path("/bucket/key")        Typed storage path
  recipe.session("main", host=gpu)
  with recipe.linear():
  main.run(...), main.bg(...)
  main.idle(...), main.wait(...), main.file(...), main.port(...)
  recipe.copy(...)
  recipe.latest_only(...), recipe.choose(...), recipe.join(...)
  recipe.http_wait(...), recipe.sqlite_query(...), recipe.xcom_push(...)
  recipe.notify(...), recipe.vast.start(...), recipe.vast.wait_ready(...)

Scheduling metadata
  Prefer constructor metadata:
    recipe = Recipe("nightly", schedule="@every 15m", owner="ml", tags=["nightly", "train"])

Canonical lifecycle commands
  train recipe list
  train recipe show <name>
  train recipe new <name> --template minimal
  train recipe run <name>
  train recipe resume <name>
  train recipe status
  train recipe logs
  train recipe jobs
  train recipe schedule list
"""


STATUS_TEXT = """Run Status vs Scheduler History

Use these commands for different questions:

  train recipe status
    Live/manual jobs, tmux sessions, current progress, attach commands.

  train recipe logs
    Full execution details for one job, including step results.

  train recipe jobs
    Compact recent job table.

  train recipe schedule list
    What recipes are scheduled?

  train recipe schedule status
    What did the scheduler start recently?

Rule of thumb
  If you started the run manually, begin with `train recipe status`.
  If you are checking cron-like scheduled activity, begin with `train recipe schedule status`.
"""


TOPIC_ALIASES = {
    "overview": "overview",
    "index": "overview",
    "recipe": "recipe",
    "syntax": "recipe",
    "python-recipes": "recipe",
    "run": "run",
    "resume": "resume",
    "status": "status",
    "workflow-status": "status",
    "logs": "logs",
    "jobs": "jobs",
    "schedule": "schedule",
    "transfer": "transfer",
    "host": "host",
    "storage": "storage",
    "secrets": "secrets",
    "config": "config",
    "vast": "vast",
    "colab": "colab",
    "pricing": "pricing",
    "update": "update",
}


def _show_recipe() -> None:
    print(RECIPE_TEXT)
    print()
    print(render_command_help("recipe"))


def _show_status_topic() -> None:
    print(STATUS_TEXT)
    print()
    print(render_command_help("status"))


def _show_plain(command: str) -> Callable[[], None]:
    return lambda: print(render_command_help(command))


TOPIC_HANDLERS: Dict[str, Callable[[], None]] = {
    "overview": lambda: print(INDEX_TEXT),
    "recipe": _show_recipe,
    "run": _show_plain("run"),
    "resume": _show_plain("resume"),
    "status": _show_status_topic,
    "logs": _show_plain("logs"),
    "jobs": _show_plain("jobs"),
    "schedule": _show_plain("schedule"),
    "transfer": _show_plain("transfer"),
    "host": _show_plain("host"),
    "storage": _show_plain("storage"),
    "secrets": _show_plain("secrets"),
    "config": _show_plain("config"),
    "vast": _show_plain("vast"),
    "colab": _show_plain("colab"),
    "pricing": _show_plain("pricing"),
    "update": _show_plain("update"),
}


def main(args: List[str]) -> None:
    """Main entry point for help topics."""
    if not args or args[0] in {"-h", "--help", "help"}:
        print(INDEX_TEXT)
        return

    topic = TOPIC_ALIASES.get(args[0].strip().lower())
    if topic is None:
        print(f"Unknown help topic: {args[0]}")
        print()
        print(INDEX_TEXT)
        raise SystemExit(1)

    TOPIC_HANDLERS[topic]()


if __name__ == "__main__":
    main(sys.argv[1:])
