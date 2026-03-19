"""JSONL-backed runtime state store."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..constants import RUNTIME_STATE_DIR


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


def json_dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), ensure_ascii=False)


def json_loads(text: Any, default: Any) -> Any:
    if text in (None, ""):
        return default
    try:
        return json.loads(str(text))
    except Exception:
        return default


def get_runtime_state_dir(path: str | os.PathLike[str] | None = None) -> Path:
    if path is None:
        target = RUNTIME_STATE_DIR
    else:
        raw = Path(path).expanduser()
        target = raw.with_suffix("") if raw.suffix else raw
    target.mkdir(parents=True, exist_ok=True)
    return target


def _record_sort_key(record: Dict[str, Any]) -> str:
    return str(
        record.get("updated_at")
        or record.get("ts")
        or record.get("created_at")
        or record.get("started_at")
        or ""
    )


class RuntimeStore:
    """Append-only JSONL runtime store with latest-snapshot helpers."""

    def __init__(self, root: str | os.PathLike[str] | None = None):
        self.root = get_runtime_state_dir(root)
        self.runs_path = self.root / "runs.jsonl"
        self.tasks_path = self.root / "tasks.jsonl"
        self.events_path = self.root / "events.jsonl"
        self.checkpoints_path = self.root / "checkpoints.jsonl"
        self.xcom_path = self.root / "xcom.jsonl"
        self.pools_path = self.root / "pools.json"
        self._lock = threading.RLock()

    def _append_jsonl(self, path: Path, record: Dict[str, Any]) -> None:
        payload = dict(to_jsonable(record))
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False))
                handle.write("\n")

    def _iter_jsonl(self, path: Path) -> Iterable[Dict[str, Any]]:
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except Exception:
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
        return records

    def _latest_by(self, path: Path, key_fields: tuple[str, ...]) -> Dict[tuple[str, ...], Dict[str, Any]]:
        latest: Dict[tuple[str, ...], Dict[str, Any]] = {}
        for record in self._iter_jsonl(path):
            key = tuple(str(record.get(field, "") or "") for field in key_fields)
            if not any(key):
                continue
            previous = latest.get(key)
            if previous is None or _record_sort_key(record) >= _record_sort_key(previous):
                latest[key] = record
        return latest

    def append_run(self, record: Dict[str, Any]) -> None:
        self._append_jsonl(self.runs_path, record)

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._latest_by(self.runs_path, ("run_id",)).get((str(run_id),))

    def list_runs(self, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        runs = [
            record
            for record in self._latest_by(self.runs_path, ("run_id",)).values()
            if not record.get("_deleted")
        ]
        runs.sort(key=lambda item: (_record_sort_key(item), str(item.get("run_id", ""))), reverse=True)
        if limit is not None:
            runs = runs[: max(0, int(limit))]
        return runs

    def append_task(self, record: Dict[str, Any]) -> None:
        self._append_jsonl(self.tasks_path, record)

    def list_tasks(self, *, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        tasks = [
            record
            for record in self._latest_by(self.tasks_path, ("run_id", "task_id")).values()
            if not record.get("_deleted")
        ]
        if run_id is not None:
            tasks = [record for record in tasks if str(record.get("run_id", "")) == str(run_id)]
        tasks.sort(key=lambda item: (_record_sort_key(item), str(item.get("task_id", ""))))
        return tasks

    def append_event(self, record: Dict[str, Any]) -> None:
        self._append_jsonl(self.events_path, record)

    def list_events(self, run_id: str) -> List[Dict[str, Any]]:
        records = [record for record in self._iter_jsonl(self.events_path) if str(record.get("run_id", "")) == str(run_id)]
        records.sort(key=_record_sort_key)
        return records

    def save_checkpoint(self, record: Dict[str, Any]) -> None:
        self._append_jsonl(self.checkpoints_path, record)

    def get_checkpoint(self, run_id: str) -> Optional[Dict[str, Any]]:
        record = self._latest_by(self.checkpoints_path, ("run_id",)).get((str(run_id),))
        if record and record.get("_deleted"):
            return None
        return record

    def list_checkpoints(self, *, limit: Optional[int] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        records = [
            record
            for record in self._latest_by(self.checkpoints_path, ("run_id",)).values()
            if not record.get("_deleted")
        ]
        if status is not None:
            records = [record for record in records if str(record.get("status", "")) == status]
        records.sort(key=lambda item: (_record_sort_key(item), str(item.get("run_id", ""))), reverse=True)
        if limit is not None:
            records = records[: max(0, int(limit))]
        return records

    def latest_checkpoint_for_recipe(
        self,
        recipe_path: str,
        *,
        statuses: Optional[set[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        target = os.path.abspath(os.path.expanduser(recipe_path))
        matches = []
        for record in self.list_checkpoints():
            if os.path.abspath(os.path.expanduser(str(record.get("recipe_path", "")))) != target:
                continue
            if statuses and str(record.get("status", "")) not in statuses:
                continue
            matches.append(record)
        return matches[0] if matches else None

    def delete_checkpoint(self, run_id: str) -> None:
        record = self.get_checkpoint(run_id)
        if not record:
            return
        tombstone = dict(record)
        tombstone["_deleted"] = True
        tombstone["updated_at"] = datetime.now().isoformat()
        self.save_checkpoint(tombstone)

    def cleanup_checkpoints(self, *, cutoff: str, statuses: set[str]) -> int:
        removed = 0
        for record in self.list_checkpoints():
            if str(record.get("status", "")) not in statuses:
                continue
            if str(record.get("updated_at", "")) >= cutoff:
                continue
            self.delete_checkpoint(str(record.get("run_id", "")))
            removed += 1
        return removed

    def append_xcom(self, record: Dict[str, Any]) -> None:
        self._append_jsonl(self.xcom_path, record)

    def query_xcom(
        self,
        *,
        dag_id: str,
        key: str,
        run_id: str,
        task_ids: Optional[List[str]] = None,
        include_prior_dates: bool = False,
        map_index: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        task_id_set = {str(item) for item in (task_ids or []) if str(item).strip()}
        records = []
        for record in self._iter_jsonl(self.xcom_path):
            if str(record.get("dag_id", "")) != str(dag_id):
                continue
            if str(record.get("key", "")) != str(key):
                continue
            if task_id_set and str(record.get("task_id", "")) not in task_id_set:
                continue
            if not include_prior_dates and str(record.get("run_id", "")) != str(run_id):
                continue
            if map_index is not None and int(record.get("map_index", 0) or 0) != int(map_index):
                continue
            records.append(record)
        if not records:
            return None
        records.sort(key=_record_sort_key, reverse=True)
        return records[0]

    def latest_run_start(self, dag_id: str) -> Optional[datetime]:
        matches = [
            record
            for record in self.list_runs()
            if str(record.get("dag_id", "")) == str(dag_id)
        ]
        if not matches:
            return None
        raw = str(matches[0].get("started_at", ""))
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    def count_running_runs(self, dag_id: Optional[str] = None) -> int:
        count = 0
        for record in self.list_runs():
            if str(record.get("state", record.get("status", ""))).lower() != "running":
                continue
            if dag_id is not None and str(record.get("dag_id", "")) != str(dag_id):
                continue
            count += 1
        return count

    def load_pools(self) -> Dict[str, Dict[str, Any]]:
        if not self.pools_path.exists():
            return {}
        try:
            payload = json.loads(self.pools_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        pools = payload.get("pools", {})
        return dict(pools) if isinstance(pools, dict) else {}

    def save_pools(self, pools: Dict[str, Dict[str, Any]]) -> None:
        self.pools_path.parent.mkdir(parents=True, exist_ok=True)
        self.pools_path.write_text(
            json.dumps({"pools": to_jsonable(pools)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


__all__ = [
    "RuntimeStore",
    "get_runtime_state_dir",
    "json_dumps",
    "json_loads",
    "to_jsonable",
]
