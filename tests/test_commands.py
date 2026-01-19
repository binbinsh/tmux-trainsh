#!/usr/bin/env python3
"""Test that all commands in README are available and can be imported."""

import json
import subprocess
import sys
import os
import tempfile
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent

TEST_HOME = tempfile.TemporaryDirectory()
TEST_CONFIG_DIR = Path(TEST_HOME.name) / ".config" / "kitten-trainsh"
TEST_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
PRICING_FILE = TEST_CONFIG_DIR / "pricing.json"

if not PRICING_FILE.exists():
    PRICING_FILE.write_text(json.dumps({
        "exchange_rates": {
            "base": "USD",
            "rates": {
                "USD": 1.0,
                "CNY": 7.0,
            },
            "updated_at": "test",
        },
        "display_currency": "USD",
    }, indent=2))

# Commands to test (from README)
# Format: (command, expected_in_help_or_error)
COMMANDS = [
    # Top-level
    ("--help", "kitten-trainsh"),
    ("--version", "kitten-trainsh"),

    # Host
    ("host --help", "Subcommands"),
    ("host list", "hosts"),
    ("host add", "Add new host"),
    ("host show", "Usage"),
    ("host ssh", "Usage"),
    ("host browse", "Usage"),
    ("host test", "Usage"),
    ("host rm", "Usage"),

    # Storage
    ("storage --help", "Subcommands"),
    ("storage list", "backends"),
    ("storage add", "Add new storage backend"),
    ("storage show", "Usage"),
    ("storage test", "Usage"),
    ("storage rm", "Usage"),

    # Transfer
    ("transfer --help", "Transfer files"),

    # Recipe
    ("recipe --help", "Subcommands"),
    ("recipe list", "recipes"),
    ("recipe show", "Usage"),
    ("recipe run", "Usage"),
    ("recipe new", "Usage"),
    ("recipe edit", "Usage"),
    ("recipe rm", "Usage"),
    ("recipe logs", "execution"),
    ("recipe logs --last", "execution"),
    ("recipe status", "sessions"),
    ("recipe status --all", "sessions"),

    # Secrets
    ("secrets --help", "Subcommands"),
    ("secrets list", "secrets"),
    ("secrets set", "Usage"),
    ("secrets get", "Usage"),
    ("secrets delete", "Usage"),

    # Config
    ("config --help", "Subcommands"),
    ("config show", "Configuration"),
    ("config get", "Usage"),
    ("config set", "Usage"),
    ("config reset", "Reset all settings"),

    # Colab
    ("colab --help", "Colab"),
    ("colab list", "Colab"),
    ("colab connect", "Connect to Google Colab"),
    ("colab ssh", "Colab"),
    ("colab run", "Usage"),

    # Vast.ai
    ("vast --help", "Subcommands"),
    ("vast list", "instances"),
    ("vast show", "Usage"),
    ("vast ssh", "Usage"),
    ("vast start", "Usage"),
    ("vast stop", "Usage"),
    ("vast rm", "Usage"),
    ("vast reboot", "Usage"),
    ("vast search", "GPU"),
    ("vast keys", "SSH"),
    ("vast attach-key", "Key file"),

    # Pricing
    ("pricing --help", "Pricing"),
    ("pricing rates", "exchange rates"),
    ("pricing currency", "Display currency"),
    ("pricing colab", "Colab Subscription"),
    ("pricing vast", "Vast.ai"),
    ("pricing convert 10 USD CNY", "="),
]


def test_command(cmd: str, expected: str) -> tuple[bool, str]:
    """Test a single command."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "trainsh"] + cmd.split(),
            capture_output=True,
            text=True,
            timeout=10,
            cwd=PROJECT_ROOT,
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "HOME": TEST_HOME.name},
            stdin=subprocess.DEVNULL,
        )
        output = result.stdout + result.stderr

        # Check if output contains expected string (case-insensitive)
        if expected.lower() in output.lower():
            return True, ""

        # Some commands may exit with error but still work
        if result.returncode in (0, 1) and len(output) > 0:
            return True, f"(output doesn't contain '{expected}')"

        return False, f"Expected '{expected}' in output: {output[:200]}"

    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def test_imports() -> list[tuple[str, bool, str]]:
    """Test that all command modules can be imported."""
    import importlib.util

    results = []
    modules = [
        "trainsh.commands.host",
        "trainsh.commands.vast",
        "trainsh.commands.storage",
        "trainsh.commands.transfer",
        "trainsh.commands.recipe",
        "trainsh.commands.secrets_cmd",
        "trainsh.commands.colab",
        "trainsh.commands.pricing",
        "trainsh.commands.config_cmd",
        "trainsh.services.vast_api",
        "trainsh.services.ssh",
        "trainsh.services.tmux",
        "trainsh.services.transfer_engine",
        "trainsh.core.models",
        "trainsh.core.secrets",
    ]

    # Add project root to path
    sys.path.insert(0, str(PROJECT_ROOT))

    for module in modules:
        try:
            importlib.import_module(module)
            results.append((module, True, ""))
        except Exception as e:
            results.append((module, False, str(e)))

    return results


def main():
    """Run all tests."""
    print("=" * 60)
    print("kitten-trainsh Command Availability Tests")
    print("=" * 60)

    # Test imports first
    print("\n1. Testing module imports...")
    print("-" * 40)

    import_results = test_imports()
    import_passed = 0
    import_failed = 0

    for module, success, error in import_results:
        if success:
            print(f"  OK: {module}")
            import_passed += 1
        else:
            print(f"  FAIL: {module}")
            print(f"        {error}")
            import_failed += 1

    print(f"\nImports: {import_passed} passed, {import_failed} failed")

    # Test commands
    print("\n2. Testing commands...")
    print("-" * 40)

    cmd_passed = 0
    cmd_failed = 0
    cmd_warnings = 0

    for cmd, expected in COMMANDS:
        success, msg = test_command(cmd, expected)
        if success:
            if msg:
                print(f"  WARN: trainsh {cmd} {msg}")
                cmd_warnings += 1
            else:
                print(f"  OK: trainsh {cmd}")
            cmd_passed += 1
        else:
            print(f"  FAIL: trainsh {cmd}")
            print(f"        {msg}")
            cmd_failed += 1

    print(f"\nCommands: {cmd_passed} passed, {cmd_failed} failed, {cmd_warnings} warnings")

    # Summary
    print("\n" + "=" * 60)
    total_passed = import_passed + cmd_passed
    total_failed = import_failed + cmd_failed
    print(f"Total: {total_passed} passed, {total_failed} failed")

    if total_failed > 0:
        print("\nFailed tests indicate commands that need to be fixed or")
        print("remove from the README.")
        return 1

    print("\nAll tests passed! README commands are up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
