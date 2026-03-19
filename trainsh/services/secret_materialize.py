"""Helpers for resource-scoped secret naming and secret-backed files."""

from __future__ import annotations

import atexit
import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from ..core.secrets import get_secrets_manager


_SECRET_FILE_CACHE: dict[tuple[str, str], str] = {}
_SECRET_FILE_PATHS: set[str] = set()


def _cleanup_secret_files() -> None:
    for path in list(_SECRET_FILE_PATHS):
        try:
            os.remove(path)
        except OSError:
            pass
        _SECRET_FILE_PATHS.discard(path)


atexit.register(_cleanup_secret_files)


def suggest_secret_name(resource_name: str, suffix: str) -> str:
    """Build a stable resource-scoped secret name."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", str(resource_name or "").strip().upper()).strip("_")
    if not base:
        base = "RESOURCE"
    tail = re.sub(r"[^A-Za-z0-9]+", "_", str(suffix or "").strip().upper()).strip("_")
    return f"{base}_{tail}" if tail else base


def resolve_resource_secret_name(
    resource_name: str,
    explicit_name: Optional[str],
    suffix: str,
) -> str:
    """Resolve an explicit secret name or fall back to the default resource-scoped name."""
    explicit = str(explicit_name or "").strip()
    if explicit:
        return explicit
    return suggest_secret_name(resource_name, suffix)


def is_default_resource_secret_name(
    resource_name: str,
    secret_name: Optional[str],
    suffix: str,
) -> bool:
    """Return whether a secret name matches the default generated name."""
    actual = str(secret_name or "").strip()
    if not actual:
        return True
    return actual == suggest_secret_name(resource_name, suffix)


def store_secret_file(secret_name: str, source_path: str) -> None:
    """Read a local text file and store its contents in the secrets backend."""
    path = Path(os.path.expanduser(source_path)).resolve()
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    if not path.is_file():
        raise OSError(f"not a file: {path}")

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"file is empty: {path}")

    secrets = get_secrets_manager()
    secrets.set(secret_name, content)


def materialize_secret_file(secret_name: str, *, suffix: str = "") -> Optional[str]:
    """Resolve a secret into a local file path.

    If the secret already contains a valid local path, reuse it directly.
    Otherwise the secret value is written to a secure temp file for the current
    process lifetime.
    """

    resolved_name = str(secret_name or "").strip()
    if not resolved_name:
        return None

    secrets = get_secrets_manager()
    value = secrets.get(resolved_name)
    if not value:
        return None

    text = str(value)
    expanded = os.path.expanduser(text.strip())
    if "\n" not in text and expanded and os.path.exists(expanded):
        return expanded

    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    cache_key = (resolved_name, digest)
    cached = _SECRET_FILE_CACHE.get(cache_key)
    if cached and os.path.exists(cached):
        return cached

    fd, temp_path = tempfile.mkstemp(
        prefix="trainsh-secret-",
        suffix=suffix,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else f"{text}\n")
        os.chmod(temp_path, 0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise

    _SECRET_FILE_CACHE[cache_key] = temp_path
    _SECRET_FILE_PATHS.add(temp_path)
    return temp_path


__all__ = [
    "is_default_resource_secret_name",
    "materialize_secret_file",
    "resolve_resource_secret_name",
    "store_secret_file",
    "suggest_secret_name",
]
