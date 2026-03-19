#!/usr/bin/env python3
"""Test that core CLI commands are available and can be imported."""

import json
import re
import subprocess
import sys
import os
import atexit
import tempfile
from pathlib import Path

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent

TEST_HOME = tempfile.TemporaryDirectory()
atexit.register(TEST_HOME.cleanup)
TEST_CONFIG_DIR = Path(TEST_HOME.name) / ".config" / "tmux-trainsh"
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

# Commands to test
# Format: (command, expected_in_help_or_error)
COMMANDS = [
    # Top-level
    ("--help", "tmux-trainsh CLI"),
    ("--version", "tmux-trainsh"),
    ("help", "Recommended Topics"),
    ("help recipe", "train help takes no topic"),
    ("help run", "train help takes no topic"),
    ("help exec", "train help takes no topic"),
    ("help recipes", "train help takes no topic"),
    ("help schedule", "train help takes no topic"),
    ("gui --help", "Unknown command"),
    ("exec --help", "Use `train help` or `train --help`."),
    ("recipes --help", "Use 'train recipe"),
    ("run --help", "Use `train help` or `train --help`."),
    ("resume", "Use 'train recipe resume"),
    ("status", "Use 'train recipe status"),
    ("logs", "Use 'train recipe logs"),
    ("jobs", "Use 'train recipe jobs"),
    ("schedule --help", "Use 'train recipe schedule"),
    ("recipe --help", "Use `train help` or `train --help`."),
    ("recipe list", "Bundled examples"),
    ("recipe show", "Usage"),
    ("recipe show hello", "hello-world"),
    ("recipe new", "Usage"),
    ("recipe edit", "Usage"),
    ("recipe remove", "Usage"),
    ("recipe run --help", "Use `train help` or `train --help`."),
    ("recipe resume", "train recipe resume"),
    ("recipe status", "Recipe sessions"),
    ("recipe logs", "No execution logs found"),
    ("recipe jobs", "No job states found"),
    ("recipe schedule --help", "Use `train help` or `train --help`."),
    ("recipe schedule list", "No scheduled recipes found"),

    # Host
    ("host --help", "Use `train help` or `train --help`."),
    ("host list", "hosts"),
    ("host add", "Add new host"),
    ("host edit", "Usage"),
    ("host show", "Usage"),
    ("host ssh", "Usage"),
    ("host run", "Usage"),
    ("host files", "Usage"),
    ("host check", "Usage"),
    ("host remove", "Usage"),
    ("host connect", "Unknown subcommand"),
    ("host browse", "Unknown subcommand"),
    ("host test", "Unknown subcommand"),
    ("host rm", "Unknown subcommand"),

    # Storage
    ("storage --help", "Use `train help` or `train --help`."),
    ("storage list", "backends"),
    ("storage add", "Add new storage backend"),
    ("storage show", "Usage"),
    ("storage check", "Usage"),
    ("storage remove", "Usage"),
    ("storage test", "Unknown subcommand"),
    ("storage rm", "Unknown subcommand"),

    # Transfer
    ("transfer --help", "Use `train help` or `train --help`."),
    ("transfer ./data s3:bucket/path", "Inline Amazon S3 endpoints are not supported"),

    # Secrets
    ("secrets --help", "Use `train help` or `train --help`."),
    ("secrets list", "secrets"),
    ("secrets set", "Usage"),
    ("secrets get", "Usage"),
    ("secrets remove", "Usage"),
    ("secrets delete", "Unknown subcommand"),

    # Config
    ("config --help", "Use `train help` or `train --help`."),
    ("config show", "Configuration"),
    ("config get", "Usage"),
    ("config set", "Usage"),
    ("config reset", "Reset all settings"),
    ("config tmux --help", "Use `train help` or `train --help`."),
    ("config tmux show", "Tmux options"),
    ("config tmux list", "Unknown tmux subcommand"),
    ("config tmux setup", "Unknown tmux subcommand"),
    ("config tmux-edit", "Unknown subcommand"),

    # Colab
    ("colab --help", "Use `train help` or `train --help`."),
    ("colab list", "Colab"),
    ("colab connect", "Connect to Google Colab"),
    ("colab ssh", "Colab"),
    ("colab run", "Usage"),
    ("colab add", "Unknown subcommand"),
    ("colab exec", "Unknown subcommand"),

    # Vast.ai
    ("vast --help", "Use `train help` or `train --help`."),
    ("vast list", "instances"),
    ("vast show", "Usage"),
    ("vast ssh", "Usage"),
    ("vast run", "Usage"),
    ("vast start", "Usage"),
    ("vast stop", "Usage"),
    ("vast remove", "Usage"),
    ("vast reboot", "Usage"),
    ("vast search", "GPU"),
    ("vast keys", "SSH"),
    ("vast attach-key", "Key file"),
    ("vast connect", "Unknown subcommand"),
    ("vast rm", "Unknown subcommand"),
    ("vast offers", "Unknown subcommand"),

    # Pricing
    ("pricing --help", "Use `train help` or `train --help`."),
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

        return False, f"Expected '{expected}' in output: {output[:200]}"

    except subprocess.TimeoutExpired:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)


def test_train_py_wrapper() -> list[tuple[str, bool, str]]:
    """Smoke-test the standalone wrapper script."""
    checks = []
    cases = [
        (["--help"], 0, "tmux-trainsh CLI"),
        (["definitely-not-a-command"], 1, "Unknown command"),
    ]
    for args, expected_code, expected_text in cases:
        try:
            result = subprocess.run(
                [sys.executable, "train.py", *args],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=PROJECT_ROOT,
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT), "HOME": TEST_HOME.name},
                stdin=subprocess.DEVNULL,
            )
            output = result.stdout + result.stderr
            ok = result.returncode == expected_code and expected_text.lower() in output.lower()
            message = ""
            if result.returncode != expected_code:
                message = f"expected exit {expected_code}, got {result.returncode}"
            elif expected_text.lower() not in output.lower():
                message = f"missing {expected_text!r} in output: {output[:200]}"
            checks.append((f"train.py {' '.join(args)}", ok, message))
        except Exception as exc:
            checks.append((f"train.py {' '.join(args)}", False, str(exc)))
    return checks


def test_project_entrypoint() -> tuple[bool, str]:
    """Verify packaging metadata still exposes the expected train entry point."""
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if "[project.scripts]" not in pyproject:
        return False, "pyproject.toml is missing the [project.scripts] section"
    if not re.search(r'^train\s*=\s*"trainsh\.main:cli"$', pyproject, flags=re.MULTILINE):
        return False, "pyproject.toml is missing [project.scripts] train = \"trainsh.main:cli\""
    return True, ""


def test_imports() -> list[tuple[str, bool, str]]:
    """Test that all command modules can be imported."""
    import importlib.util

    results = []
    modules = [
        "trainsh.commands.host",
        "trainsh.commands.vast",
        "trainsh.commands.storage",
        "trainsh.commands.transfer",
        "trainsh.commands.help_cmd",
        "trainsh.commands.recipe",
        "trainsh.commands.recipe_cmd",
        "trainsh.commands.recipe_templates",
        "trainsh.commands.recipe_runtime",
        "trainsh.commands.runtime_dispatch",
        "trainsh.commands.secrets_cmd",
        "trainsh.commands.colab",
        "trainsh.commands.pricing",
        "trainsh.commands.config_cmd",
        "trainsh.commands.schedule_cmd",
        "trainsh.services.vast_api",
        "trainsh.services.ssh",
        "trainsh.services.transfer_engine",
        "trainsh.core.models",
        "trainsh.core.secrets",
        "trainsh.pyrecipe",
        "trainsh.runtime",
        "trainsh.runtime_executors",
        "trainsh.core.dag_processor",
        "trainsh.core.dag_executor",
        "trainsh.core.scheduler",
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
    print("tmux-trainsh Command Availability Tests")
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
    for cmd, expected in COMMANDS:
        success, msg = test_command(cmd, expected)
        if success:
            print(f"  OK: trainsh {cmd}")
            cmd_passed += 1
        else:
            print(f"  FAIL: trainsh {cmd}")
            print(f"        {msg}")
            cmd_failed += 1

    print(f"\nCommands: {cmd_passed} passed, {cmd_failed} failed")

    print("\n3. Testing wrapper and packaging metadata...")
    print("-" * 40)

    wrapper_passed = 0
    wrapper_failed = 0
    for label, success, error in test_train_py_wrapper():
        if success:
            print(f"  OK: {label}")
            wrapper_passed += 1
        else:
            print(f"  FAIL: {label}")
            print(f"        {error}")
            wrapper_failed += 1

    entrypoint_ok, entrypoint_error = test_project_entrypoint()
    if entrypoint_ok:
        print("  OK: pyproject entry point")
        wrapper_passed += 1
    else:
        print("  FAIL: pyproject entry point")
        print(f"        {entrypoint_error}")
        wrapper_failed += 1

    print(f"\nWrapper/metadata: {wrapper_passed} passed, {wrapper_failed} failed")

    # Summary
    print("\n" + "=" * 60)
    total_passed = import_passed + cmd_passed + wrapper_passed
    total_failed = import_failed + cmd_failed + wrapper_failed
    print(f"Total: {total_passed} passed, {total_failed} failed")

    if total_failed > 0:
        print("\nFailed tests indicate commands that need to be fixed or")
        print("remove from the README.")
        return 1

    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
