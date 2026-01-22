#!/usr/bin/env python3
"""
tmux-trainsh entry point.

This file serves as the main entry point for:
1. train ... (CLI command)
2. python train.py ... (standalone mode)

Usage:
    train help
    train config show
    train host list
    train vast list
    train run <recipe>
"""

import sys
import os

# Add project directory to path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from trainsh.main import main as trainsh_main


def main(args: list[str]) -> str | None:
    """Entry point for train command."""
    try:
        return trainsh_main(list(args))
    except SystemExit:
        pass
    return None


if __name__ == "__main__":
    from trainsh import __version__

    # Standalone mode: args[0] is the script name
    result = main(["train"] + sys.argv[1:])
    if result:
        print(result)
    sys.exit(0)
