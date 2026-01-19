#!/usr/bin/env python
# train - GPU training workflow automation
# License: MIT

import sys
from typing import Optional

usage = '''[command] [args...]

Commands:
  exec      - Execute DSL commands directly
  host      - Host management (SSH, Colab, Vast.ai)
  transfer  - File transfer between hosts/storage
  recipe    - Execute automation recipes
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

Use "train <command> --help" for command-specific help.

Examples:
  train host add                # Add SSH/Colab host
  train vast list               # List Vast.ai instances
  train storage add             # Add storage backend (R2, B2, S3)
  train transfer src dst        # Transfer files
  train recipe run train        # Run a recipe
'''


def option_text() -> str:
    return '''\
--config
default=~/.config/tmux-trainsh/config.toml
Path to configuration file.

--verbose -v
type=bool-set
Enable verbose output.

--version
type=bool-set
Show version and exit.
'''


def main(args: list[str]) -> Optional[str]:
    """Main entry point for train."""
    from .constants import CONFIG_DIR, RECIPES_DIR

    # Ensure config directories exist
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RECIPES_DIR.mkdir(parents=True, exist_ok=True)

    # Check for --help at top level only (not for subcommands)
    if len(args) < 2 or (len(args) == 2 and args[1] in ("--help", "-h", "help")):
        if "--help" in args or "-h" in args or "help" in args:
            print(help_text)
            raise SystemExit(0)

    # Check for --version
    if "--version" in args or "-V" in args:
        from . import __version__
        print(f"tmux-trainsh {__version__}")
        raise SystemExit(0)

    # No subcommand - show usage
    if len(args) < 2:
        print(usage)
        raise SystemExit(0)

    command = args[1]
    cmd_args = args[2:]

    # Route to subcommand
    if command == "exec":
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
    elif command in ("--help", "-h", "help"):
        print(help_text)
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
