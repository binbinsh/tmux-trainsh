# tmux-trainsh update command
# Check for updates and perform automatic upgrade

import sys
from typing import Optional, List

usage = '''[--help] [--check]

Check for updates and automatically upgrade tmux-trainsh.

Options:
  --check    Only check for updates, don't install

Examples:
  train update          # Check and install update
  train update --check  # Only check, show update command
'''


def main(args: List[str]) -> Optional[str]:
    """Main entry point for update command."""
    if args and args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    check_only = False
    if args and args[0] in ("--check", "-c"):
        check_only = True
        args = args[1:]

    if args:
        print(f"Unknown option: {' '.join(args)}")
        print(usage)
        sys.exit(1)

    from .. import __version__
    from ..utils.update_checker import (
        get_latest_version,
        parse_version,
        print_update_notice,
        detect_install_method,
        get_update_command,
        perform_update,
    )

    latest = get_latest_version(force=True)
    if not latest:
        print("Unable to check for updates. Network or PyPI might be unavailable.")
        return None

    if parse_version(latest) <= parse_version(__version__):
        print(f"tmux-trainsh is up to date ({__version__}).")
        return None

    # Update available
    if check_only:
        print_update_notice(__version__, latest)
        return None

    # Perform automatic update
    method = detect_install_method()
    print(f"Updating {__version__} → {latest} (detected: {method})...")

    success, message = perform_update()
    if success:
        print(f"\033[32m✓\033[0m {message}")
    else:
        print(f"\033[31m✗\033[0m {message}")
        sys.exit(1)

    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Update tmux-trainsh"
    cd["short_desc"] = "Check for updates"
