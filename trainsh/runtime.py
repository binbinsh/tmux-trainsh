# Runtime helpers inspired by Airflow-style execution primitives.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Protocol
from datetime import datetime

import json
import sqlite3
import threading

from .constants import CONFIG_DIR
from .core.runtime_db import (
    connect_runtime_db,
    ensure_runtime_schema,
    json_dumps,
    replace_run_hosts,
    replace_run_storages,
)


class CallbackSink(Protocol):
    """Protocol for event callbacks."""

    def send(self, event: "CallbackEvent") -> None:
        """Handle a callback event."""
        ...


@dataclass
class CallbackEvent:
    """Normalized event emitted by execution pipeline."""

    event: str
    run_id: str
    recipe_name: str
    recipe_path: str
    step_num: Optional[int] = None
    try_number: int = 1
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now().isoformat())


class CallbackManager:
    """Fan-out callback sink manager."""

    def __init__(self, sinks: Optional[Sequence[CallbackSink]] = None):
        self.sinks: List[CallbackSink] = list(sinks or [])

    def add(self, sink: CallbackSink) -> None:
        """Register one sink."""
        self.sinks.append(sink)

    def emit(self, event: CallbackEvent) -> None:
        """Emit event to all sinks."""
        for sink in self.sinks:
            try:
                sink.send(event)
            except Exception as exc:
                # Keep execution resilient if custom sinks fail.
                print(f"[trainsh-runtime] callback sink failed: {exc}")

    def close(self) -> None:
        """Close any sinks that expose a close hook."""
        for sink in self.sinks:
            close = getattr(sink, "close", None)
            if callable(close):
                try:
                    close()
                except Exception as exc:
                    print(f"[trainsh-runtime] callback sink close failed: {exc}")


class ConsoleCallbackSink:
    """Print concise progress lines to console."""

    def __init__(self, log_callback: Callable[[str], None] = print):
        self.log_callback = log_callback

    def send(self, event: CallbackEvent) -> None:
        if event.event == "execution_start":
            self.log_callback(
                f"[runtime] start recipe={event.recipe_name} run_id={event.run_id}"
            )
        elif event.event == "step_start":
            step = event.step_num or 0
            self.log_callback(f"[runtime] step start #{step}: {event.payload.get('raw', '')}")
        elif event.event == "step_end":
            step = event.step_num or 0
            ok = event.payload.get("success")
            self.log_callback(
                f"[runtime] step end #{step}: {'OK' if ok else 'FAIL'}"
            )
        elif event.event == "execution_end":
            ok = event.payload.get("success")
            self.log_callback(
                f"[runtime] end run_id={event.run_id} result={'OK' if ok else 'FAIL'}"
            )


class SqliteCallbackSink:
    """Persist execution events in sqlite database."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or CONFIG_DIR / "runtime.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = connect_runtime_db(self.db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._closed = False
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Initialize callback tables."""
        ensure_runtime_schema(self.conn)

    def _serialize(self, payload: Dict[str, Any]) -> str:
        return json_dumps(payload)

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on", "y"}:
            return True
        if text in {"0", "false", "no", "off", "n", ""}:
            return False
        return default

    @staticmethod
    def _coerce_dag_id(recipe_name: str, recipe_path: str) -> str:
        name = str(recipe_name or "").strip()
        path_text = str(recipe_path or "").strip()
        if path_text:
            return path_text
        if name:
            return name
        return "unknown_dag"

    @staticmethod
    def _coerce_text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        text = str(value).strip()
        return text or default

    @staticmethod
    def _coerce_int(value: Any, *, default: int = 1) -> int:
        try:
            parsed = int(value)
        except Exception:
            return default
        return parsed

    def send(self, event: CallbackEvent) -> None:
        if self._closed:
            return
        with self._lock:
            now = datetime.now().isoformat()
            payload_json = self._serialize(event.payload)
            dag_id = self._coerce_dag_id(event.recipe_name, event.recipe_path)
            run_type = self._coerce_text(event.payload.get("run_type"), "manual")
            try_number = self._coerce_int(event.payload.get("try_number"), default=1)
            execution_date = self._coerce_text(event.payload.get("execution_date"), "")

            if event.event == "execution_start":
                hosts = event.payload.get("hosts")
                if isinstance(hosts, dict):
                    replace_run_hosts(self.conn, event.run_id, hosts)
                storages = event.payload.get("storages")
                if isinstance(storages, dict):
                    replace_run_storages(self.conn, event.run_id, storages)
                self.conn.execute(
                    """
                    INSERT INTO dag (
                        dag_id, file_path, is_paused, is_active, owner, created_at, updated_at
                    ) VALUES (?, ?, 0, 1, 'trainsh', ?, ?)
                    ON CONFLICT(dag_id) DO UPDATE SET
                        file_path=excluded.file_path,
                        updated_at=excluded.updated_at
                    """,
                    (
                        dag_id,
                        event.recipe_path,
                        event.ts,
                        now,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO dag_run (
                        dag_id, run_id, state, run_type, execution_date, start_date,
                        end_date, external_trigger, conf
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?)
                    """,
                    (
                        dag_id,
                        event.run_id,
                        "running",
                        run_type,
                        event.ts,
                        event.ts,
                        payload_json,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO recipe_runs (
                        run_id, recipe_name, recipe_path, status, started_at, ended_at,
                        duration_ms, success, metadata_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
                    """,
                    (
                        event.run_id,
                        event.recipe_name,
                        event.recipe_path,
                        "running",
                        event.ts,
                        self._serialize(event.payload),
                        now,
                    ),
                )

            elif event.event == "step_start":
                step_id = str(event.payload.get("step_id", "")).strip()
                if not step_id:
                    if event.step_num is not None:
                        step_id = f"step_{int(event.step_num):04d}"
                    else:
                        step_id = "anonymous"
                details = event.payload.get("details")
                if not isinstance(details, dict):
                    details = dict(event.payload)

                self.conn.execute(
                    """
                    INSERT INTO task_instance (
                        dag_id, task_id, run_id, state, start_date, end_date,
                        duration_ms, operator, host, pool, trigger_rule,
                        details_json, output, try_number
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, ?)
                    ON CONFLICT(dag_id, task_id, run_id) DO UPDATE SET
                        state=excluded.state,
                        start_date=excluded.start_date,
                        operator=excluded.operator,
                        host=excluded.host,
                        pool=excluded.pool,
                        trigger_rule=excluded.trigger_rule,
                        details_json=excluded.details_json,
                        try_number=excluded.try_number,
                        duration_ms=COALESCE(excluded.duration_ms, task_instance.duration_ms),
                        output=COALESCE(task_instance.output, excluded.output)
                    """,
                    (
                        dag_id,
                        step_id,
                        event.run_id,
                        "running",
                        event.ts,
                        None,
                        str(details.get("operation", "")),
                        str(details.get("host", "")),
                        str(details.get("pool", "default")),
                        str(details.get("trigger_rule", "all_success")),
                        self._serialize(details),
                        try_number,
                    ),
                )

            elif event.event == "step_end":
                step_id = str(event.payload.get("step_id", "")).strip()
                if not step_id:
                    if event.step_num is not None:
                        step_id = f"step_{int(event.step_num):04d}"
                    else:
                        step_id = "anonymous"
                details = event.payload.get("details")
                if not isinstance(details, dict):
                    details = dict(event.payload)
                success = self._as_bool(event.payload.get("success"), default=True)
                state = str(event.payload.get("state", "")).strip().lower()
                duration_ms = event.payload.get("duration_ms", 0)
                try:
                    duration_ms = int(duration_ms)
                except Exception:
                    duration_ms = 0

                normalized_state = state
                if normalized_state not in {
                    "success",
                    "failed",
                    "skipped",
                    "upstream_failed",
                    "up_for_retry",
                    "up_for_reschedule",
                    "deferred",
                    "running",
                    "queued",
                    "restarting",
                    "removed",
                }:
                    normalized_state = "success" if success else "failed"

                output_text = event.payload.get("output")
                if output_text is None:
                    output_text = event.payload.get("error")
                if isinstance(output_text, dict):
                    output_text = self._serialize(output_text)
                elif output_text is None:
                    output_text = ""
                else:
                    output_text = str(output_text)

                self.conn.execute(
                    """
                    INSERT INTO task_instance (
                        dag_id, task_id, run_id, state, start_date, end_date,
                        duration_ms, operator, host, pool, trigger_rule,
                        details_json, output, try_number
                    ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(dag_id, task_id, run_id) DO UPDATE SET
                        state=excluded.state,
                        end_date=excluded.end_date,
                        duration_ms=excluded.duration_ms,
                        operator=excluded.operator,
                        host=excluded.host,
                        pool=excluded.pool,
                        trigger_rule=excluded.trigger_rule,
                        details_json=excluded.details_json,
                        output=excluded.output,
                        try_number=excluded.try_number,
                        start_date=COALESCE(task_instance.start_date, excluded.start_date)
                    """,
                    (
                        dag_id,
                        step_id,
                        event.run_id,
                        normalized_state,
                        event.ts,
                        duration_ms,
                        str(details.get("operation", "")),
                        str(details.get("host", "")),
                        str(details.get("pool", "default")),
                        str(details.get("trigger_rule", "all_success")),
                        self._serialize(details),
                        output_text,
                        try_number,
                    ),
                )

            elif event.event == "xcom_push":
                task_id = self._coerce_text(event.payload.get("task_id"), "")
                if not task_id:
                    if event.step_num is not None:
                        task_id = f"step_{int(event.step_num):04d}"
                    else:
                        task_id = "anonymous"
                key = self._coerce_text(event.payload.get("key"), "")
                if key:
                    map_index = self._coerce_int(event.payload.get("map_index"), default=0)
                    self.conn.execute(
                        """
                        INSERT INTO xcom (
                            dag_id, task_id, run_id, map_index, key, value, created_at, execution_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(dag_id, task_id, run_id, map_index, key) DO UPDATE SET
                            value=excluded.value,
                            created_at=excluded.created_at,
                            execution_date=excluded.execution_date
                        """,
                        (
                            dag_id,
                            task_id,
                            event.run_id,
                            map_index,
                            key,
                            self._coerce_text(event.payload.get("value")),
                            now,
                            execution_date,
                        ),
                    )

            elif event.event == "execution_end":
                success = self._as_bool(event.payload.get("success"), default=False)
                self.conn.execute(
                    """
                    UPDATE dag_run
                    SET state=?, end_date=? , conf=?
                    WHERE dag_id=? AND run_id=?
                    """,
                    (
                        "success" if success else "failed",
                        event.ts,
                        payload_json,
                        dag_id,
                        event.run_id,
                    ),
                )
                self.conn.execute(
                    """
                    UPDATE recipe_runs
                    SET status=?, ended_at=?, duration_ms=?, success=?, metadata_json=?, updated_at=?
                    WHERE run_id=?
                    """,
                    (
                        "succeeded" if event.payload.get("success") else "failed",
                        event.ts,
                        event.payload.get("duration_ms"),
                        1 if event.payload.get("success") else 0,
                        self._serialize(event.payload),
                        now,
                        event.run_id,
                    ),
                )

            self.conn.execute(
                """
                INSERT INTO recipe_events (
                    run_id, event_name, step_num, payload_json, ts
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.event,
                    event.step_num,
                    payload_json,
                    event.ts,
                ),
            )
            self.conn.commit()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.conn.close()
        except Exception:
            pass
        self._closed = True

    def __del__(self):
        if hasattr(self, "conn"):
            self.close()


def _sink_factory(name: str, **kwargs: Any) -> CallbackSink:
    """Build built-in callback sink by name."""
    lower = name.lower()
    if lower in ("console", "stdout", "print"):
        return ConsoleCallbackSink(log_callback=kwargs.get("log_callback", print))
    if lower == "sqlite":
        db_path = kwargs.get("sqlite_db")
        return SqliteCallbackSink(db_path=db_path)
    raise ValueError(f"unknown callback sink: {name}")


def build_sinks(
    names: Optional[Sequence[str]],
    *,
    log_callback: Callable[[str], None] = print,
    sqlite_db: Optional[str] = None,
) -> List[CallbackSink]:
    """Build callback sinks from simple names."""
    if not names:
        return []
    sinks: List[CallbackSink] = []
    for raw_name in names:
        if not raw_name:
            continue
        parts = [part.strip().lower() for part in str(raw_name).split(",") if part.strip()]
        if not parts:
            continue
        for part in parts:
            sinks.append(_sink_factory(part, log_callback=log_callback, sqlite_db=sqlite_db))
    return sinks

from .runtime_executors import (
    AirflowExecutor,
    CELERY_EXECUTOR_ALIASES,
    DaskExecutor,
    DebugExecutor,
    ExecutionExecutor,
    PARALLEL_EXECUTOR_ALIASES,
    ProcessPoolExecutor,
    SEQUENTIAL_EXECUTOR_ALIASES,
    THREAD_EXECUTOR_ALIASES,
    CeleryExecutor,
    LocalExecutor,
    NoopExecutor,
    SequentialExecutor,
    ThreadPoolExecutor,
    _coerce_max_workers,
    get_executor,
    normalize_executor_name,
)
