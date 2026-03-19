import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.commands.recipe_runtime import _show_execution_details, _show_job_details, cmd_jobs, cmd_logs, cmd_status
from trainsh.commands.schedule_cmd import _parse_args, cmd_schedule_list, cmd_schedule_run, cmd_schedule_status, main
from trainsh.core import DagRunState
from trainsh.core.execution_log import ExecutionLogReader
from trainsh.core.job_state import JobStateManager, JobState
from trainsh.core.job_state import JobState
from trainsh.core.runtime_store import RuntimeStore


def _capture(fn, *args, **kwargs) -> str:
    buffer = StringIO()
    with redirect_stdout(buffer):
        fn(*args, **kwargs)
    return buffer.getvalue()


def _seed_runtime_db(db_path: Path, recipe_path: Path) -> None:
    recipe_path = recipe_path.resolve()
    store = RuntimeStore(db_path)
    store.append_run(
        {
            "run_id": "job12345",
            "dag_id": str(recipe_path),
            "recipe_name": "demo",
            "recipe_path": str(recipe_path),
            "status": "succeeded",
            "state": "success",
            "run_type": "scheduled",
            "execution_date": "2026-03-12T09:00:00",
            "started_at": "2026-03-12T09:00:00",
            "ended_at": "2026-03-12T09:00:30",
            "duration_ms": 30000,
            "success": True,
            "updated_at": "2026-03-12T09:00:30",
            "hosts": {"gpu": "local"},
            "storages": {"artifacts": {"path": "/tmp/out"}},
        }
    )
    JobStateManager(str(db_path)).save(
        JobState(
            job_id="job12345",
            recipe_path=str(recipe_path),
            recipe_name="demo",
            current_step=1,
            total_steps=2,
            status="completed",
            variables={"MODEL": "tiny"},
            hosts={"gpu": "local"},
            storages={"artifacts": {"path": "/tmp/out"}},
            window_sessions={"gpu": "train_demo_0"},
            next_window_index=1,
            tmux_session="train_demo_0",
            updated_at="2026-03-12T09:00:30",
            created_at="2026-03-12T09:00:00",
        )
    )
    for event_name, step_num, payload, ts in [
        ("execution_start", None, {"variables": {"MODEL": "tiny"}}, "2026-03-12T09:00:00"),
        ("step_start", 1, {"state": "running"}, "2026-03-12T09:00:01"),
        ("detail", None, {"category": "execute", "message": "ran training"}, "2026-03-12T09:00:05"),
        ("step_end", 1, {"success": True, "state": "success", "duration_ms": 1000, "output": "ok", "error": ""}, "2026-03-12T09:00:06"),
        ("execution_end", None, {"success": True, "final_variables": {"MODEL": "tiny"}}, "2026-03-12T09:00:30"),
    ]:
        store.append_event(
            {
                "run_id": "job12345",
                "event": event_name,
                "event_name": event_name,
                "step_num": step_num,
                "payload": payload,
                "ts": ts,
            }
        )


class ScheduleCommandViewTests(unittest.TestCase):
    def test_parse_args_and_validation(self):
        parsed = _parse_args(
            [
                "run",
                "--forever",
                "--recipe",
                "demo",
                "--runtime-state",
                "/tmp/runtime",
                "--rows",
                "5",
                "--max-active-runs",
                "2",
                "--max-active-runs-per-recipe",
                "3",
            ]
        )
        self.assertEqual(parsed["mode"], "run")
        self.assertTrue(parsed["forever"])
        self.assertFalse(parsed["once"])
        self.assertEqual(parsed["dag_ids"], ["demo"])
        self.assertEqual(parsed["runtime_state"], "/tmp/runtime")
        self.assertEqual(parsed["rows"], 5)
        self.assertEqual(parsed["max_active_runs"], 2)
        self.assertEqual(parsed["max_active_runs_per_dag"], 3)

        with self.assertRaises(SystemExit):
            _parse_args(["status", "--rows", "0"], default_mode="status")

    def test_schedule_list_and_status_render_from_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            recipes_dir = root / "recipes"
            recipes_dir.mkdir()
            recipe_path = recipes_dir / "demo.pyrecipe"
            recipe_path.write_text(
                textwrap.dedent(
                    """
                    from trainsh import Recipe

                    recipe = Recipe("demo", schedule="@every 5m")
                    recipe.empty(id="start")
                    """
                ),
                encoding="utf-8",
            )
            db_path = root / "runtime"
            _seed_runtime_db(db_path, recipe_path)

            list_output = _capture(
                cmd_schedule_list,
                ["--recipes-dir", str(recipes_dir), "--runtime-state", str(db_path)],
            )
            self.assertIn("demo", list_output)
            self.assertIn("job12345", list_output)
            self.assertIn("@every 5m", list_output)

            status_output = _capture(cmd_schedule_status, ["--runtime-state", str(db_path), "--rows", "5"])
            self.assertIn("RECIPE\tRUN_ID\tSTATE\tRUN_TYPE\tSTARTED", status_output)
            self.assertIn("demo\tjob12345\tsuccess\tscheduled", status_output)

    def test_schedule_run_dispatches_once_forever_and_failure_output(self):
        scheduler = SimpleNamespace(
            run_once=lambda **kwargs: [SimpleNamespace(state=DagRunState.FAILED, dag_id="/tmp/demo.pyrecipe", run_id="job1", message="boom")],
            run_forever=lambda **kwargs: None,
        )
        with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
            with self.assertRaises(SystemExit):
                _capture(cmd_schedule_run, ["--wait", "--recipe", "demo"])

        scheduler = SimpleNamespace(
            run_once=lambda **kwargs: [SimpleNamespace(state="started", dag_id="/tmp/demo.pyrecipe", run_id="job2", message="queued")],
            run_forever=lambda **kwargs: None,
        )
        with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
            run_output = _capture(cmd_schedule_run, ["--recipe", "demo", "--force"])
            self.assertIn("started\tdemo\tjob2\tqueued", run_output)

        called = {}

        def _run_forever(**kwargs):
            called.update(kwargs)

        scheduler = SimpleNamespace(run_once=lambda **kwargs: [], run_forever=_run_forever)
        with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
            _capture(cmd_schedule_run, ["--forever", "--iterations", "2", "--loop-interval", "7", "--recipe", "demo"])
        self.assertEqual(called["dag_ids"], ["demo"])
        self.assertEqual(called["loop_interval"], 7)
        self.assertEqual(called["max_iterations"], 2)

    def test_schedule_main_help_and_missing_db(self):
        help_output = _capture(main, ["--help"])
        self.assertIn("train recipe schedule status", help_output)

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_output = _capture(cmd_schedule_status, ["--runtime-state", str(Path(tmpdir) / "missing")])
            self.assertIn("No runtime state found", missing_output)


class RecipeRuntimeViewTests(unittest.TestCase):
    def test_execution_details_logs_status_and_jobs_views(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "runtime"
            recipe_path = root / "demo.pyrecipe"
            recipe_path.write_text("from trainsh import Recipe\nrecipe = Recipe('demo')\n", encoding="utf-8")
            _seed_runtime_db(db_path, recipe_path)

            reader = ExecutionLogReader(str(db_path))
            manager = JobStateManager(str(db_path))
            job = manager.load("job12345")
            self.assertIsInstance(job, JobState)

            details_output = _capture(_show_execution_details, reader, "job12345")
            self.assertIn("Storages (1):", details_output)
            self.assertIn("Recent Events (5):", details_output)
            self.assertIn("step 1 success", details_output)

            with patch("trainsh.core.execution_log.ExecutionLogReader", side_effect=lambda *args, **kwargs: ExecutionLogReader(str(db_path))):
                logs_output = _capture(cmd_logs, [])
                self.assertIn("Recent executions:", logs_output)
                self.assertIn("1/1", logs_output)

                job_output = _capture(_show_job_details, job)
                self.assertIn("Storages:", job_output)
                self.assertIn("Recent Events:", job_output)

            with patch("trainsh.core.job_state.JobStateManager", return_value=manager):
                status_output = _capture(cmd_status, ["--all"])
                self.assertIn("Recipe Jobs:", status_output)
                self.assertIn("1/1", status_output)

                status_detail_output = _capture(cmd_status, ["job12345"])
                self.assertIn("Job ID: job12345", status_detail_output)
                self.assertIn("Storages:", status_detail_output)

                jobs_output = _capture(cmd_jobs, ["--all"])
                self.assertIn("Recipe Jobs:", jobs_output)
                self.assertIn("job12345", jobs_output)

            reader.close()

    def test_logs_and_status_empty_paths(self):
        class Reader:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def list_executions(self, limit=20):
                return []

            def get_execution_summary(self, job_id):
                return None

        reader = Reader()
        with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=reader):
            self.assertIn("No execution logs found.", _capture(cmd_logs, []))
            with self.assertRaises(SystemExit):
                _show_execution_details(reader, "missing")

        manager = SimpleNamespace(list_running=lambda: [], list_all=lambda limit=20: [], load=lambda job_id: None)
        with patch("trainsh.core.job_state.JobStateManager", return_value=manager):
            status_output = _capture(cmd_status, [])
            self.assertIn("No running recipe jobs.", status_output)
            jobs_output = _capture(cmd_jobs, [])
            self.assertIn("No job states found.", jobs_output)


if __name__ == "__main__":
    unittest.main()
