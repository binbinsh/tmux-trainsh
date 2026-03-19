"""Simple DAG scheduler core inspired by Airflow scheduling primitives."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ..constants import RUNTIME_STATE_DIR
from .dag_executor import DagExecutionResult, DagExecutor
from .dag_processor import DagProcessor, ParsedDag
from .runtime_store import RuntimeStore


class DagRunState:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass
class DagRunRecord:
    dag_id: str
    run_id: str
    recipe_path: str
    state: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    success: Optional[bool] = None
    message: str = ""
    future: Optional[Future] = None


class DagScheduler:
    """Core scheduler loop: discover DAGs, evaluate schedule, dispatch executor."""

    def __init__(
        self,
        *,
        dag_processor: Optional[DagProcessor] = None,
        dag_executor: Optional[DagExecutor] = None,
        dags_dir: Optional[str | Path] = None,
        max_active_runs: int = 16,
        max_active_runs_per_dag: int = 1,
        runtime_state: Optional[str] = None,
        loop_interval: int = 60,
    ):
        self.processor = dag_processor or DagProcessor([str(dags_dir)] if dags_dir else None)
        self.executor = dag_executor or DagExecutor()
        self.max_active_runs = max(1, int(max_active_runs))
        self.max_active_runs_per_dag = max(1, int(max_active_runs_per_dag))
        self.loop_interval = max(1, int(loop_interval))
        self.runtime_state = runtime_state or str(RUNTIME_STATE_DIR)
        self.store = RuntimeStore(self.runtime_state)

        self._running_lock = threading.Lock()
        self._active: Dict[Future, DagRunRecord] = {}
        self._next_due: Dict[str, datetime] = {}
        self._pool = ThreadPoolExecutor(max_workers=self.max_active_runs)

    def run_once(
        self,
        *,
        force: bool = False,
        dag_ids: Optional[Sequence[str]] = None,
        wait: bool = False,
        include_invalid: bool = False,
    ) -> List[DagRunRecord]:
        """Run one scheduling round and return started/completed run records."""
        now = datetime.now(timezone.utc)
        self._drain_futures()

        discovered = self.processor.discover_dags()
        records: List[DagRunRecord] = []
        allowed = set(dag_ids or [])

        for dag in discovered:
            if dag_ids and not self._matches_filter(dag, allowed):
                continue
            if not dag.is_enabled and not force:
                continue
            if not include_invalid and not dag.is_valid:
                continue
            if dag.load_error is not None and not include_invalid:
                continue
            is_due = self._is_due(dag, now=now)
            if not force and not is_due:
                continue
            if not self._can_run(dag):
                continue
            run_type = "scheduled" if not force and is_due else "manual"
            records.append(self._submit(dag, now=now, run_type=run_type))

        if wait:
            self._wait_for_records(records)
        else:
            self._drain_futures()

        return records

    def run_forever(
        self,
        *,
        force: bool = False,
        dag_ids: Optional[Sequence[str]] = None,
        loop_interval: Optional[int] = None,
        max_iterations: Optional[int] = None,
        wait_completed: bool = False,
    ) -> None:
        """Long-running scheduling loop."""
        interval = self.loop_interval if loop_interval is None else max(1, int(loop_interval))
        iterations = 0
        try:
            while max_iterations is None or iterations < max_iterations:
                self.run_once(force=force, dag_ids=dag_ids, wait=wait_completed)
                self._drain_futures()
                iterations += 1
                if max_iterations is not None and iterations >= max_iterations:
                    break
                time.sleep(interval)
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def active_records(self) -> List[DagRunRecord]:
        self._drain_futures()
        return list(self._active.values())

    def _submit(self, dag: ParsedDag, *, now: datetime, run_type: str = "manual") -> DagRunRecord:
        if dag.schedule_meta.is_due_capable and dag.schedule_meta.interval_seconds:
            self._next_due[dag.dag_id] = now + timedelta(seconds=dag.schedule_meta.interval_seconds)

        run_id = uuid4().hex
        record = DagRunRecord(
            dag_id=dag.dag_id,
            run_id=run_id,
            recipe_path=str(dag.path),
            state=DagRunState.QUEUED,
            started_at=now,
            message=dag.schedule or "manual",
        )
        future = self._pool.submit(self.executor.run, dag, run_id=run_id, run_type=run_type)
        record.state = DagRunState.RUNNING
        record.future = future
        with self._running_lock:
            self._active[future] = record
        return record

    def _drain_futures(self) -> None:
        done: List[tuple[Future, DagRunRecord]] = []
        with self._running_lock:
            for future, record in list(self._active.items()):
                if not future.done():
                    continue
                done.append((future, record))

        for future, record in done:
            try:
                result = future.result()
                if isinstance(result, DagExecutionResult):
                    if result.success:
                        record.state = DagRunState.SUCCESS
                    else:
                        record.state = DagRunState.FAILED
                    record.success = result.success
                    record.message = result.message
                else:
                    record.state = DagRunState.ERROR
                    record.message = "unexpected executor result"
            except Exception as exc:  # noqa: BLE001
                record.state = DagRunState.ERROR
                record.message = str(exc)
            record.ended_at = datetime.now(timezone.utc)
            with self._running_lock:
                self._active.pop(future, None)

    def _wait_for_records(self, records: Iterable[DagRunRecord]) -> None:
        futures = [record.future for record in records if record.future is not None]
        if not futures:
            return
        for future in as_completed(futures):
            future.result()
        self._drain_futures()

    def _is_due(self, dag: ParsedDag, *, now: datetime) -> bool:
        if not dag.schedule_meta.is_due_capable or not dag.schedule_meta.interval_seconds:
            return False

        next_due = self._next_due.get(dag.dag_id)
        if next_due is None:
            last = self._latest_run_start(dag.dag_id)
            if last is None:
                next_due = now
            else:
                next_due = last + timedelta(seconds=dag.schedule_meta.interval_seconds)
            self._next_due[dag.dag_id] = next_due

        return now >= next_due

    def _can_run(self, dag: ParsedDag) -> bool:
        dag_active_limit = min(self.max_active_runs_per_dag, dag.normalized_max_active_runs_per_dag)
        local_active = self._count_local_running(dag.dag_id)
        db_active = self._count_db_running(dag.dag_id)
        if (local_active + db_active) >= dag_active_limit:
            return False

        local_total = self._count_local_running()
        db_total = self._count_db_running()
        return (local_total + db_total) < self.max_active_runs

    def _count_local_running(self, dag_id: Optional[str] = None) -> int:
        self._drain_futures()
        with self._running_lock:
            if dag_id is None:
                return len(self._active)
            return sum(1 for rec in self._active.values() if rec.dag_id == dag_id)

    def _latest_run_start(self, dag_id: str) -> Optional[datetime]:
        return self.store.latest_run_start(dag_id)

    def _count_db_running(self, dag_id: Optional[str] = None) -> int:
        return self.store.count_running_runs(dag_id)

    def _parse_time(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.fromtimestamp(float(value), tz=timezone.utc)
            except Exception:
                return None

    def _matches_filter(self, dag: ParsedDag, filters: set[str]) -> bool:
        if not filters:
            return True
        for token in filters:
            if dag.dag_id == token:
                return True
            if dag.recipe_name == token:
                return True
            if dag.path.name == token:
                return True
        return False


__all__ = ["DagScheduler", "DagRunRecord", "DagRunState"]
