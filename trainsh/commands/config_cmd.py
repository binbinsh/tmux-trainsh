# kitten-trainsh config command
# Configuration management

import sys
from typing import Optional, List

usage = '''[subcommand] [args...]

Subcommands:
  tui              - Launch interactive configuration TUI
  show             - Show current configuration
  get <key>        - Get a config value (e.g., vast.default_disk_gb)
  set <key> <val>  - Set a config value
  reset            - Reset to default configuration

Examples:
  kitty +kitten trainsh config tui
  kitty +kitten trainsh config get ui.currency
  kitty +kitten trainsh config set ui.currency CNY
  kitty +kitten trainsh config set defaults.ssh_key_path ~/.ssh/id_ed25519
'''


def cmd_show(args: List[str]) -> None:
    """Show current configuration."""
    from ..config import load_config

    config = load_config()

    def print_dict(d: dict, indent: int = 0):
        prefix = "  " * indent
        for key, value in d.items():
            if isinstance(value, dict):
                print(f"{prefix}{key}:")
                print_dict(value, indent + 1)
            else:
                print(f"{prefix}{key} = {value}")

    print("Current configuration:")
    print("-" * 40)
    print_dict(config)


def cmd_get(args: List[str]) -> None:
    """Get a config value."""
    if not args:
        print("Usage: kitty +kitten trainsh config get <key>")
        print("Example: kitty +kitten trainsh config get ui.currency")
        sys.exit(1)

    from ..config import get_config_value

    key = args[0]
    value = get_config_value(key)

    if value is None:
        print(f"Key not found: {key}")
        sys.exit(1)

    print(value)


def cmd_set(args: List[str]) -> None:
    """Set a config value."""
    if len(args) < 2:
        print("Usage: kitty +kitten trainsh config set <key> <value>")
        print("Example: kitty +kitten trainsh config set ui.currency CNY")
        sys.exit(1)

    from ..config import set_config_value

    key = args[0]
    value = " ".join(args[1:])

    # Type conversion
    if value.lower() == "true":
        value = True
    elif value.lower() == "false":
        value = False
    elif value.isdigit():
        value = int(value)
    else:
        try:
            value = float(value)
        except ValueError:
            pass  # Keep as string

    set_config_value(key, value)
    print(f"Set {key} = {value}")


def cmd_tui(args: List[str]) -> None:
    """Launch interactive configuration TUI."""
    from ..ui.handler import run_tui
    run_tui(args)


def cmd_reset(args: List[str]) -> None:
    """Reset to default configuration."""
    confirm = input("Reset all settings to defaults? (y/N): ")
    if confirm.lower() != "y":
        print("Cancelled.")
        return

    from ..config import save_config, get_default_config

    save_config(get_default_config())
    print("Configuration reset to defaults.")


def main(args: List[str]) -> Optional[str]:
    """Main entry point for config command."""
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    subcommand = args[0]
    subargs = args[1:]

    commands = {
        "show": cmd_show,
        "get": cmd_get,
        "set": cmd_set,
        "tui": cmd_tui,
        "reset": cmd_reset,
    }

    if subcommand not in commands:
        print(f"Unknown subcommand: {subcommand}")
        print(usage)
        sys.exit(1)

    commands[subcommand](subargs)
    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Configuration management"
    cd["short_desc"] = "Manage trainsh configuration"
