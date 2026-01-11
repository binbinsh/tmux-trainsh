#!/usr/bin/env python3
"""Allow running trainsh as a module: python -m trainsh"""

import sys
from .main import main

if __name__ == "__main__":
    main(sys.argv)
