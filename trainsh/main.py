#!/usr/bin/env python
# train - GPU training workflow automation
# License: MIT

import sys
from typing import Optional

BANNER = r'''
   ████████╗██████╗  █████╗ ██╗███╗   ██╗███████╗██╗  ██╗
   ╚══██╔══╝██╔══██╗██╔══██╗██║████╗  ██║██╔════╝██║  ██║
      ██║   ██████╔╝███████║██║██╔██╗ ██║███████╗███████║
      ██║   ██╔══██╗██╔══██║██║██║╚██╗██║╚════██║██╔══██║
      ██║   ██║  ██║██║  ██║██║██║ ╚████║███████║██║  ██║
      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝

   ════════════════════════════════════════════════════════
     🖥️  TMUX   ══▶   ☁️  GPU   ══▶   💾  STORAGE
   ════════════════════════════════════════════════════════
'''

usage = '''[command] [args...]

Commands:
  help      - Browse help topics
  run       - Run a recipe
  resume    - Resume the latest failed/interrupted recipe run
  status    - Show current or recent recipe sessions
  logs      - Show execution logs
  jobs      - Show recent job state history
  schedule  - Scheduler operations for timed recipes
  recipes   - Recipe file management
  transfer  - File transfer between hosts/storage
  host      - Host management (SSH, Colab, Vast.ai)
  storage   - Storage backend management (R2, B2, etc.)
  secrets   - Manage API keys and credentials
  config    - Configuration and settings
  vast      - Vast.ai instance management
  colab     - Google Colab integration
  pricing   - Currency exchange rates and cost calculator
  update    - Check for updates
'''

help_text = '''
tmux-trainsh: GPU training workflow automation in the terminal.

Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage backends
(Cloudflare R2, Backblaze B2, Google Drive), and automate training workflows.

QUICK START
  train help                          # Browse help topics
  train help recipe                   # Python recipe syntax and examples
  train secrets set VAST_API_KEY      # Set up API keys
  train host add                      # Add SSH/Colab host
  train storage add                   # Add storage backend
  train recipes list                  # Inspect available recipes
  train run <recipe>                  # Run a recipe
  train schedule list                 # Inspect scheduled recipes

HELP HUB
  help                    Browse all help topics
  help recipe             Python recipe syntax, examples, and lifecycle
  help run                Run command options
  help schedule           Scheduler usage
  help host               Host management

WORKFLOWS
  run <name>              Run a recipe
  resume <name>           Resume the latest failed/interrupted recipe run
  status [id]             Show current or recent recipe sessions
  logs [job-id]           Show execution logs
  jobs                    Show recent job state history
  schedule list|run|...   Scheduler operations for timed recipes
  transfer <src> <dst>    File transfer between hosts/storage

RECIPE FILES
  recipes list|show|new|... Manage Python recipe files

INFRASTRUCTURE
  host list|add|ssh|...   Host management (SSH, Colab, Vast.ai)
  storage list|add|...    Storage backend management (R2, B2)
  secrets list|set|get    Manage API keys and credentials
  config show|set|...     Configuration and settings

CLOUD
  vast list|ssh|start|... Vast.ai instance management
  colab list|connect|ssh  Google Colab integration

UTILITY
  pricing rates|convert   Currency exchange and cost calculator
  update                  Check for updates
  version                 Show version

RESUME
  train resume <name>                 Resume from the latest saved checkpoint
  Resume keeps saved hosts/tmux state; only --var overrides are supported

CONFIG FILES
  ~/.config/tmux-trainsh/
  ├── config.yaml         Main settings
  ├── hosts.yaml          SSH hosts
  ├── storages.yaml       Storage backends
  └── recipes/            Recipe files (.py)

Use "train help <topic>" for centralized help, or "train <command> --help" for command-local help.
Full documentation: https://github.com/binbinsh/tmux-trainsh
'''


def option_text() -> str:
    return '''\
--config
default=~/.config/tmux-trainsh/config.toml
Path to configuration file.

--verbose -v
type=bool-set
Enable verbose output.
'''


def main(args: list[str]) -> Optional[str]:
    """Main entry point for train."""
    from .constants import CONFIG_DIR, RECIPES_DIR

    # Ensure config directories exist
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)

    # No subcommand - show usage
    if len(args) < 2:
        print(BANNER)
        print(usage)
        raise SystemExit(0)

    command = args[1]
    cmd_args = args[2:]

    if command in {"-h", "--help"}:
        from .commands.help_cmd import main as help_main
        print(BANNER)
        help_main([])
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

    from .commands.recipe import main as recipes_main
    from .commands.recipe_runtime import (
        cmd_jobs,
        cmd_logs,
        cmd_resume,
        cmd_run,
        cmd_status,
    )
    from .commands.schedule_cmd import main as schedule_main
    from .commands.vast import main as vast_main
    from .commands.transfer import main as transfer_main
    from .commands.host import main as host_main
    from .commands.storage import main as storage_main
    from .commands.secrets_cmd import main as secrets_main
    from .commands.colab import main as colab_main
    from .commands.pricing import main as pricing_main
    from .commands.update import main as update_main
    from .commands.config_cmd import main as config_main

    handlers = {
        "run": cmd_run,
        "resume": cmd_resume,
        "status": cmd_status,
        "logs": cmd_logs,
        "jobs": cmd_jobs,
        "schedule": schedule_main,
        "recipes": recipes_main,
        "transfer": transfer_main,
        "host": host_main,
        "storage": storage_main,
        "secrets": secrets_main,
        "config": config_main,
        "vast": vast_main,
        "colab": colab_main,
        "pricing": pricing_main,
        "update": update_main,
    }

    handler = handlers.get(command)
    if command == "recipe":
        print("Unknown command: recipe")
        print("Use 'train recipes' for file management.")
        print("Use top-level 'train run|resume|status|logs|jobs|schedule' for execution.")
        raise SystemExit(1)

    if handler is None:
        print(f"Unknown command: {command}")
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
