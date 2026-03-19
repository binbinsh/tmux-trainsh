import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.commands import schedule_cmd
from trainsh.core.runtime_store import RuntimeStore


def capture(fn, *args, **kwargs):
    import io
    from contextlib import redirect_stdout

    stream = io.StringIO()
    code = None
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code


class ScheduleCommandMoreTests(unittest.TestCase):
    def test_parse_eq_flags_and_help_dispatch_paths(self):
        parsed = schedule_cmd._parse_args(
            [
                "run",
                "--once",
                "--recipe=demo",
                "--recipes-dir=/tmp/recipes",
                "--runtime-state=/tmp/runtime",
                "--loop-interval=9",
                "--max-active-runs=2",
                "--max-active-runs-per-recipe=3",
                "--iterations=4",
                "--rows=6",
                "--help",
            ]
        )
        self.assertEqual(parsed["mode"], "help")
        self.assertTrue(parsed["once"])
        self.assertEqual(parsed["dag_ids"], ["demo"])
        self.assertEqual(parsed["dags_dir"], "/tmp/recipes")
        self.assertEqual(parsed["runtime_state"], "/tmp/runtime")
        self.assertEqual(parsed["loop_interval"], 9)
        self.assertEqual(parsed["max_active_runs"], 2)
        self.assertEqual(parsed["max_active_runs_per_dag"], 3)
        self.assertEqual(parsed["iterations"], 4)
        self.assertEqual(parsed["rows"], 6)

        out, code = capture(schedule_cmd.cmd_schedule_list, ["--help"])
        self.assertIsNone(code)
        self.assertIn("train recipe schedule", out)

        out, code = capture(schedule_cmd.cmd_schedule_status, ["--help"])
        self.assertIsNone(code)
        self.assertIn("train recipe schedule status", out)

        scheduler = SimpleNamespace(run_once=lambda **kwargs: [], run_forever=lambda **kwargs: None)
        with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
            out, code = capture(schedule_cmd.cmd_schedule_run, ["--help"])
        self.assertIsNone(code)
        self.assertIn("train recipe schedule", out)

        with patch("trainsh.commands.schedule_cmd.cmd_schedule_list") as mocked_list:
            schedule_cmd.cmd_schedule(["list", "--runtime-state", "/tmp/runtime"])
        mocked_list.assert_called_once_with(["--runtime-state", "/tmp/runtime"])

        with patch("trainsh.commands.schedule_cmd.cmd_schedule_status") as mocked_status:
            schedule_cmd.cmd_schedule(["status", "--rows", "5"])
        mocked_status.assert_called_once_with(["--rows", "5"])

        with patch("trainsh.commands.schedule_cmd.cmd_schedule_run") as mocked_run:
            schedule_cmd.cmd_schedule(["run", "--force"])
        mocked_run.assert_called_once_with(["--force"])

        with patch("trainsh.commands.schedule_cmd.cmd_schedule_run") as mocked_run:
            schedule_cmd.cmd_schedule(["demo-filter"])
        mocked_run.assert_called_once_with(["demo-filter"])

    def test_history_and_status_edge_rendering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "runtime"
            RuntimeStore(db).append_run(
                {
                    "run_id": "run-1",
                    "dag_id": "bad-path-\0",
                    "recipe_name": "bad-path-\0",
                    "recipe_path": "bad-path-\0",
                    "state": "success",
                    "status": "succeeded",
                    "run_type": "scheduled",
                    "execution_date": "now",
                    "started_at": "",
                    "ended_at": "",
                    "updated_at": "now",
                }
            )

            out, code = capture(schedule_cmd.cmd_schedule_status, ["--runtime-state", str(db), "--rows=1"])
            self.assertIsNone(code)
            self.assertIn("bad-path-\x00\trun-1\tsuccess\tscheduled\t-", out)

            dag = SimpleNamespace(recipe_name="demo", dag_id="/tmp/demo.pyrecipe", schedule=None, path="/tmp/demo.pyrecipe", is_valid=True, load_error=None)
            with patch("trainsh.commands.schedule_cmd.DagProcessor") as mocked_proc, patch(
                "trainsh.commands.schedule_cmd._latest_state_for_dag",
                return_value={"state": "", "run_id": "", "start_date": ""},
            ):
                mocked_proc.return_value.discover_dags.return_value = [dag]
                out, code = capture(schedule_cmd.cmd_schedule_list, ["--runtime-state", str(db)])
            self.assertIsNone(code)
            self.assertIn("demo\t-\t-\t-\t-\t/tmp/demo.pyrecipe", out)

            records = [SimpleNamespace(state="success", dag_id="/tmp/demo.pyrecipe", run_id="run-2", message="ok")]
            scheduler = SimpleNamespace(run_once=lambda **kwargs: records, run_forever=lambda **kwargs: None)
            with patch("trainsh.commands.schedule_cmd.DagScheduler", return_value=scheduler):
                out, code = capture(schedule_cmd.cmd_schedule_run, ["--wait"])
            self.assertIsNone(code)
            self.assertIn("success\tdemo\trun-2\tok", out)

        out, code = capture(schedule_cmd.main, ["help"])
        self.assertIsNone(code)
        self.assertIn("train recipe schedule", out)


if __name__ == "__main__":
    unittest.main()
