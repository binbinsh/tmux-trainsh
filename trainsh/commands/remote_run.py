"""Shared helpers for one-off remote command execution."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
import sys
from typing import List, Tuple

from ..core.models import Host
from ..services.git_auth import (
    build_git_clone_command,
    build_remote_git_auth_command,
    is_plain_github_repo_url,
    normalize_git_auth_mode,
)
from ..services.secret_materialize import materialize_secret_file
from ..services.ssh import SSHClient


@dataclass(frozen=True)
class RemoteCloneRequest:
    repo_url: str
    destination: str = ""
    branch: str = ""
    depth: str = ""
    auth: str = "auto"
    token_secret: str = "GITHUB_TOKEN"


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


def parse_remote_clone_args(args: List[str], *, usage: str) -> Tuple[str, RemoteCloneRequest]:
    """Parse `<target> <repo-url> [destination] [options...]` clone arguments."""
    if len(args) < 2:
        print(f"Usage: {usage}")
        raise SystemExit(1)

    target = str(args[0]).strip()
    repo_url = str(args[1]).strip()
    if not target or not repo_url:
        print(f"Usage: {usage}")
        raise SystemExit(1)

    index = 2
    destination = ""
    if index < len(args) and not str(args[index]).startswith("--"):
        destination = str(args[index]).strip()
        index += 1

    branch = ""
    depth = ""
    auth = "auto"
    token_secret = "GITHUB_TOKEN"

    while index < len(args):
        option = str(args[index]).strip()
        index += 1
        if option == "--branch" and index < len(args):
            branch = str(args[index]).strip()
            index += 1
            continue
        if option == "--depth" and index < len(args):
            depth = str(args[index]).strip()
            index += 1
            continue
        if option == "--auth" and index < len(args):
            auth = str(args[index]).strip()
            index += 1
            continue
        if option == "--token-secret" and index < len(args):
            token_secret = str(args[index]).strip() or "GITHUB_TOKEN"
            index += 1
            continue
        print(f"Usage: {usage}")
        raise SystemExit(1)

    return target, RemoteCloneRequest(
        repo_url=repo_url,
        destination=destination,
        branch=branch,
        depth=depth,
        auth=auth,
        token_secret=token_secret,
    )


def _write_remote_result(result) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")


def run_remote_command(host: Host, command: str, *, label: str) -> None:
    """Execute one command on one resolved host and forward output locally."""
    print(f"Running on {label}...")

    try:
        ssh = SSHClient.from_host(host)
    except Exception as exc:
        print(f"Connection setup failed: {exc}")
        raise SystemExit(1)

    result = ssh.run(command)

    _write_remote_result(result)

    if result.exit_code != 0:
        raise SystemExit(result.exit_code if result.exit_code > 0 else 1)


def run_remote_git_clone(host: Host, request: RemoteCloneRequest, *, label: str) -> None:
    """Clone one repository on a remote host using optional GitHub token auth."""
    print(f"Cloning on {label}...")

    try:
        ssh = SSHClient.from_host(host)
    except Exception as exc:
        print(f"Connection setup failed: {exc}")
        raise SystemExit(1)

    try:
        auth_mode = normalize_git_auth_mode(request.auth)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)

    clone_command = build_git_clone_command(
        request.repo_url,
        request.destination,
        branch=request.branch,
        depth=request.depth,
    )

    if auth_mode == "github_token" and not is_plain_github_repo_url(request.repo_url):
        print("auth=github_token currently supports plain https://github.com/OWNER/REPO(.git) URLs only")
        raise SystemExit(1)

    token_text = ""
    if auth_mode != "plain" and is_plain_github_repo_url(request.repo_url):
        token_file = materialize_secret_file(request.token_secret, suffix=".token")
        if token_file:
            try:
                with open(token_file, "r", encoding="utf-8", errors="replace") as handle:
                    token_text = handle.read().strip()
            except OSError as exc:
                if auth_mode == "github_token":
                    print(f"Failed to read secret {request.token_secret}: {exc}")
                    raise SystemExit(1)
        elif auth_mode == "github_token":
            print(f"Secret not configured: {request.token_secret}")
            raise SystemExit(1)

    if auth_mode == "github_token" and not token_text:
        print(f"Secret {request.token_secret} is empty or unavailable")
        raise SystemExit(1)

    if token_text:
        result = ssh.run_with_input(
            build_remote_git_auth_command(clone_command),
            token_text if token_text.endswith("\n") else f"{token_text}\n",
        )
    else:
        result = ssh.run(clone_command)

    _write_remote_result(result)
    if result.exit_code != 0:
        raise SystemExit(result.exit_code if result.exit_code > 0 else 1)
