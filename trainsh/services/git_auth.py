"""Helpers for secure one-shot Git authentication."""

from __future__ import annotations

import atexit
import os
import shlex
import tempfile
from urllib.parse import urlparse


_TEMP_PATHS: set[str] = set()
_ASKPASS_PATH: str | None = None

_ASKPASS_BODY = """#!/bin/sh
prompt="$1"
case "$prompt" in
  *Username*|*username*)
    printf '%s\\n' 'x-access-token'
    ;;
  *)
    tr -d '\\r\\n' < "${TRAINSH_GIT_PASSWORD_FILE:?}"
    printf '\\n'
    ;;
esac
"""

_AUTH_ALIASES = {
    "": "auto",
    "auto": "auto",
    "default": "auto",
    "github_token": "github_token",
    "token": "github_token",
    "plain": "plain",
    "none": "plain",
}


def _cleanup_temp_paths() -> None:
    for path in list(_TEMP_PATHS):
        try:
            os.remove(path)
        except OSError:
            pass
        _TEMP_PATHS.discard(path)


atexit.register(_cleanup_temp_paths)


def is_plain_github_repo_url(repo_url: str) -> bool:
    """Return whether a repo URL targets github.com over HTTPS without embedded creds."""
    text = str(repo_url or "").strip()
    if not text:
        return False

    parsed = urlparse(text)
    if parsed.scheme.lower() != "https":
        return False
    if (parsed.hostname or "").lower() != "github.com":
        return False
    if parsed.username or parsed.password:
        return False

    path = str(parsed.path or "").strip("/")
    if not path:
        return False
    parts = [part for part in path.split("/") if part]
    return len(parts) >= 2


def build_git_clone_command(
    repo_url: str,
    destination: str = "",
    *,
    branch: str = "",
    depth: str = "",
) -> str:
    """Build a quoted `git clone` shell command."""
    command = "git clone"
    if branch:
        command += f" -b {shlex.quote(branch)}"
    if depth:
        command += f" --depth {shlex.quote(depth)}"
    command += f" {shlex.quote(repo_url)}"
    if destination:
        command += f" {shlex.quote(destination)}"
    return command


def normalize_git_auth_mode(value: str | None) -> str:
    """Normalize user-facing git auth mode values."""
    text = str(value or "").strip().lower()
    normalized = _AUTH_ALIASES.get(text)
    if normalized is None:
        raise ValueError(
            "Unsupported git auth mode. Use one of: auto, github_token, plain."
        )
    return normalized


def materialize_git_askpass_script() -> str:
    """Return a cached local askpass helper script path."""
    global _ASKPASS_PATH
    if _ASKPASS_PATH and os.path.exists(_ASKPASS_PATH):
        return _ASKPASS_PATH

    fd, path = tempfile.mkstemp(prefix="trainsh-git-askpass-", suffix=".sh")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(_ASKPASS_BODY)
        os.chmod(path, 0o700)
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise

    _ASKPASS_PATH = path
    _TEMP_PATHS.add(path)
    return path


def build_remote_git_auth_command(clone_command: str) -> str:
    """Build a remote shell command that reads a token from stdin for one clone."""
    script = "\n".join(
        (
            "set -eu",
            'tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/trainsh-git-XXXXXX")',
            'cleanup() { rm -rf "$tmpdir"; }',
            "trap cleanup EXIT HUP INT TERM",
            'token_file="$tmpdir/token"',
            'askpass_file="$tmpdir/askpass.sh"',
            'cat >"$token_file"',
            'chmod 600 "$token_file"',
            'cat >"$askpass_file" <<\'EOF_TRAINSH_GIT_ASKPASS\'',
            _ASKPASS_BODY.rstrip("\n"),
            "EOF_TRAINSH_GIT_ASKPASS",
            'chmod 700 "$askpass_file"',
            'export GIT_TERMINAL_PROMPT=0',
            'export GIT_ASKPASS="$askpass_file"',
            'export TRAINSH_GIT_PASSWORD_FILE="$token_file"',
            clone_command,
        )
    )
    return "sh -lc " + shlex.quote(script)


__all__ = [
    "build_git_clone_command",
    "build_remote_git_auth_command",
    "is_plain_github_repo_url",
    "materialize_git_askpass_script",
    "normalize_git_auth_mode",
]
