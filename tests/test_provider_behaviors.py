import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from trainsh.core.models import Storage, StorageType
from trainsh.core.recipe_models import RecipeModel

from tests.runtime_test_utils import isolated_executor


class _EchoJsonHandler(BaseHTTPRequestHandler):
    last_method = ""
    last_headers = {}
    last_body = ""

    def do_GET(self):  # noqa: N802
        self._handle()

    def do_POST(self):  # noqa: N802
        self._handle()

    def _handle(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8") if length else ""
        type(self).last_method = self.command
        type(self).last_headers = dict(self.headers.items())
        type(self).last_body = body
        payload = {"ok": True, "method": self.command, "body": body}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A003
        return


class ProviderBehaviorTests(unittest.TestCase):
    def _storage_recipe(self, root: Path) -> RecipeModel:
        return RecipeModel(
            name="provider-demo",
            storages={
                "artifacts": Storage(
                    id="artifacts",
                    name="artifacts",
                    type=StorageType.LOCAL,
                    config={"path": str(root)},
                )
            },
        )

    def test_sqlite_query_modes_bindings_and_output_vars(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "demo.db"
            with isolated_executor(RecipeModel(name="sqlite-demo")) as (executor, _config_dir):
                ok, _ = executor._exec_provider_sqlite_script(
                    {
                        "database": str(db),
                        "script": """
                        CREATE TABLE items (name TEXT, qty INTEGER);
                        INSERT INTO items(name, qty) VALUES ('alpha', 1);
                        INSERT INTO items(name, qty) VALUES ('beta', 2);
                        """,
                    }
                )
                self.assertTrue(ok)

                ok, _ = executor._exec_provider_sqlite_exec(
                    {
                        "database": str(db),
                        "sql": "INSERT INTO items(name, qty) VALUES (?, ?)",
                        "params": '["gamma", 3]',
                        "output_var": "ROWCOUNT",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["ROWCOUNT"], "1")

                ok, all_rows = executor._exec_provider_sqlite_query(
                    {
                        "database": str(db),
                        "sql": "SELECT name, qty FROM items WHERE qty >= ? ORDER BY qty",
                        "params": "[2]",
                        "mode": "all",
                        "output_var": "ROWS",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(
                    json.loads(all_rows),
                    [{"name": "beta", "qty": 2}, {"name": "gamma", "qty": 3}],
                )
                self.assertEqual(json.loads(executor.ctx.variables["ROWS"])[0]["name"], "beta")

                ok, first_row = executor._exec_provider_sqlite_query(
                    {
                        "database": str(db),
                        "sql": "SELECT name, qty FROM items ORDER BY qty",
                        "mode": "one",
                        "output_var": "FIRST",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(json.loads(first_row), {"name": "alpha", "qty": 1})
                self.assertEqual(json.loads(executor.ctx.variables["FIRST"])["qty"], 1)

                ok, scalar = executor._exec_provider_sqlite_query(
                    {
                        "database": str(db),
                        "sql": "SELECT COUNT(*) FROM items",
                        "mode": "value",
                        "output_var": "COUNT",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(scalar, "3")
                self.assertEqual(executor.ctx.variables["COUNT"], "3")

    def test_xcom_push_pull_decode_json_and_prior_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "xcom.db"
            with isolated_executor(RecipeModel(name="xcom-demo")) as (executor, _config_dir):
                executor.ctx.job_id = "run-current"
                ok, _ = executor._exec_provider_xcom_push(
                    {
                        "database": str(db),
                        "task_id": "producer",
                        "key": "payload",
                        "value": {"items": [1, 2]},
                    }
                )
                self.assertTrue(ok)

                ok, pulled = executor._exec_provider_xcom_pull(
                    {
                        "database": str(db),
                        "task_ids": ["producer"],
                        "key": "payload",
                        "decode_json": True,
                        "output_var": "CURRENT_PAYLOAD",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(json.loads(pulled), {"items": [1, 2]})
                self.assertEqual(json.loads(executor.ctx.variables["CURRENT_PAYLOAD"])["items"], [1, 2])

                ok, _ = executor._exec_provider_xcom_push(
                    {
                        "database": str(db),
                        "task_id": "legacy_task",
                        "run_id": "run-legacy",
                        "key": "payload",
                        "value": {"items": [9]},
                    }
                )
                self.assertTrue(ok)
                executor.ctx.job_id = "run-missing"

                ok, missing = executor._exec_provider_xcom_pull(
                    {
                        "database": str(db),
                        "task_ids": ["legacy_task"],
                        "key": "payload",
                    }
                )
                self.assertTrue(ok)
                self.assertIn("not found", missing)

                ok, legacy = executor._exec_provider_xcom_pull(
                    {
                        "database": str(db),
                        "task_ids": ["legacy_task"],
                        "key": "payload",
                        "include_prior_dates": True,
                        "decode_json": True,
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(json.loads(legacy), {"items": [9]})

    def test_latest_only_checks_recipe_runs_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "runtime.db"
            with isolated_executor(RecipeModel(name="latest-demo")) as (executor, _config_dir):
                executor.ctx.job_id = "run-current"
                current_started_at = executor.ctx.start_time.isoformat()
                later = (executor.ctx.start_time + timedelta(seconds=5)).isoformat()

                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE recipe_runs (recipe_name TEXT, run_id TEXT, started_at TEXT)")
                    conn.execute(
                        "INSERT INTO recipe_runs(recipe_name, run_id, started_at) VALUES (?, ?, ?)",
                        ("latest-demo", "run-newer", later),
                    )
                    conn.commit()

                ok, message = executor._exec_provider_latest_only(
                    {"sqlite_db": str(db), "message": "skip newer"}
                )

        self.assertFalse(ok)
        self.assertEqual(message, "skip newer")

    def test_latest_only_falls_back_to_dag_run_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db = Path(tmpdir) / "runtime.db"
            with isolated_executor(RecipeModel(name="latest-demo")) as (executor, _config_dir):
                executor.ctx.job_id = "run-current"
                current_started_at = executor.ctx.start_time.isoformat()
                later = (executor.ctx.start_time + timedelta(seconds=5)).isoformat()

                with sqlite3.connect(db) as conn:
                    conn.execute("CREATE TABLE dag_run (dag_id TEXT, run_id TEXT, start_date TEXT)")
                    conn.execute(
                        "INSERT INTO dag_run(dag_id, run_id, start_date) VALUES (?, ?, ?)",
                        ("latest-demo", "run-newer", later),
                    )
                    conn.commit()

                ok, message = executor._exec_provider_latest_only(
                    {"sqlite_db": str(db), "message": "skip dag newer"}
                )

        self.assertFalse(ok)
        self.assertEqual(message, "skip dag newer")

    def test_storage_local_operations_cover_list_info_read_mkdir_rename_delete_and_wait(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "storage"
            root.mkdir(parents=True, exist_ok=True)
            (root / "hello.txt").write_text("hello world", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "a.txt").write_text("nested", encoding="utf-8")

            with isolated_executor(self._storage_recipe(root)) as (executor, _config_dir):
                ok, listed = executor._exec_provider_storage_list(
                    {"storage": "artifacts", "path": "/", "recursive": True}
                )
                self.assertTrue(ok)
                self.assertIn("hello.txt", listed)
                self.assertIn("nested/a.txt", listed)

                ok, info = executor._exec_provider_storage_info(
                    {"storage": "artifacts", "path": "/hello.txt"}
                )
                self.assertTrue(ok)
                self.assertEqual(json.loads(info)["is_dir"], False)

                ok, content = executor._exec_provider_storage_read_text(
                    {"storage": "artifacts", "path": "/hello.txt", "max_chars": 5}
                )
                self.assertTrue(ok)
                self.assertEqual(content, "hello")

                ok, _ = executor._exec_provider_storage_mkdir(
                    {"storage": "artifacts", "path": "/newdir"}
                )
                self.assertTrue(ok)
                self.assertTrue((root / "newdir").is_dir())

                ok, _ = executor._exec_provider_storage_rename(
                    {"storage": "artifacts", "source": "/hello.txt", "destination": "/renamed.txt"}
                )
                self.assertTrue(ok)
                self.assertTrue((root / "renamed.txt").exists())

                with patch("trainsh.core.executor_main.time.sleep", side_effect=lambda *_args, **_kwargs: None):
                    ok, wait_msg = executor._exec_provider_storage_wait(
                        {"storage": "artifacts", "path": "/renamed.txt", "timeout": 1, "poll_interval": 1}
                    )
                self.assertTrue(ok)
                self.assertIn("exists", wait_msg)

                ok, _ = executor._exec_provider_storage_delete(
                    {"storage": "artifacts", "path": "/nested", "recursive": True}
                )
                self.assertTrue(ok)
                self.assertFalse((root / "nested").exists())

    def test_http_request_and_wait_capture_response(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _EchoJsonHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/echo"

        try:
            with isolated_executor(RecipeModel(name="http-demo")) as (executor, _config_dir):
                ok, body = executor._exec_provider_http_request(
                    {
                        "method": "POST",
                        "url": url,
                        "headers": {"X-Test": "yes"},
                        "body": {"hello": "world"},
                        "capture_var": "HTTP_BODY",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(json.loads(body)["ok"], True)
                self.assertEqual(_EchoJsonHandler.last_method, "POST")
                self.assertIn("application/json", _EchoJsonHandler.last_headers.get("Content-Type", ""))
                self.assertIn('"hello": "world"', _EchoJsonHandler.last_body)
                self.assertEqual(json.loads(executor.ctx.variables["HTTP_BODY"])["method"], "POST")

                ok, wait_msg = executor._exec_provider_http_wait(
                    {
                        "url": url,
                        "expected_status": 200,
                        "expected_text": '"ok": true',
                        "capture_var": "HTTP_WAIT_BODY",
                        "timeout": 2,
                        "poll_interval": 1,
                    }
                )
                self.assertTrue(ok)
                self.assertIn("matched", wait_msg)
                self.assertEqual(json.loads(executor.ctx.variables["HTTP_WAIT_BODY"])["ok"], True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_wait_condition_wait_file_and_wait_port_local_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ready = Path(tmpdir) / "ready.txt"
            ready.write_text("ok", encoding="utf-8")
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]

            with isolated_executor(RecipeModel(name="wait-demo")) as (executor, _config_dir):
                with patch.object(
                    executor,
                    "_eval_condition",
                    side_effect=[(False, "no"), (True, "matched")],
                ), patch("trainsh.core.executor_main.time.sleep", side_effect=lambda *_args, **_kwargs: None):
                    ok, message = executor._exec_provider_wait_condition(
                        {
                            "condition": "var:READY==1",
                            "capture": True,
                            "timeout": 2,
                            "poll_interval": 1,
                        }
                    )
                self.assertTrue(ok)
                self.assertEqual(message, "matched")

                ok, message = executor._exec_provider_wait_for_file(
                    {"path": str(ready), "timeout": 1, "poll_interval": 1}
                )
                self.assertTrue(ok)
                self.assertIn("File found", message)

                ok, message = executor._exec_provider_wait_for_port(
                    {"port": port, "host_name": "127.0.0.1", "timeout": 1, "poll_interval": 1}
                )
                self.assertTrue(ok)
                self.assertIn("Port", message)

            listener.close()

    def test_get_value_assert_notice_and_transfer_behavior(self):
        with isolated_executor(RecipeModel(name="utility-demo")) as (executor, _config_dir):
            executor.ctx.variables["LOCAL_TOKEN"] = "abc123"
            with patch.dict(os.environ, {"TRAINSH_TEST_ENV": "env-value"}, clear=False), patch.object(
                executor.secrets,
                "get",
                return_value="secret-value",
            ), patch.object(
                executor,
                "_exec_provider_shell",
                return_value=(True, "cmd-value\n"),
            ) as shell_mock, patch.object(
                executor.notifier,
                "notify",
                return_value=(True, "via log"),
            ) as notify_mock, patch.object(
                executor.transfer_helper,
                "transfer",
                return_value=(True, "transferred"),
            ) as transfer_mock:
                self.assertTrue(
                    executor._exec_provider_get_value(
                        {"target": "FROM_ENV", "source": "env:TRAINSH_TEST_ENV"}
                    )[0]
                )
                self.assertTrue(
                    executor._exec_provider_get_value(
                        {"target": "FROM_SECRET", "source": "secret:demo"}
                    )[0]
                )
                self.assertTrue(
                    executor._exec_provider_get_value(
                        {"target": "FROM_VAR", "source": "var:LOCAL_TOKEN"}
                    )[0]
                )
                self.assertTrue(
                    executor._exec_provider_get_value(
                        {"target": "FROM_CMD", "source": "command:echo value"}
                    )[0]
                )

                ok, _ = executor._exec_provider_assert({"condition": "var:FROM_ENV==env-value"})
                self.assertTrue(ok)

                ok, summary = executor._exec_provider_notice(
                    {
                        "body": "hello",
                        "subject": "Train",
                        "channels": ["log"],
                        "timeout": 5,
                        "command": "echo ok",
                    }
                )
                self.assertTrue(ok)
                self.assertEqual(summary, "via log")
                notify_kwargs = notify_mock.call_args.kwargs
                self.assertEqual(notify_kwargs["title"], "Train")
                self.assertEqual(notify_kwargs["message"], "hello")
                self.assertEqual(notify_kwargs["timeout_secs"], 5)

                ok, transfer_summary = executor._exec_provider_transfer(
                    {"source": "/tmp/a", "destination": "/tmp/b", "operation": "move"}
                )
                self.assertTrue(ok)
                self.assertEqual(transfer_summary, "transferred")
                transfer_mock.assert_called_once_with(
                    "/tmp/a",
                    "/tmp/b",
                    delete=True,
                    exclude=[],
                    operation="sync",
                )

        self.assertEqual(executor.ctx.variables["FROM_ENV"], "env-value")
        self.assertEqual(executor.ctx.variables["FROM_SECRET"], "secret-value")
        self.assertEqual(executor.ctx.variables["FROM_VAR"], "abc123")
        self.assertEqual(executor.ctx.variables["FROM_CMD"], "cmd-value")
        self.assertEqual(shell_mock.call_args.args[0]["command"], "echo value")


if __name__ == "__main__":
    unittest.main()
