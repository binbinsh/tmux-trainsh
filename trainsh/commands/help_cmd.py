"""Centralized help topics for trainsh CLI."""

from __future__ import annotations

import sys
from typing import Callable, Dict, List


INDEX_TEXT = """tmux-trainsh Help

Help Topics
  recipe      Python recipe syntax, examples, and lifecycle
  recipes     Recipe file management commands
  run         Recipe execution options
  resume      Resume behavior and constraints
  status      Session and live job inspection
  logs        Execution log inspection
  jobs        Job history inspection
  schedule    Scheduler commands
  transfer    File transfer commands
  host        Host management
  storage     Storage backend management
  secrets     Secret management
  config      Configuration and tmux settings
  vast        Vast.ai management
  colab       Google Colab integration
  pricing     Pricing and currency tools
  update      Update checks

Examples
  train help
  train help recipe
  train help run
  train help schedule
  train help host
"""


RECIPE_TEXT = """Python Recipe Syntax

Recipe files live under:
  ~/.config/tmux-trainsh/recipes/*.py

Public import contract:
  from trainsh.pyrecipe import *

Minimal example:
```python
from trainsh.pyrecipe import *

recipe("example", callbacks=["console", "sqlite"])
var("MODEL", "llama-7b")
host("gpu", "your-server")

prepare = host_test("gpu", timeout="15s")
main = session("main", on="gpu", after=prepare)
clone = main("cd /tmp && git clone https://github.com/example/project.git project")
train = main.bg("cd /tmp/project && python train.py --model $MODEL", after=clone)
done = main.idle(timeout="2h", after=train)
notice("Training finished", after=done)
main.close(after=done)
```

Starter templates
  train recipes new demo --template minimal
  train recipes new feature-demo --template feature-tour
  train recipes show feature-tour

Core building blocks
  var("NAME", "value")                 Define variables used as $NAME
  host("gpu", "user@host")             Define host aliases
  storage("artifacts", "r2:bucket")
  session("main", on="gpu")
  main(...), main.bg(...)
  main.idle(...), main.wait(...), main.file(...), main.port(...)
  transfer(...)
  latest_only(...), choose(...), join(...)
  http_wait(...), sql_query(...), xcom_push(...)
  notice(...), vast_pick(...), vast_wait(...)

Scheduling metadata
  Prefer recipe(...) metadata:
    recipe("nightly", schedule="@every 15m", owner="ml", tags=["nightly", "train"])

Recipe lifecycle commands
  train recipes list
  train recipes show <name>
  train recipes new <name> --template minimal|feature-tour
  train run <name>
  train resume <name>
  train status
  train logs
  train jobs
  train schedule list
"""


TOPIC_ALIASES = {
    "recipe": "recipe",
    "recipes": "recipes",
    "syntax": "recipe",
    "python-recipes": "recipe",
    "run": "run",
    "resume": "resume",
    "status": "status",
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
    "overview": "overview",
}


def _show_recipe() -> None:
    print(RECIPE_TEXT)


def _show_recipes() -> None:
    from .recipe import main as recipes_main

    recipes_main(["--help"])


def _show_run() -> None:
    from .recipe_runtime import cmd_run

    cmd_run(["--help"])


def _show_resume() -> None:
    from .recipe_runtime import cmd_resume

    cmd_resume(["--help"])


def _show_status() -> None:
    from .recipe_runtime import cmd_status

    cmd_status(["--help"])


def _show_logs() -> None:
    from .recipe_runtime import cmd_logs

    cmd_logs(["--help"])


def _show_jobs() -> None:
    from .recipe_runtime import cmd_jobs

    cmd_jobs(["--help"])


def _show_schedule() -> None:
    from .schedule_cmd import main as schedule_main

    schedule_main(["--help"])


def _show_host() -> None:
    from .host import main as host_main

    host_main(["--help"])


def _show_storage() -> None:
    from .storage import main as storage_main

    storage_main(["--help"])


def _show_transfer() -> None:
    from .transfer import main as transfer_main

    transfer_main(["--help"])


def _show_secrets() -> None:
    from .secrets_cmd import main as secrets_main

    secrets_main(["--help"])


def _show_config() -> None:
    from .config_cmd import main as config_main

    config_main(["--help"])


def _show_vast() -> None:
    from .vast import main as vast_main

    vast_main(["--help"])


def _show_colab() -> None:
    from .colab import main as colab_main

    colab_main(["--help"])


def _show_pricing() -> None:
    from .pricing import main as pricing_main

    pricing_main(["--help"])


def _show_update() -> None:
    from .update import main as update_main

    update_main(["--help"])


TOPIC_HANDLERS: Dict[str, Callable[[], None]] = {
    "overview": lambda: print(INDEX_TEXT),
    "recipe": _show_recipe,
    "recipes": _show_recipes,
    "run": _show_run,
    "resume": _show_resume,
    "status": _show_status,
    "logs": _show_logs,
    "jobs": _show_jobs,
    "schedule": _show_schedule,
    "transfer": _show_transfer,
    "host": _show_host,
    "storage": _show_storage,
    "secrets": _show_secrets,
    "config": _show_config,
    "vast": _show_vast,
    "colab": _show_colab,
    "pricing": _show_pricing,
    "update": _show_update,
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
