import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import Future
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.dag_executor import DagExecutionResult
from trainsh.core.dag_processor import ParsedDag, parse_schedule
from trainsh.core.scheduler import DagRunState, DagScheduler


def make_dag(name: str, *, schedule="@every 5m", paused=False, valid=True, load_error=None, max_active_runs=1, max_active_runs_per_dag=None):
    return ParsedDag(
        dag_id=f"/tmp/{name}.py",
        path=Path(f"/tmp/{name}.py"),
        recipe_name=name,
        is_python=True,
        schedule=schedule,
        schedule_meta=parse_schedule(schedule),
        is_paused=paused,
        load_error=load_error if not valid else None,
        max_active_runs=max_active_runs,
        max_active_runs_per_dag=max_active_runs_per_dag,
    )


class SchedulerMoreTests(unittest.TestCase):
    def test_run_once_filters_wait_and_manual_force_paths(self):
        due = make_dag("due")
        paused = make_dag("paused", paused=True)
        invalid = make_dag("invalid", valid=False, load_error="boom")
        blocked = make_dag("blocked")
        processor = SimpleNamespace(discover_dags=lambda: [due, paused, invalid, blocked])
        scheduler = DagScheduler(dag_processor=processor, dag_executor=SimpleNamespace(run=lambda *a, **k: None))

        scheduler._is_due = MagicMock(side_effect=lambda dag, now: dag.recipe_name == "due")
        scheduler._can_run = MagicMock(side_effect=lambda dag: dag.recipe_name != "blocked")
        scheduler._submit = MagicMock(side_effect=lambda dag, now, run_type="manual": SimpleNamespace(recipe_name=dag.recipe_name, state=DagRunState.RUNNING, future=None, dag_id=dag.dag_id, run_id="run1", message=run_type))
        scheduler._wait_for_records = MagicMock()
        scheduler._drain_futures = MagicMock()

        records = scheduler.run_once(wait=True)
        self.assertEqual([r.recipe_name for r in records], ["due"])
        scheduler._wait_for_records.assert_called_once()

        scheduler._wait_for_records.reset_mock()
        scheduler._drain_futures.reset_mock()
        records = scheduler.run_once(force=True, dag_ids=["paused"], include_invalid=True)
        self.assertEqual([r.recipe_name for r in records], ["paused"])
        scheduler._drain_futures.assert_called()

    def test_run_forever_shutdown_and_active_records(self):
        scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), dag_executor=SimpleNamespace(run=lambda *a, **k: None), loop_interval=1)
        calls = []
        scheduler.run_once = lambda **kwargs: calls.append(kwargs)
        scheduler._drain_futures = lambda: calls.append("drain")
        scheduler.shutdown = MagicMock()
        with patch("trainsh.core.scheduler.time.sleep"):
            scheduler.run_forever(max_iterations=2, force=True, wait_completed=True)
        self.assertEqual(len([c for c in calls if isinstance(c, dict)]), 2)
        scheduler.shutdown.assert_called_once()

        scheduler._active = {Future(): SimpleNamespace(dag_id="a")}
        scheduler._drain_futures = MagicMock()
        records = scheduler.active_records()
        self.assertEqual(len(records), 1)
        scheduler._drain_futures.assert_called_once()

        scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), dag_executor=SimpleNamespace(run=lambda *a, **k: None))
        scheduler._pool = SimpleNamespace(shutdown=MagicMock())
        scheduler.shutdown()
        scheduler._pool.shutdown.assert_called_once_with(wait=False, cancel_futures=True)

    def test_submit_drain_wait_and_due_helpers(self):
        dag = make_dag("demo", max_active_runs=4, max_active_runs_per_dag=3)
        scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), dag_executor=SimpleNamespace(run=lambda *a, **k: None))
        fake_future = Future()
        scheduler._pool.submit = MagicMock(return_value=fake_future)
        now = datetime.now(timezone.utc)
        record = scheduler._submit(dag, now=now, run_type="scheduled")
        self.assertEqual(record.state, DagRunState.RUNNING)
        self.assertIn(dag.dag_id, scheduler._next_due)

        result = DagExecutionResult(
            dag_id=dag.dag_id,
            run_id="run1",
            recipe_path=str(dag.path),
            state="success",
            success=False,
            started_at=now,
            ended_at=now,
            message="failed",
        )
        future = Future()
        future.set_result(result)
        record = SimpleNamespace(dag_id=dag.dag_id, state=DagRunState.RUNNING, future=future, message="", ended_at=None, success=None)
        with scheduler._running_lock:
            scheduler._active = {future: record}
        scheduler._drain_futures()
        self.assertEqual(record.state, DagRunState.FAILED)
        self.assertFalse(record.success)

        future = Future()
        future.set_result("weird")
        record = SimpleNamespace(dag_id=dag.dag_id, state=DagRunState.RUNNING, future=future, message="", ended_at=None, success=None)
        with scheduler._running_lock:
            scheduler._active = {future: record}
        scheduler._drain_futures()
        self.assertEqual(record.state, DagRunState.ERROR)

        scheduler._drain_futures = MagicMock()
        scheduler._wait_for_records([SimpleNamespace(future=None)])
        scheduler._drain_futures.assert_not_called()

        f1 = Future()
        f1.set_result(None)
        scheduler._drain_futures = MagicMock()
        scheduler._wait_for_records([SimpleNamespace(future=f1)])
        scheduler._drain_futures.assert_called_once()

        scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), dag_executor=SimpleNamespace(run=lambda *a, **k: None))
        scheduler._next_due = {}
        scheduler._latest_run_start = MagicMock(return_value=None)
        now = datetime.now(timezone.utc)
        self.assertTrue(scheduler._is_due(dag, now=now))
        self.assertIn(dag.dag_id, scheduler._next_due)

        scheduler._next_due = {}
        scheduler._latest_run_start = MagicMock(return_value=now)
        self.assertFalse(scheduler._is_due(dag, now=now))

    def test_db_counts_sqlite_helpers_and_filters(self):
        dag = make_dag("demo")
        with tempfile.TemporaryDirectory() as tmpdir:
            from trainsh.core.runtime_store import RuntimeStore

            db_path = Path(tmpdir) / "runtime"
            scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), dag_executor=SimpleNamespace(run=lambda *a, **k: None), runtime_state=str(db_path))
            RuntimeStore(db_path).append_run(
                {
                    "run_id": "run-1",
                    "dag_id": dag.dag_id,
                    "recipe_name": dag.recipe_name,
                    "recipe_path": str(dag.path),
                    "state": "running",
                    "status": "running",
                    "started_at": "2026-03-13T00:00:00+00:00",
                    "updated_at": "2026-03-13T00:00:00+00:00",
                }
            )

            self.assertEqual(scheduler._count_db_running(), 1)
            self.assertEqual(scheduler._count_db_running(dag.dag_id), 1)
            self.assertIsNotNone(scheduler._latest_run_start(dag.dag_id))
            self.assertIsNone(scheduler._parse_time(""))
            self.assertIsNotNone(scheduler._parse_time("1700000000"))

            scheduler._drain_futures = MagicMock()
            scheduler._active = {Future(): SimpleNamespace(dag_id=dag.dag_id), Future(): SimpleNamespace(dag_id="other")}
            self.assertEqual(scheduler._count_local_running(), 2)
            self.assertEqual(scheduler._count_local_running(dag.dag_id), 1)

            scheduler.max_active_runs = 2
            scheduler.max_active_runs_per_dag = 2
            scheduler._active = {}
            scheduler._count_db_running = MagicMock(side_effect=lambda dag_id=None: 0)
            self.assertTrue(scheduler._can_run(dag))
            scheduler._count_db_running = MagicMock(side_effect=lambda dag_id=None: 2 if dag_id is None else 0)
            self.assertFalse(scheduler._can_run(dag))

            self.assertTrue(scheduler._matches_filter(dag, {dag.recipe_name}))
            self.assertTrue(scheduler._matches_filter(dag, {dag.path.name}))
            self.assertFalse(scheduler._matches_filter(dag, {"missing"}))

        scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), dag_executor=SimpleNamespace(run=lambda *a, **k: None), runtime_state="/tmp/does-not-exist/dir/runtime")
        self.assertEqual(scheduler._count_db_running(), 0)
        self.assertIsNone(scheduler._latest_run_start("missing"))


if __name__ == "__main__":
    unittest.main()
