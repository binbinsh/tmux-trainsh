"""Persistent state for managed FlashAttention installs."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..constants import STATE_DIR


def _now_iso() -> str:
    return datetime.now().isoformat()


def sanitize_flash_attn_name(value: str) -> str:
    """Normalize arbitrary FlashAttention install names into CLI-safe identifiers."""
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip().lower())
    text = text.strip("-.")
    return text or "flash-attn"


def _installs_dir() -> Path:
    root = STATE_DIR / "flash_attn" / "installs"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class FlashAttnInstallRecord:
    """Persisted metadata for one managed FlashAttention install attempt."""

    name: str
    host_name: str
    host: dict[str, Any]
    python_executable: str = ""
    package_name: str = ""
    install_spec: str = ""
    session_name: str = ""
    log_path: str = ""
    status: str = "planned"
    strategy: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        self.name = sanitize_flash_attn_name(self.name)
        self.host_name = str(self.host_name or "").strip()
        self.python_executable = str(self.python_executable or "").strip()
        self.package_name = str(self.package_name or "").strip()
        self.install_spec = str(self.install_spec or "").strip()
        self.session_name = str(self.session_name or "").strip()
        self.log_path = str(self.log_path or "").strip()
        self.status = str(self.status or "planned").strip() or "planned"
        self.strategy = str(self.strategy or "").strip()
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FlashAttnInstallRecord":
        return cls(**dict(data or {}))


def install_record_path(name: str) -> Path:
    """Resolve the on-disk path for one FlashAttention install record."""
    return _installs_dir() / f"{sanitize_flash_attn_name(name)}.json"


def save_install_record(record: FlashAttnInstallRecord) -> None:
    """Persist one FlashAttention install record."""
    record.updated_at = _now_iso()
    target = install_record_path(record.name)
    target.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_install_record(name: str) -> Optional[FlashAttnInstallRecord]:
    """Load one persisted FlashAttention install record by name."""
    target = install_record_path(name)
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return FlashAttnInstallRecord.from_dict(payload)


__all__ = [
    "FlashAttnInstallRecord",
    "install_record_path",
    "load_install_record",
    "sanitize_flash_attn_name",
    "save_install_record",
]
