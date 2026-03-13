"""Shared sqlite control-plane helpers for runtime state and logs."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from ..constants import CONFIG_DIR


RUNTIME_DB = CONFIG_DIR / "runtime.db"
DEFAULT_XCOM_RETENTION_DAYS = 30


def get_runtime_db_path(db_path: str | os.PathLike[str] | None = None) -> Path:
    path = Path(db_path) if db_path else RUNTIME_DB
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect_runtime_db(
    db_path: str | os.PathLike[str] | None = None,
    *,
    check_same_thread: bool = False,
) -> sqlite3.Connection:
    conn = sqlite3.connect(get_runtime_db_path(db_path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    ensure_runtime_schema(conn)
    return conn


def json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


def json_loads(text: Any, default: Any) -> Any:
    if text in (None, ""):
        return default
    try:
        return json.loads(str(text))
    except Exception:
        return default


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return str(value)


def ensure_runtime_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_runs (
            run_id TEXT PRIMARY KEY,
            recipe_name TEXT NOT NULL,
            recipe_path TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            duration_ms INTEGER,
            success INTEGER,
            metadata_json TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recipe_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_name TEXT NOT NULL,
            step_num INTEGER,
            payload_json TEXT,
            ts TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dag (
            dag_id TEXT PRIMARY KEY,
            file_path TEXT,
            is_paused INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            owner TEXT DEFAULT 'trainsh',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dag_run (
            dag_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            state TEXT NOT NULL,
            run_type TEXT DEFAULT 'manual',
            execution_date TEXT,
            start_date TEXT NOT NULL,
            end_date TEXT,
            external_trigger INTEGER DEFAULT 1,
            conf TEXT,
            PRIMARY KEY (dag_id, run_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_instance (
            dag_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            state TEXT NOT NULL,
            start_date TEXT,
            end_date TEXT,
            duration_ms INTEGER,
            operator TEXT,
            host TEXT,
            pool TEXT,
            trigger_rule TEXT,
            details_json TEXT,
            output TEXT,
            try_number INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (dag_id, task_id, run_id)
        )
        """
    )
    ensure_xcom_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slot_pool (
            pool TEXT PRIMARY KEY,
            slots INTEGER NOT NULL DEFAULT 1,
            occupied INTEGER NOT NULL DEFAULT 0,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS job_checkpoint (
            run_id TEXT PRIMARY KEY,
            recipe_path TEXT NOT NULL,
            recipe_name TEXT NOT NULL,
            current_step INTEGER NOT NULL DEFAULT 0,
            total_steps INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            variables_json TEXT NOT NULL DEFAULT '{}',
            next_window_index INTEGER NOT NULL DEFAULT 0,
            tmux_session TEXT NOT NULL DEFAULT '',
            bridge_session TEXT NOT NULL DEFAULT '',
            vast_instance_id TEXT,
            vast_start_time TEXT,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_host (
            run_id TEXT NOT NULL,
            host_name TEXT NOT NULL,
            host_spec TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, host_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_storage (
            run_id TEXT NOT NULL,
            storage_name TEXT NOT NULL,
            storage_spec_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, storage_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS run_window (
            run_id TEXT NOT NULL,
            window_name TEXT NOT NULL,
            host_spec TEXT NOT NULL,
            remote_session TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, window_name)
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_recipe_events_run_ts ON recipe_events (run_id, ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_recipe_runs_status ON recipe_runs (status, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dag_run_dag_start ON dag_run (dag_id, start_date DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dag_run_run_id ON dag_run (run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_instance_run_task ON task_instance (run_id, dag_id, task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_slot_pool_updated_at ON slot_pool (updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_checkpoint_recipe_updated ON job_checkpoint (recipe_path, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_window_run_id ON run_window (run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_host_run_id ON run_host (run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_storage_run_id ON run_storage (run_id)")
    conn.commit()


def ensure_xcom_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS xcom (
            dag_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            map_index INTEGER NOT NULL DEFAULT 0,
            key TEXT NOT NULL,
            value TEXT,
            created_at TEXT NOT NULL,
            execution_date TEXT,
            PRIMARY KEY (dag_id, task_id, run_id, map_index, key)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_xcom_run_task_key ON xcom (run_id, dag_id, task_id, key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_xcom_created_at ON xcom (created_at)")


def prune_old_xcom(
    conn: sqlite3.Connection,
    *,
    retention_days: int = DEFAULT_XCOM_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    retention_days = int(retention_days)
    if retention_days <= 0:
        return 0
    cutoff = (now or datetime.now()) - timedelta(days=retention_days)
    cutoff_text = cutoff.isoformat()
    cursor = conn.execute(
        """
        DELETE FROM xcom
        WHERE COALESCE(NULLIF(created_at, ''), execution_date, '') < ?
        """,
        (cutoff_text,),
    )
    return max(0, int(cursor.rowcount or 0))


def replace_run_hosts(conn: sqlite3.Connection, run_id: str, hosts: Dict[str, Any]) -> None:
    now = _now()
    conn.execute("DELETE FROM run_host WHERE run_id=?", (run_id,))
    rows = [
        (run_id, str(name), str(spec), now, now)
        for name, spec in dict(hosts or {}).items()
        if str(name).strip()
    ]
    if rows:
        conn.executemany(
            """
            INSERT INTO run_host (run_id, host_name, host_spec, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def replace_run_storages(conn: sqlite3.Connection, run_id: str, storages: Dict[str, Any]) -> None:
    now = _now()
    conn.execute("DELETE FROM run_storage WHERE run_id=?", (run_id,))
    rows = [
        (run_id, str(name), json_dumps(spec), now, now)
        for name, spec in dict(storages or {}).items()
        if str(name).strip()
    ]
    if rows:
        conn.executemany(
            """
            INSERT INTO run_storage (run_id, storage_name, storage_spec_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )


def replace_run_windows(conn: sqlite3.Connection, run_id: str, windows: Dict[str, Dict[str, Any]]) -> None:
    now = _now()
    conn.execute("DELETE FROM run_window WHERE run_id=?", (run_id,))
    rows = []
    for name, payload in dict(windows or {}).items():
        window_name = str(name).strip()
        if not window_name:
            continue
        info = dict(payload or {})
        rows.append(
            (
                run_id,
                window_name,
                str(info.get("host", "")),
                str(info.get("remote_session", "")),
                now,
                now,
            )
        )
    if rows:
        conn.executemany(
            """
            INSERT INTO run_window (run_id, window_name, host_spec, remote_session, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def load_run_hosts(conn: sqlite3.Connection, run_id: str) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT host_name, host_spec FROM run_host WHERE run_id=? ORDER BY host_name",
        (run_id,),
    ).fetchall()
    return {str(row["host_name"]): str(row["host_spec"]) for row in rows}


def load_run_storages(conn: sqlite3.Connection, run_id: str) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT storage_name, storage_spec_json FROM run_storage WHERE run_id=? ORDER BY storage_name",
        (run_id,),
    ).fetchall()
    return {
        str(row["storage_name"]): json_loads(row["storage_spec_json"], row["storage_spec_json"])
        for row in rows
    }


def load_run_windows(conn: sqlite3.Connection, run_id: str) -> Dict[str, Dict[str, str]]:
    rows = conn.execute(
        "SELECT window_name, host_spec, remote_session FROM run_window WHERE run_id=? ORDER BY window_name",
        (run_id,),
    ).fetchall()
    return {
        str(row["window_name"]): {
            "host": str(row["host_spec"]),
            "remote_session": str(row["remote_session"] or ""),
        }
        for row in rows
    }


def _now() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


__all__ = [
    "RUNTIME_DB",
    "connect_runtime_db",
    "DEFAULT_XCOM_RETENTION_DAYS",
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
