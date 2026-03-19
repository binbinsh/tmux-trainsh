# Runtime helpers inspired by Airflow-style execution primitives.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Protocol
from datetime import datetime

import json
import threading

from .constants import RUNTIME_STATE_DIR
from .core.runtime_store import RuntimeStore, json_dumps


CONFIG_DIR = RUNTIME_STATE_DIR


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


class JsonlCallbackSink:
    """Persist execution events in JSONL runtime state files."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or CONFIG_DIR)
        self.store = RuntimeStore(self.db_path)
        self._lock = threading.Lock()
        self._closed = False

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
            dag_id = self._coerce_dag_id(event.recipe_name, event.recipe_path)
            run_type = self._coerce_text(event.payload.get("run_type"), "manual")
            try_number = self._coerce_int(event.payload.get("try_number"), default=1)
            execution_date = self._coerce_text(event.payload.get("execution_date"), "")
            payload_json = self._serialize(event.payload)

            if event.event == "execution_start":
                self.store.append_run(
                    {
                        "run_id": event.run_id,
                        "dag_id": dag_id,
                        "recipe_name": event.recipe_name,
                        "recipe_path": event.recipe_path,
                        "status": "running",
                        "state": "running",
                        "run_type": run_type,
                        "execution_date": event.ts,
                        "started_at": event.ts,
                        "ended_at": "",
                        "duration_ms": None,
                        "success": None,
                        "metadata": dict(event.payload),
                        "hosts": event.payload.get("hosts", {}) if isinstance(event.payload.get("hosts"), dict) else {},
                        "storages": event.payload.get("storages", {}) if isinstance(event.payload.get("storages"), dict) else {},
                        "updated_at": now,
                    }
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

                self.store.append_task(
                    {
                        "dag_id": dag_id,
                        "task_id": step_id,
                        "run_id": event.run_id,
                        "state": "running",
                        "start_date": event.ts,
                        "end_date": "",
                        "duration_ms": None,
                        "operator": str(details.get("operation", "")),
                        "host": str(details.get("host", "")),
                        "pool": str(details.get("pool", "default")),
                        "trigger_rule": str(details.get("trigger_rule", "all_success")),
                        "details": details,
                        "output": "",
                        "try_number": try_number,
                        "updated_at": now,
                    }
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

                existing = {
                    str(item.get("task_id", "")): item
                    for item in self.store.list_tasks(run_id=event.run_id)
                }.get(step_id, {})
                self.store.append_task(
                    {
                        "dag_id": dag_id,
                        "task_id": step_id,
                        "run_id": event.run_id,
                        "state": normalized_state,
                        "start_date": str(existing.get("start_date", "") or event.ts),
                        "end_date": event.ts,
                        "duration_ms": duration_ms,
                        "operator": str(details.get("operation", existing.get("operator", ""))),
                        "host": str(details.get("host", existing.get("host", ""))),
                        "pool": str(details.get("pool", existing.get("pool", "default"))),
                        "trigger_rule": str(details.get("trigger_rule", existing.get("trigger_rule", "all_success"))),
                        "details": details,
                        "output": output_text,
                        "try_number": try_number,
                        "updated_at": now,
                    }
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
                    self.store.append_xcom(
                        {
                            "dag_id": dag_id,
                            "task_id": task_id,
                            "run_id": event.run_id,
                            "map_index": map_index,
                            "key": key,
                            "value": self._coerce_text(event.payload.get("value")),
                            "created_at": now,
                            "execution_date": execution_date or now,
                            "updated_at": now,
                        }
                    )

            elif event.event == "execution_end":
                success = self._as_bool(event.payload.get("success"), default=False)
                previous = self.store.get_run(event.run_id) or {}
                self.store.append_run(
                    {
                        "run_id": event.run_id,
                        "dag_id": dag_id,
                        "recipe_name": event.recipe_name,
                        "recipe_path": event.recipe_path,
                        "status": "succeeded" if success else "failed",
                        "state": "success" if success else "failed",
                        "run_type": str(previous.get("run_type", run_type)),
                        "execution_date": str(previous.get("execution_date", event.ts)),
                        "started_at": str(previous.get("started_at", event.ts)),
                        "ended_at": event.ts,
                        "duration_ms": event.payload.get("duration_ms"),
                        "success": success,
                        "metadata": dict(event.payload),
                        "hosts": previous.get("hosts", {}),
                        "storages": previous.get("storages", {}),
                        "updated_at": now,
                    }
                )

            self.store.append_event(
                {
                    "run_id": event.run_id,
                    "event": event.event,
                    "event_name": event.event,
                    "step_num": event.step_num,
                    "payload": dict(event.payload),
                    "payload_json": payload_json,
                    "recipe_name": event.recipe_name,
                    "recipe_path": event.recipe_path,
                    "dag_id": dag_id,
                    "ts": event.ts,
                }
            )

    def close(self) -> None:
        self._closed = True

    def __del__(self):
        self.close()


def _sink_factory(name: str, **kwargs: Any) -> CallbackSink:
    """Build built-in callback sink by name."""
    lower = name.lower()
    if lower in ("console", "stdout", "print"):
        return ConsoleCallbackSink(log_callback=kwargs.get("log_callback", print))
    if lower == "jsonl":
        db_path = kwargs.get("runtime_state")
        return JsonlCallbackSink(db_path=db_path)
    raise ValueError(f"unknown callback sink: {name}")


def build_sinks(
    names: Optional[Sequence[str]],
    *,
    log_callback: Callable[[str], None] = print,
    runtime_state: Optional[str] = None,
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
            sinks.append(
                _sink_factory(
                    part,
                    log_callback=log_callback,
                    runtime_state=runtime_state,
                )
            )
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
