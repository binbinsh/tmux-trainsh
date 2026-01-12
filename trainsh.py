#!/usr/bin/env python3
"""
kitten-trainsh entry point for kitty.

This file serves as the entry point for both:
1. kitty +kitten trainsh ... (when installed to ~/.config/kitty/)
2. python trainsh.py ... (standalone mode)

Usage:
    kitty +kitten trainsh --help
    kitty +kitten trainsh config show
    kitty +kitten trainsh host list
"""

import sys
import os

# Add project directory to path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from trainsh.main import main as trainsh_main


def main(args: list[str]) -> str | None:
    """Entry point for kitty kitten command.

    kitty passes args as ['trainsh', 'config', 'show']
    where args[0] is the kitten name.
    """
    try:
        return trainsh_main(list(args))
    except SystemExit:
        pass
    return None


if __name__ == "__main__":
    # Standalone mode: args[0] is the script name, not kitten name
    sys.exit(main(["trainsh"] + sys.argv[1:]) or 0)
