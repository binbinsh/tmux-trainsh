import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from trainsh.core.execution_log import ExecutionLogReader, ExecutionLogger
from trainsh.core.job_state import JobState, JobStateManager, check_remote_condition, generate_job_id
from trainsh.core.runtime_db import (
    connect_runtime_db,
    get_runtime_db_path,
    json_dumps,
    json_loads,
    load_run_hosts,
    load_run_storages,
    load_run_windows,
    replace_run_hosts,
    replace_run_storages,
    replace_run_windows,
    to_jsonable,
)
from trainsh.core.runtime_store import RuntimeStore


class RuntimeDbHelpersTests(unittest.TestCase):
    def test_json_helpers_and_runtime_db_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            resolved = get_runtime_db_path(db_path)
            self.assertEqual(resolved, db_path.with_suffix(""))
            self.assertTrue(resolved.exists())

        class CustomObject:
            def to_dict(self):
                return {"path": Path("/tmp/demo.txt")}

        class Stringy:
            def __str__(self):
                return "stringy"

        self.assertEqual(json_loads(None, {"fallback": True}), {"fallback": True})
        self.assertEqual(json_loads("", {"fallback": True}), {"fallback": True})
        self.assertEqual(json_loads("not-json", {"fallback": True}), {"fallback": True})
        self.assertEqual(to_jsonable(Path("/tmp/demo.txt")), "/tmp/demo.txt")
        self.assertEqual(to_jsonable(CustomObject()), {"path": "/tmp/demo.txt"})
        self.assertEqual(to_jsonable(Stringy()), "stringy")
        self.assertEqual(json_dumps({"obj": CustomObject()}), '{"obj": {"path": "/tmp/demo.txt"}}')

    def test_replace_and_load_run_bindings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = connect_runtime_db(Path(tmpdir) / "runtime.db")
            replace_run_hosts(conn, "run-1", {})
            replace_run_storages(conn, "run-1", {})
            replace_run_windows(conn, "run-1", {})

            replace_run_hosts(conn, "run-1", {"gpu": "ssh://demo", "": "ignored"})
            replace_run_storages(conn, "run-1", {"artifacts": {"path": Path("/tmp/out")}, "": "ignored"})
            replace_run_windows(
                conn,
                "run-1",
                {
                    "main": {"host": "local", "remote_session": "train_run_0"},
                    "": {"host": "ignored"},
                },
            )

            self.assertEqual(load_run_hosts(conn, "run-1")["gpu"], "ssh://demo")
            self.assertEqual(load_run_storages(conn, "run-1")["artifacts"]["path"], "/tmp/out")
            self.assertEqual(load_run_windows(conn, "run-1")["main"]["remote_session"], "train_run_0")


class JobStateManagerTests(unittest.TestCase):
    def _state(self, **overrides):
        data = {
            "job_id": "job-1",
            "recipe_path": "/tmp/demo.pyrecipe",
            "recipe_name": "demo",
            "current_step": 2,
            "total_steps": 5,
            "status": "running",
            "variables": {"MODEL": "tiny"},
            "hosts": {"gpu": "ssh://gpu"},
            "storages": {"artifacts": {"path": "/tmp/out"}},
            "window_sessions": {"gpu": "train_demo_0"},
            "next_window_index": 1,
            "tmux_session": "train_demo_0",
            "bridge_session": "bridge_demo",
            "vast_instance_id": "123",
            "vast_start_time": "2026-03-12T08:00:00",
            "error": "",
        }
        data.update(overrides)
        return JobState(**data)

    def test_save_load_delete_and_query_job_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = JobStateManager(str(Path(tmpdir) / "runtime"))

            self.assertIsNone(manager.load("missing"))

            state = self._state()
            manager.save(state)
            loaded = manager.load("job-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.hosts["gpu"], "ssh://gpu")
            self.assertEqual(loaded.storages["artifacts"]["path"], "/tmp/out")
            self.assertEqual(loaded.window_sessions["gpu"], "train_demo_0")

            by_recipe = manager.find_by_recipe("/tmp/demo.pyrecipe")
            self.assertIsNotNone(by_recipe)
            self.assertEqual(by_recipe.job_id, "job-1")

            resumable = manager.find_resumable("/tmp/demo.pyrecipe")
            self.assertIsNotNone(resumable)
            self.assertEqual(resumable.job_id, "job-1")

            manager.save(self._state(job_id="job-2", status="failed", current_step=4, updated_at="2026-03-12T09:00:00"))
            manager.save(self._state(job_id="job-3", status="completed", recipe_path="/tmp/other.pyrecipe"))

            all_jobs = manager.list_all(limit=10)
            self.assertEqual([job.job_id for job in all_jobs], ["job-3", "job-2", "job-1"])
            running_jobs = manager.list_running()
            self.assertEqual([job.job_id for job in running_jobs], ["job-1"])

            manager.delete("job-3")
            self.assertIsNone(manager.load("job-3"))

    def test_cleanup_old_and_resumable_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "runtime"
            manager = JobStateManager(str(root))
            manager.save(self._state(job_id="running-job", status="running"))
            manager.save(self._state(job_id="completed-job", status="completed", updated_at="2000-01-01T00:00:00"))
            manager.save(
                self._state(
                    job_id="cancelled-job",
                    status="cancelled",
                    recipe_path="/tmp/cancelled.pyrecipe",
                    updated_at="2000-01-01T00:00:00",
                )
            )

            store = RuntimeStore(root)
            updated = []
            for line in store.checkpoints_path.read_text(encoding="utf-8").splitlines():
                payload = json.loads(line)
                if payload.get("run_id") in {"completed-job", "cancelled-job"}:
                    payload["updated_at"] = "2000-01-01T00:00:00"
                updated.append(json.dumps(payload, ensure_ascii=False))
            store.checkpoints_path.write_text("\n".join(updated) + "\n", encoding="utf-8")

            cleaned = manager.cleanup_old(days=7)
            self.assertEqual(cleaned, 2)
            self.assertIsNotNone(manager.find_resumable("/tmp/demo.pyrecipe"))
            self.assertIsNone(manager.find_resumable("/tmp/cancelled.pyrecipe"))
            self.assertEqual(manager.cleanup_old(days=7), 0)

    def test_generate_job_id_and_remote_condition_checks(self):
        self.assertEqual(len(generate_job_id()), 8)

        with patch("subprocess.run") as mocked_run:
            mocked_run.return_value = type("Result", (), {"stdout": "EXISTS\n"})()
            ok, message = check_remote_condition("root@example -p 22", "file:/tmp/ready")
            self.assertTrue(ok)
            self.assertIn("Condition met", message)
            called = mocked_run.call_args.args[0]
            self.assertIn("-p", called)
            self.assertIn("22", called)

            mocked_run.return_value = type("Result", (), {"stdout": "NOTFOUND\n"})()
            ok, message = check_remote_condition("root@example", "file:/tmp/ready")
            self.assertFalse(ok)
            self.assertIn("Condition not met", message)

            mocked_run.side_effect = subprocess.TimeoutExpired("ssh", 30)
            ok, message = check_remote_condition("root@example", "file:/tmp/ready")
            self.assertFalse(ok)
            self.assertIn("SSH connection timeout", message)

            mocked_run.side_effect = TimeoutError()
            ok, message = check_remote_condition("root@example", "file:/tmp/ready")
            self.assertFalse(ok)
            self.assertIn("SSH error", message)

        with patch("subprocess.run", side_effect=Exception("boom")):
            ok, message = check_remote_condition("root@example", "file:/tmp/ready")
            self.assertFalse(ok)
            self.assertIn("SSH error", message)

        ok, message = check_remote_condition("root@example", "port:22")
        self.assertFalse(ok)
        self.assertIn("Unknown condition type", message)


class ExecutionLogTests(unittest.TestCase):
    def _seed_run(self, db_path: Path, *, run_id: str = "run-1"):
        store = RuntimeStore(db_path)
        store.append_run(
            {
                "run_id": run_id,
                "dag_id": "/tmp/demo.pyrecipe",
                "recipe_name": "demo",
                "recipe_path": "/tmp/demo.pyrecipe",
                "status": "succeeded",
                "state": "success",
                "started_at": "2026-03-12T08:00:00",
                "ended_at": "2026-03-12T08:01:00",
                "duration_ms": 60000,
                "success": True,
                "metadata": {},
                "updated_at": "2026-03-12T08:01:00",
                "hosts": {"gpu": "ssh://gpu"},
                "storages": {"artifacts": {"path": "/tmp/out"}},
            }
        )

    def test_execution_logger_and_reader_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime"
            self._seed_run(db_path)

            logger = ExecutionLogger("run-1", "demo", str(db_path))
            logger.start("demo", {"MODEL": "tiny"}, {"gpu": "ssh://gpu"}, "/tmp/demo.pyrecipe")
            logger.step_start(1, "echo hi", "execute", {})
            logger.step_end(1, True, 5, "ok", "")
            logger.log_detail("category", "message", {"ok": True})
            logger.log_ssh("gpu", "echo hi", 0, "out", "", 3)
            logger.log_tmux("open", "main", {"detached": True}, True, "opened")
            logger.log_vast("wait", 123, {"id": 1}, {"ready": True}, True)
            logger.log_transfer("/a", "/b", "copy", 12, 4, True, "done")
            logger.log_wait("main", "idle", 2, 3, "poll #1")
            logger.log_variable("MODEL", "tiny", "test")
            logger.step_output(1, "hello")
            logger.step_output(2, "x" * 60001)
            logger.end(True, 100, {"MODEL": "tiny"})
            logger._write("ignored", payload="ignored")

            reader = ExecutionLogReader(str(db_path))
            executions = reader.list_executions(limit=5)
            self.assertEqual(executions[0]["host_count"], 1)
            self.assertEqual(executions[0]["storage_count"], 1)

            full_log = reader.get_full_log("run-1")
            self.assertTrue(any(entry["event"] == "detail" for entry in full_log))
            self.assertTrue(any(entry["event"] == "step_output" for entry in full_log))

            self.assertEqual(reader.get_step_output("run-1", 1), "hello")
            self.assertEqual(reader.get_step_output("run-1", 2), "x" * 60001)

            summary = reader.get_execution_summary("run-1")
            self.assertEqual(summary["hosts"]["gpu"], "ssh://gpu")
            self.assertEqual(summary["storages"]["artifacts"]["path"], "/tmp/out")
            self.assertEqual(summary["recent_events"][-1]["event"], "variable_set")
            self.assertIsNone(reader.get_execution_summary("missing"))
            reader.close()

    def test_reader_handles_non_dict_payloads_and_event_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime"
            self._seed_run(db_path, run_id="run-2")
            store = RuntimeStore(db_path)
            store.append_event({"run_id": "run-2", "event": "execution_start", "event_name": "execution_start", "step_num": None, "payload": {"variables": {"MODE": "dev"}}, "ts": "2026-03-12T08:00:00"})
            store.append_event({"run_id": "run-2", "event": "step_output", "event_name": "step_output", "step_num": 1, "payload": "plain-text", "ts": "2026-03-12T08:00:01"})
            store.append_event({"run_id": "run-2", "event": "wait_poll", "event_name": "wait_poll", "step_num": 1, "payload": {"status": "poll"}, "ts": "2026-03-12T08:00:02"})
            store.append_event({"run_id": "run-2", "event": "execution_end", "event_name": "execution_end", "step_num": None, "payload": {"final_variables": {"MODE": "prod"}}, "ts": "2026-03-12T08:00:03"})

            reader = ExecutionLogReader(str(db_path))
            entries = reader.read_execution("run-2")
            self.assertEqual(entries[1]["payload"], "plain-text")

            recent = reader.list_recent_events("run-2", limit=5)
            self.assertEqual([item["event"] for item in recent], ["execution_start", "execution_end"])

            summary = reader.get_execution_summary("run-2")
            self.assertEqual(summary["variables"], {"MODE": "prod"})
            reader.close()

    def test_logger_destructor_is_safe(self):
        logger = ExecutionLogger.__new__(ExecutionLogger)
        logger._closed = False
        logger.store = RuntimeStore(Path(tempfile.gettempdir()) / "runtime-store-safe")
        ExecutionLogger.__del__(logger)


if __name__ == "__main__":
    unittest.main()
