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
    train recipe run <recipe>
"""

import sys
import os

# Add project directory to path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from trainsh.main import main as trainsh_main


def main(args: list[str]) -> int:
    """Entry point for train command."""
    try:
        result = trainsh_main(list(args))
        if result:
            print(result)
        return 0
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        return 1


if __name__ == "__main__":
    # Standalone mode: args[0] is the script name
    sys.exit(main(["train"] + sys.argv[1:]))
