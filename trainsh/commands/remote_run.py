"""Shared helpers for one-off remote command execution."""

from __future__ import annotations

import shlex
import sys
from typing import List, Tuple

from ..core.models import Host
from ..services.ssh import SSHClient


def parse_remote_run_args(args: List[str], *, usage: str) -> Tuple[str, str]:
    """Parse `<target> [--] <command...>` style args into target + shell command."""
    if len(args) < 2:
        print(f"Usage: {usage}")
        raise SystemExit(1)

    target = str(args[0]).strip()
    command_parts = list(args[1:])
    if command_parts[:1] == ["--"]:
        command_parts = command_parts[1:]

    if not target or not command_parts:
        print(f"Usage: {usage}")
        raise SystemExit(1)

    return target, shlex.join(command_parts)


def run_remote_command(host: Host, command: str, *, label: str) -> None:
    """Execute one command on one resolved host and forward output locally."""
    print(f"Running on {label}...")

    try:
        ssh = SSHClient.from_host(host)
    except Exception as exc:
        print(f"Connection setup failed: {exc}")
        raise SystemExit(1)

    result = ssh.run(command)

    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")

    if result.exit_code != 0:
        raise SystemExit(result.exit_code if result.exit_code > 0 else 1)
