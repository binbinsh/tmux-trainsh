"""Compatibility helpers that now route to JSONL runtime state storage."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from ..constants import RUNTIME_STATE_DIR
from .runtime_store import RuntimeStore, get_runtime_state_dir, json_dumps, json_loads, to_jsonable


DEFAULT_XCOM_RETENTION_DAYS = 30
RUNTIME_DB = RUNTIME_STATE_DIR


def get_runtime_db_path(db_path: str | os.PathLike[str] | None = None) -> Path:
    return get_runtime_state_dir(db_path)


def connect_runtime_db(
    db_path: str | os.PathLike[str] | None = None,
    *,
    check_same_thread: bool = False,
) -> RuntimeStore:
    del check_same_thread
    return RuntimeStore(db_path)


def ensure_runtime_schema(conn: RuntimeStore) -> None:
    del conn


def ensure_xcom_schema(conn: RuntimeStore) -> None:
    del conn


def prune_old_xcom(
    conn: RuntimeStore,
    *,
    retention_days: int = DEFAULT_XCOM_RETENTION_DAYS,
    now=None,
) -> int:
    del conn, retention_days, now
    return 0


def _merge_run_snapshot(store: RuntimeStore, run_id: str, field: str, payload: Dict[str, Any]) -> None:
    existing = store.get_run(run_id) or {"run_id": run_id, "updated_at": ""}
    existing[field] = to_jsonable(payload)
    store.append_run(existing)


def replace_run_hosts(conn: RuntimeStore, run_id: str, hosts: Dict[str, Any]) -> None:
    _merge_run_snapshot(conn, run_id, "hosts", hosts)


def replace_run_storages(conn: RuntimeStore, run_id: str, storages: Dict[str, Any]) -> None:
    _merge_run_snapshot(conn, run_id, "storages", storages)


def replace_run_windows(conn: RuntimeStore, run_id: str, windows: Dict[str, Dict[str, Any]]) -> None:
    _merge_run_snapshot(conn, run_id, "windows", windows)


def load_run_hosts(conn: RuntimeStore, run_id: str) -> Dict[str, str]:
    record = conn.get_run(run_id) or {}
    return dict(record.get("hosts", {}) or {})


def load_run_storages(conn: RuntimeStore, run_id: str) -> Dict[str, Any]:
    record = conn.get_run(run_id) or {}
    return dict(record.get("storages", {}) or {})


def load_run_windows(conn: RuntimeStore, run_id: str) -> Dict[str, Dict[str, str]]:
    record = conn.get_run(run_id) or {}
    return dict(record.get("windows", {}) or {})


__all__ = [
    "DEFAULT_XCOM_RETENTION_DAYS",
    "RUNTIME_DB",
    "connect_runtime_db",
    "ensure_runtime_schema",
    "ensure_xcom_schema",
    "get_runtime_db_path",
    "json_dumps",
    "json_loads",
    "load_run_hosts",
    "load_run_storages",
    "load_run_windows",
    "prune_old_xcom",
    "replace_run_hosts",
    "replace_run_storages",
    "replace_run_windows",
    "to_jsonable",
]
