#!/usr/bin/env python
"""Regenerate the ## Recipe DSL and ## Commands sections in README.md.

Usage:
    python scripts/update_readme.py          # update README.md in-place
    python scripts/update_readme.py --check  # exit 1 if README is stale
"""

import sys
import os
import re

# Allow importing trainsh from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trainsh.core.dsl_parser import generate_syntax_reference
from trainsh.main import generate_commands_markdown


README_PATH = os.path.join(os.path.dirname(__file__), "..", "README.md")


def _replace_section(text: str, heading: str, new_body: str) -> str:
    """Replace everything from ``## <heading>`` up to the next ``## `` line."""
    pattern = re.compile(
        rf"(^## {re.escape(heading)}\s*\n)"  # match the heading line
        rf"(.*?)"                              # existing body (lazy)
        rf"(?=^## |\Z)",                       # stop at next ## or EOF
        re.MULTILINE | re.DOTALL,
    )
    replacement = f"## {heading}\n\n{new_body}\n"
    new_text, count = pattern.subn(replacement, text)
    if count == 0:
        print(f"WARNING: section '## {heading}' not found in README.md", file=sys.stderr)
    return new_text


def main() -> None:
    check_only = "--check" in sys.argv

    readme_path = os.path.abspath(README_PATH)
    with open(readme_path, "r") as f:
        original = f.read()

    dsl_body = generate_syntax_reference()
    commands_body = generate_commands_markdown()

    updated = _replace_section(original, "Recipe DSL", dsl_body)
    updated = _replace_section(updated, "Commands", commands_body)

    if check_only:
        if updated != original:
            print("README.md is out of date. Run: python scripts/update_readme.py")
            sys.exit(1)
        else:
            print("README.md is up to date.")
            sys.exit(0)

    if updated == original:
        print("README.md is already up to date.")
        return

    with open(readme_path, "w") as f:
        f.write(updated)
    print(f"Updated {readme_path}")


if __name__ == "__main__":
    main()
