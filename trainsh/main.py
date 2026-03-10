#!/usr/bin/env python
# train - GPU training workflow automation
# License: MIT

import sys
from typing import Optional, List, Dict

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
  storage   - Storage backend management (R2, B2, S3, etc.)
  secrets   - Manage API keys and credentials
  config    - Configuration and settings
  vast      - Vast.ai instance management
  colab     - Google Colab integration
  pricing   - Currency exchange rates and cost calculator
  update    - Check for updates
'''

COMMANDS_REGISTRY: List[Dict] = [
    {
        "command": "run",
        "description": "Run a recipe (alias for \"recipe run\")",
        "help_summary": "Run a recipe",
        "frequency": "frequent",
        "subcommands": [
            {"name": "<name>", "description": "Run a recipe"},
            {"name": "<name> --host gpu=vast:123", "description": "Override host"},
            {"name": "<name> --var MODEL=llama-7b", "description": "Override variable"},
            {"name": "<name> --pick-host gpu", "description": "Pick Vast.ai host"},
        ],
    },
    {
        "command": "exec",
        "description": "Execute DSL commands directly",
        "help_summary": "Execute DSL commands directly",
        "frequency": "frequent",
        "subcommands": [
            {"name": "'<dsl>'", "description": "Execute DSL commands directly"},
            {"name": "'@session > cmd'", "description": "Run in tmux session; falls back to host if no session exists"},
            {"name": "'@src:path -> @dst:path'", "description": "Transfer files"},
        ],
    },
    {
        "command": "host",
        "description": "Host management (SSH, Colab, Vast.ai)",
        "help_summary": "Host management (SSH, Colab, Vast.ai)",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List configured hosts", "frequency": "frequent"},
            {"name": "show <name>", "description": "Show host details", "frequency": "frequent"},
            {"name": "ssh <name>", "description": "SSH into host", "frequency": "frequent"},
            {"name": "add", "description": "Add new host (SSH/Colab)", "frequency": "occasional"},
            {"name": "edit <name>", "description": "Edit existing host config", "frequency": "occasional"},
            {"name": "browse <name>", "description": "Browse files on host", "frequency": "occasional"},
            {"name": "test <name>", "description": "Test connection", "frequency": "occasional"},
            {"name": "rm <name>", "description": "Remove a host", "frequency": "rare"},
        ],
    },
    {
        "command": "transfer",
        "description": "File transfer between hosts/storage",
        "help_summary": "File transfer between hosts/storage",
        "frequency": "frequent",
        "subcommands": [
            {"name": "<src> <dst>", "description": "Transfer files"},
            {"name": "<src> <dst> --delete", "description": "Sync with deletions"},
            {"name": "<src> <dst> --exclude '*.ckpt'", "description": "Exclude patterns"},
            {"name": "<src> <dst> --dry-run", "description": "Preview transfer"},
        ],
    },
    {
        "command": "recipe",
        "description": "Recipe management (list, show, edit, etc.)",
        "help_summary": "Recipe management",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List recipes", "frequency": "frequent"},
            {"name": "show <name>", "description": "Show recipe details", "frequency": "frequent"},
            {"name": "status", "description": "View running sessions", "frequency": "frequent"},
            {"name": "status --last", "description": "Show latest running job details and attach commands", "frequency": "frequent"},
            {"name": "status --all", "description": "Include completed sessions", "frequency": "frequent"},
            {"name": "syntax", "description": "Show full DSL syntax reference", "frequency": "occasional"},
            {"name": "new <name>", "description": "Create new recipe", "frequency": "occasional"},
            {"name": "edit <name>", "description": "Edit recipe in editor", "frequency": "occasional"},
            {"name": "run <name>", "description": "Run a recipe (same as `train run`)", "frequency": "occasional"},
            {"name": "resume <name>", "description": "Resume a failed/interrupted recipe (rebuilds tmux bridge splits)", "frequency": "occasional"},
            {"name": "resume <name> --check", "description": "Check remote status only", "frequency": "occasional"},
            {"name": "logs", "description": "View execution logs", "frequency": "occasional"},
            {"name": "logs --last", "description": "Show last execution", "frequency": "occasional"},
            {"name": "logs <job-id>", "description": "Show logs for a specific job", "frequency": "occasional"},
            {"name": "jobs", "description": "View job history", "frequency": "occasional"},
            {"name": "rm <name>", "description": "Remove a recipe", "frequency": "rare"},
        ],
    },
    {
        "command": "storage",
        "description": "Storage backend management (R2, B2, S3, etc.)",
        "help_summary": "Storage backend management (R2, B2, S3)",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List storage backends", "frequency": "occasional"},
            {"name": "show <name>", "description": "Show storage details", "frequency": "occasional"},
            {"name": "add", "description": "Add storage backend", "frequency": "occasional"},
            {"name": "test <name>", "description": "Test connection", "frequency": "occasional"},
            {"name": "rm <name>", "description": "Remove storage", "frequency": "rare"},
        ],
    },
    {
        "command": "secrets",
        "description": "Manage API keys and credentials",
        "help_summary": "Manage API keys and credentials",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List stored secrets", "frequency": "occasional"},
            {"name": "set <key>", "description": "Set a secret", "frequency": "occasional"},
            {"name": "get <key>", "description": "Get a secret", "frequency": "occasional"},
            {"name": "delete <key>", "description": "Delete a secret", "frequency": "rare"},
        ],
    },
    {
        "command": "config",
        "description": "Configuration and settings",
        "help_summary": "Configuration and settings",
        "frequency": "mixed",
        "subcommands": [
            {"name": "show", "description": "Show configuration", "frequency": "occasional"},
            {"name": "get <key>", "description": "Get config value", "frequency": "occasional"},
            {"name": "set <key> <val>", "description": "Set config value", "frequency": "occasional"},
            {"name": "tmux-setup", "description": "Apply tmux configuration to ~/.tmux.conf", "frequency": "occasional"},
            {"name": "tmux-edit", "description": "Edit tmux options in $EDITOR", "frequency": "occasional"},
            {"name": "tmux-list", "description": "List current tmux options", "frequency": "occasional"},
            {"name": "reset", "description": "Reset configuration", "frequency": "rare"},
        ],
    },
    {
        "command": "colab",
        "description": "Google Colab integration",
        "help_summary": "Google Colab integration",
        "frequency": "occasional",
        "subcommands": [
            {"name": "list", "description": "List Colab connections"},
            {"name": "connect", "description": "Add Colab connection"},
            {"name": "run <cmd>", "description": "Run command on Colab"},
            {"name": "ssh", "description": "SSH into Colab"},
        ],
    },
    {
        "command": "vast",
        "description": "Vast.ai instance management",
        "help_summary": "Vast.ai instance management",
        "frequency": "mixed",
        "subcommands": [
            {"name": "list", "description": "List your instances", "frequency": "occasional"},
            {"name": "show <id>", "description": "Show instance details", "frequency": "occasional"},
            {"name": "ssh <id>", "description": "SSH into instance", "frequency": "occasional"},
            {"name": "start <id>", "description": "Start instance", "frequency": "occasional"},
            {"name": "stop <id>", "description": "Stop instance", "frequency": "occasional"},
            {"name": "reboot <id>", "description": "Reboot instance", "frequency": "occasional"},
            {"name": "search", "description": "Search for GPU offers", "frequency": "occasional"},
            {"name": "keys", "description": "List SSH keys", "frequency": "occasional"},
            {"name": "attach-key [path]", "description": "Attach local SSH key", "frequency": "occasional"},
            {"name": "rm <id>", "description": "Remove instance", "frequency": "rare"},
        ],
    },
    {
        "command": "pricing",
        "description": "Currency exchange rates and cost calculator",
        "help_summary": "Currency exchange and cost calculator",
        "frequency": "rare",
        "subcommands": [
            {"name": "rates", "description": "Show exchange rates"},
            {"name": "rates --refresh", "description": "Refresh exchange rates"},
            {"name": "currency", "description": "Show display currency"},
            {"name": "currency --set CNY", "description": "Set display currency"},
            {"name": "colab", "description": "Show Colab pricing"},
            {"name": "vast", "description": "Show Vast.ai costs"},
            {"name": "convert 10 USD CNY", "description": "Convert currency"},
        ],
    },
    {
        "command": "update",
        "description": "Check for updates",
        "help_summary": "Check for updates",
        "frequency": "rare",
        "subcommands": [],
    },
    {
        "command": "help",
        "description": "Show help",
        "help_summary": "Show this help",
        "frequency": "rare",
        "subcommands": [],
    },
    {
        "command": "version",
        "description": "Show version",
        "help_summary": "Show version",
        "frequency": "rare",
        "subcommands": [],
    },
]


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
  storage list|add|...    Storage backend management (R2, B2, S3)
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
  ├── config.toml         Main settings
  ├── hosts.toml          SSH hosts
  ├── storages.toml       Storage backends
  └── recipes/            Recipe files (.py)

Use "train help <topic>" for centralized help, or "train <command> --help" for command-local help.
Full documentation: https://github.com/binbinsh/tmux-trainsh
'''


def option_text() -> str:
    return '''\
--config
default=~/.config/tmux-trainsh/config.yaml
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
