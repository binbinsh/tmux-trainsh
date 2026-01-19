# tmux-trainsh update command
# Check for updates

import sys
from typing import Optional, List

usage = '''[--help]

Check for updates and print upgrade instructions.

Examples:
  train update
'''


def main(args: List[str]) -> Optional[str]:
    """Main entry point for update command."""
    if args and args[0] in ("-h", "--help", "help"):
        print(usage)
        return None

    if args:
        print(f"Unknown option: {' '.join(args)}")
        print(usage)
        sys.exit(1)

    from .. import __version__
    from ..utils.update_checker import get_latest_version, parse_version, print_update_notice

    latest = get_latest_version(force=True)
    if not latest:
        print("Unable to check for updates. Network or PyPI might be unavailable.")
        return None

    if parse_version(latest) > parse_version(__version__):
        print_update_notice(__version__, latest)
    else:
        print(f"tmux-trainsh is up to date ({__version__}).")

    return None


if __name__ == "__main__":
    main(sys.argv[1:])
elif __name__ == "__doc__":
    cd = sys.cli_docs  # type: ignore
    cd["usage"] = usage
    cd["help_text"] = "Update tmux-trainsh"
    cd["short_desc"] = "Check for updates"
