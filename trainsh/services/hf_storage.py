"""Helpers for Hugging Face bucket-backed storage."""

from __future__ import annotations

import os
import subprocess
from typing import Dict

from ..constants import SecretKeys
from ..core.models import Storage, StorageType
from ..core.secrets import get_secrets_manager
from .secret_materialize import resolve_resource_secret_name


def resolve_hf_bucket_id(storage: Storage) -> str:
    """Return the configured Hugging Face bucket id."""
    if storage.type != StorageType.HF:
        return ""
    return str(storage.config.get("bucket", "")).strip().strip("/")


def resolve_hf_bucket_uri(storage: Storage, path: str = "") -> str:
    """Resolve a bucket-relative path to an hf:// URI."""
    bucket_id = resolve_hf_bucket_id(storage)
    relative = str(path or "").strip().lstrip("/")

    if bucket_id:
        rooted = bucket_id
        if relative:
            if relative != bucket_id and not relative.startswith(f"{bucket_id}/"):
                rooted = f"{bucket_id}/{relative}"
            else:
                rooted = relative
    else:
        rooted = relative

    rooted = rooted.strip("/")
    return f"hf://buckets/{rooted}" if rooted else "hf://buckets"


def resolve_hf_token(storage: Storage) -> str:
    """Resolve the HF token for a storage, preferring scoped secrets."""
    secrets = get_secrets_manager()
    token_secret = resolve_resource_secret_name(storage.name, storage.config.get("token_secret"), "HF_TOKEN")

    for key in (token_secret, SecretKeys.HF_TOKEN):
        value = secrets.get(key)
        if value:
            return str(value).strip()

    return str(storage.config.get("token", "")).strip()


def build_hf_env(storage: Storage) -> Dict[str, str]:
    """Build environment variables for the hf CLI."""
    token = resolve_hf_token(storage)
    return {"HF_TOKEN": token} if token else {}


def check_hf_available() -> bool:
    """Check if the hf CLI is installed."""
    try:
        subprocess.run(["hf", "version"], capture_output=True)
        return True
    except FileNotFoundError:
        return False


def is_hf_bucket_uri(value: str) -> bool:
    """Return whether a path is an hf:// bucket URI."""
    return str(value or "").strip().startswith("hf://buckets/")


def local_path_for_cli(path: str) -> str:
    """Expand a local filesystem path for CLI use."""
    return os.path.expanduser(str(path or "").strip())
