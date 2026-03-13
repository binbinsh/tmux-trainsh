#!/usr/bin/env python3
"""Check sqlite runtime control-plane coverage."""

from __future__ import annotations

import sys
import unittest

import coverage


MODULES = [
    "trainsh.core.runtime_db",
    "trainsh.core.job_state",
    "trainsh.core.execution_log",
]

TESTS = [
    "tests.test_runtime_persist",
    "tests.test_pyrecipe_runtime",
    "tests.test_runtime_semantics",
    "tests.test_provider_dispatch",
    "tests.test_ti_dependencies",
]

THRESHOLD = 95.0


def main() -> int:
    cov = coverage.Coverage(source=MODULES)
    cov.start()
    suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    cov.stop()
    cov.save()

    if not result.wasSuccessful():
        return 1

    total = cov.report(show_missing=True)
    if total < THRESHOLD:
        print(f"\nCoverage gate failed: {total:.1f}% < {THRESHOLD:.1f}%")
        return 1

    print(f"\nCoverage gate passed: {total:.1f}% >= {THRESHOLD:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
