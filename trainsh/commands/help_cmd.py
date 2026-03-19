"""Canonical help command for trainsh CLI."""

from __future__ import annotations

import sys
from typing import List

from .help_catalog import render_top_level_help


INDEX_TEXT = render_top_level_help()


def main(args: List[str]) -> None:
    """Print the single canonical CLI reference."""
    if args and args[0] not in {"-h", "--help"}:
        print("train help takes no topic or subcommand.")
        print("Use `train help` or `train --help`.")
        raise SystemExit(1)
    print(INDEX_TEXT)


if __name__ == "__main__":
    main(sys.argv[1:])
