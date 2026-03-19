#!/usr/bin/env python3
"""Sync generated repository docs from the canonical CLI help source."""

from __future__ import annotations

import argparse
from pathlib import Path

from trainsh.commands.help_catalog import render_readme_overview


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync README.md from the canonical CLI help source.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if README.md is out of date.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    readme_path = root / "README.md"
    expected = render_readme_overview()
    current = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    if current == expected:
        print("README.md is up to date.")
        return 0

    if args.check:
        print("README.md is out of date.")
        return 1

    readme_path.write_text(expected, encoding="utf-8")
    print("Updated README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
