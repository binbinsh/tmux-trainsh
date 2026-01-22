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
  run       - Run a recipe (alias for "recipe run")
  exec      - Execute DSL commands directly
  host      - Host management (SSH, Colab, Vast.ai)
  transfer  - File transfer between hosts/storage
  recipe    - Recipe management (list, show, edit, etc.)
  storage   - Storage backend management (R2, B2, S3, etc.)
  secrets   - Manage API keys and credentials
  config    - Configuration and settings
  colab     - Google Colab integration
  pricing   - Currency exchange rates and cost calculator
  update    - Check for updates
'''

help_text = '''
tmux-trainsh: GPU training workflow automation in the terminal.

Manage remote GPU hosts (Vast.ai, Google Colab, SSH), cloud storage backends
(Cloudflare R2, Backblaze B2, S3, Google Drive), and automate training workflows.

QUICK START
  train secrets set VAST_API_KEY      # Set up API keys
  train host add                      # Add SSH/Colab host
  train storage add                   # Add storage backend
  train run <recipe>                  # Run a recipe

COMMANDS
  run <name>              Run a recipe
  exec '<dsl>'            Execute DSL commands directly
  host list|add|ssh|...   Host management (SSH, Colab, Vast.ai)
  storage list|add|...    Storage backend management (R2, B2, S3)
  transfer <src> <dst>    File transfer between hosts/storage
  recipe list|run|...     Recipe management
  vast list|ssh|start|... Vast.ai instance management
  colab list|connect|ssh  Google Colab integration
  secrets list|set|get    Manage API keys and credentials
  config show|set|...     Configuration and settings
  pricing rates|convert   Currency exchange and cost calculator
  help                    Show this help
  version                 Show version

RECIPE DSL (quick reference)
  var NAME = value                    Define a variable
  host gpu = placeholder              Define a host (filled by vast.pick)
  storage output = r2:bucket          Define storage backend

  vast.pick @gpu num_gpus=1           Pick Vast.ai instance
  vast.wait timeout=5m                Wait for instance ready
  tmux.open @gpu as work              Create tmux session

  @work > command                     Run command in session
  @work > command &                   Run in background
  wait @work idle timeout=2h          Wait for completion

  @gpu:/path -> @output:/path         Transfer files
  vast.stop                           Stop instance

CONFIG FILES
  ~/.config/tmux-trainsh/
  ├── config.toml         Main settings
  ├── hosts.toml          SSH hosts
  ├── storages.toml       Storage backends
  └── recipes/            Recipe files (.recipe)

Use "train <command> --help" for command-specific help.
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

    # Route to subcommand
    if command == "run":
        # Alias: "train run <name>" -> "train recipe run <name>"
        from .commands.recipe import cmd_run
        return cmd_run(cmd_args)
    elif command == "exec":
        from .commands.exec_cmd import main as exec_main
        return exec_main(cmd_args)
    elif command == "vast":
        from .commands.vast import main as vast_main
        return vast_main(cmd_args)
    elif command == "transfer":
        from .commands.transfer import main as transfer_main
        return transfer_main(cmd_args)
    elif command == "recipe":
        from .commands.recipe import main as recipe_main
        return recipe_main(cmd_args)
    elif command == "host":
        from .commands.host import main as host_main
        return host_main(cmd_args)
    elif command == "storage":
        from .commands.storage import main as storage_main
        return storage_main(cmd_args)
    elif command == "secrets":
        from .commands.secrets_cmd import main as secrets_main
        return secrets_main(cmd_args)
    elif command == "colab":
        from .commands.colab import main as colab_main
        return colab_main(cmd_args)
    elif command == "pricing":
        from .commands.pricing import main as pricing_main
        return pricing_main(cmd_args)
    elif command == "update":
        from .commands.update import main as update_main
        return update_main(cmd_args)
    elif command == "config":
        from .commands.config_cmd import main as config_main
        return config_main(cmd_args)
    elif command == "help":
        print(BANNER)
        print(help_text)
        raise SystemExit(0)
    elif command == "version":
        from . import __version__
        print(f"tmux-trainsh {__version__}")
        raise SystemExit(0)
    else:
        print(f"Unknown command: {command}")
        print(usage)
        raise SystemExit(1)


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
