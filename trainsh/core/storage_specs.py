"""Shared helpers for resolving storage names and inline storage specs."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Optional

from .models import Storage, StorageType

_STORAGE_TYPE_ALIASES = {
    "local": StorageType.LOCAL,
    "file": StorageType.LOCAL,
    "ssh": StorageType.SSH,
    "sftp": StorageType.SSH,
    "gdrive": StorageType.GOOGLE_DRIVE,
    "drive": StorageType.GOOGLE_DRIVE,
    "hf": StorageType.HF,
    "r2": StorageType.R2,
    "b2": StorageType.B2,
    "gcs": StorageType.GCS,
    "smb": StorageType.SMB,
}

_BUCKET_STORAGE_TYPES = {
    StorageType.R2,
    StorageType.B2,
    StorageType.GCS,
    StorageType.HF,
}

_INLINE_TRANSFER_STORAGE_TYPES = {
    StorageType.R2,
    StorageType.B2,
    StorageType.GCS,
    StorageType.HF,
    StorageType.GOOGLE_DRIVE,
}


def normalize_storage_reference(value: Any) -> str:
    """Normalize storage references like '@artifacts' to 'artifacts'."""
    text = str(value).strip() if value is not None else ""
    if text.startswith("@"):
        text = text[1:].strip()
    return text


def storage_type_from_name(value: Any) -> Optional[StorageType]:
    """Resolve a storage provider name to StorageType."""
    text = str(value).strip().lower() if value is not None else ""
    if not text:
        return None
    return _STORAGE_TYPE_ALIASES.get(text)


def unsupported_inline_storage_error(value: Any) -> Optional[str]:
    """Return a user-facing error for intentionally unsupported inline specs."""
    text = normalize_storage_reference(value)
    if text.startswith("storage:"):
        text = text[8:].strip()
    if not text:
        return None

    provider, sep, _ = text.partition(":")
    if sep and provider.strip().lower() == "s3":
        return (
            "Inline Amazon S3 endpoints are not supported. "
            "Use `train storage add` and a named endpoint like `storage:<name>:/path`."
        )
    return None


def sanitize_rclone_remote_name(name: Any, *, uppercase: bool = False) -> str:
    """Convert arbitrary storage names into safe rclone remote identifiers."""
    text = str(name).strip() if name is not None else ""
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_") or "storage"
    if text[0].isdigit():
        text = f"s_{text}"
    return text.upper() if uppercase else text.lower()


def build_inline_storage_name(spec: Any) -> str:
    """Create a stable local name for an inline storage spec."""
    normalized = normalize_storage_reference(spec)
    provider, _, remainder = normalized.partition(":")
    slug = sanitize_rclone_remote_name(remainder or provider)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
    provider_name = sanitize_rclone_remote_name(provider or "storage")
    return f"{provider_name}_{slug[:24]}_{digest}"


def build_storage_from_spec(
    spec: Any,
    *,
    storage_name: Optional[str] = None,
) -> Optional[Storage]:
    """Build a Storage object from a direct provider spec like 'r2:bucket'."""
    if isinstance(spec, Storage):
        return spec

    if isinstance(spec, dict):
        try:
            return Storage.from_dict(spec)
        except Exception:
            return None

    text = normalize_storage_reference(spec)
    if not text or text == "placeholder":
        return None

    provider, sep, remainder = text.partition(":")
    storage_type = storage_type_from_name(provider)
    if storage_type is None:
        return None

    config = {}
    remainder = remainder.strip()
    if storage_type in _BUCKET_STORAGE_TYPES:
        if remainder:
            config["bucket"] = remainder.strip("/")
    elif storage_type == StorageType.GOOGLE_DRIVE:
        if remainder:
            config["remote_name"] = remainder
    elif storage_type == StorageType.HF:
        if remainder:
            config["bucket"] = remainder.strip("/")
    elif storage_type == StorageType.LOCAL:
        if remainder:
            config["path"] = remainder
    elif storage_type == StorageType.SSH:
        if remainder:
            config["host"] = remainder
    elif storage_type == StorageType.SMB:
        if remainder:
            config["host"] = remainder

    name = storage_name or build_inline_storage_name(text)
    return Storage(
        id=name,
        name=name,
        type=storage_type,
        config=config,
    )


def resolve_storage_reference(
    value: Any,
    *,
    named_storages: Optional[Mapping[str, Storage]] = None,
) -> Optional[Storage]:
    """Resolve a configured storage name or an inline storage spec."""
    if isinstance(value, Storage):
        return value

    if isinstance(value, dict):
        try:
            return Storage.from_dict(value)
        except Exception:
            return None

    text = normalize_storage_reference(value)
    if not text:
        return None
    if named_storages and text in named_storages:
        return named_storages[text]
    return build_storage_from_spec(text)


def parse_inline_storage_endpoint(spec: Any) -> Optional[tuple[str, str]]:
    """Parse inline transfer endpoints like 'r2:bucket:/path/to/file'."""
    text = normalize_storage_reference(spec)
    provider, sep, remainder = text.partition(":")
    storage_type = storage_type_from_name(provider)
    if storage_type not in _INLINE_TRANSFER_STORAGE_TYPES or not sep or ":" not in remainder:
        return None

    storage_target, path = remainder.split(":", 1)
    storage_target = storage_target.strip()
    if not storage_target:
        return None
    return f"{provider}:{storage_target}", path
