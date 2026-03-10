#!/usr/bin/env python3
"""Convert legacy `.recipe` files to the current Python recipe DSL."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trainsh.legacy_recipe_converter import main


if __name__ == "__main__":
    raise SystemExit(main())
