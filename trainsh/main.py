#!/usr/bin/env python
# train - GPU training workflow automation
# License: MIT

import sys
from typing import Optional

from .commands.help_catalog import render_top_level_help

usage = render_top_level_help()
help_text = usage


COMMAND_HINTS = {
    "recipes": "Use 'train recipe list|show|new|edit|remove' for recipe file management.",
    "resume": "Use 'train recipe resume <recipe>' to resume a recipe.",
    "status": "Use 'train recipe status' to inspect live/manual job state.",
    "logs": "Use 'train recipe logs' to inspect execution details.",
    "jobs": "Use 'train recipe jobs' for the recent-jobs table.",
    "schedule": "Use 'train recipe schedule <run|list|status>' for scheduled recipes.",
    "hosts": "Use 'train host' (singular) for named host definitions.",
    "storages": "Use 'train storage' (singular) for storage backends.",
    "log": "Use 'train recipe logs' for detailed execution logs.",
    "job": "Use 'train recipe jobs' for a compact recent-jobs table.",
}


def option_text() -> str:
    return '''\
--help -h
Show the canonical full CLI reference.

--version -V
Print the installed tmux-trainsh version.
'''


def main(args: list[str]) -> Optional[str]:
    """Main entry point for train."""
    from .constants import CONFIG_DIR

    # Ensure config directories exist
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # No subcommand - show the canonical reference.
    if len(args) < 2:
        print(usage)
        raise SystemExit(0)

    command = args[1]
    cmd_args = args[2:]

    if command in {"-h", "--help"}:
        print(help_text)
        raise SystemExit(0)
    if command in {"-V", "--version"}:
        from . import __display_version__
        print(f"tmux-trainsh {__display_version__}")
        raise SystemExit(0)

    # Route to subcommand
    if command == "help":
        from .commands.help_cmd import main as help_main
        return help_main(cmd_args)
    elif command == "version":
        from . import __display_version__
        print(f"tmux-trainsh {__display_version__}")
        raise SystemExit(0)

    from .commands.recipe_cmd import main as recipe_main
    from .commands.runpod import main as runpod_main
    from .commands.vast import main as vast_main
    from .commands.transfer import main as transfer_main
    from .commands.host import main as host_main
    from .commands.storage import main as storage_main
    from .commands.secrets_cmd import main as secrets_main
    from .commands.colab import main as colab_main
    from .commands.pricing import main as pricing_main
    from .commands.update import main as update_main
    from .commands.config_cmd import main as config_main
    from .commands.vllm import main as vllm_main
    handlers = {
        "recipe": recipe_main,
        "run": lambda args: recipe_main(["run", *args]),
        "exec": lambda args: recipe_main(["exec", *args]),
        "transfer": transfer_main,
        "host": host_main,
        "storage": storage_main,
        "secrets": secrets_main,
        "config": config_main,
        "vast": vast_main,
        "runpod": runpod_main,
        "colab": colab_main,
        "pricing": pricing_main,
        "vllm": vllm_main,
        "update": update_main,
    }

    handler = handlers.get(command)
    if handler is None:
        print(f"Unknown command: {command}")
        hint = COMMAND_HINTS.get(command)
        if hint:
            print(hint)
            print()
        print(usage)
        raise SystemExit(1)
    return handler(cmd_args)


def cli() -> None:
    """CLI entry point (called by uv/pip installed command)."""
    result = main(sys.argv)
    if result:
        print(result)


if __name__ == "__main__":
    cli()
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["options"] = option_text
    cd["help_text"] = help_text
    cd["short_desc"] = "GPU training workflow automation"
