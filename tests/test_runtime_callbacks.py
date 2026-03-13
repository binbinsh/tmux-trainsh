import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.runtime import (
    CallbackEvent,
    CallbackManager,
    ConsoleCallbackSink,
    SqliteCallbackSink,
    _sink_factory,
    build_sinks,
)


class RuntimeCallbackTests(unittest.TestCase):
    def test_callback_manager_console_and_factories(self):
        messages = []
        manager = CallbackManager()
        sink = SimpleNamespace(send=lambda event: messages.append(event.event))
        manager.add(sink)
        manager.emit(CallbackEvent(event="execution_start", run_id="r1", recipe_name="demo", recipe_path="/tmp/demo.py"))
        self.assertEqual(messages, ["execution_start"])

        manager = CallbackManager([SimpleNamespace(send=lambda event: (_ for _ in ()).throw(RuntimeError("boom")))])
        with patch("builtins.print") as mocked_print:
            manager.emit(CallbackEvent(event="execution_end", run_id="r1", recipe_name="demo", recipe_path="/tmp/demo.py"))
        mocked_print.assert_called()

        lines = []
        console = ConsoleCallbackSink(log_callback=lambda line: lines.append(line))
        console.send(CallbackEvent(event="execution_start", run_id="r1", recipe_name="demo", recipe_path="/tmp/demo.py"))
        console.send(CallbackEvent(event="step_start", run_id="r1", recipe_name="demo", recipe_path="/tmp/demo.py", step_num=1, payload={"raw": "echo hi"}))
        console.send(CallbackEvent(event="step_end", run_id="r1", recipe_name="demo", recipe_path="/tmp/demo.py", step_num=1, payload={"success": False}))
        console.send(CallbackEvent(event="execution_end", run_id="r1", recipe_name="demo", recipe_path="/tmp/demo.py", payload={"success": True}))
        self.assertTrue(any("start recipe=demo" in line for line in lines))
        self.assertTrue(any("step start #1" in line for line in lines))
        self.assertTrue(any("FAIL" in line for line in lines))
        self.assertTrue(any("result=OK" in line for line in lines))

        self.assertIsInstance(_sink_factory("console"), ConsoleCallbackSink)
        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_sink = _sink_factory("sqlite", sqlite_db=str(Path(tmpdir) / "runtime.db"))
            self.assertIsInstance(sqlite_sink, SqliteCallbackSink)
        with self.assertRaises(ValueError):
            _sink_factory("missing")

        sinks = build_sinks(["console,sqlite"], sqlite_db=":memory:")
        self.assertEqual(len(sinks), 2)
        self.assertEqual(build_sinks([]), [])
        self.assertEqual(build_sinks(["", " , "]), [])

        closers = []
        manager = CallbackManager(
            [
                SimpleNamespace(close=lambda: closers.append("ok")),
                SimpleNamespace(close=lambda: (_ for _ in ()).throw(RuntimeError("boom"))),
            ]
        )
        with patch("builtins.print") as mocked_print:
            manager.close()
        self.assertEqual(closers, ["ok"])
        mocked_print.assert_called()

    def test_sqlite_callback_sink_helpers_and_send_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            sink = SqliteCallbackSink(str(db_path))

            self.assertTrue(sink._as_bool(True))
            self.assertTrue(sink._as_bool("yes"))
            self.assertFalse(sink._as_bool("off"))
            self.assertEqual(sink._coerce_dag_id("demo", "/tmp/demo.py"), "/tmp/demo.py")
            self.assertEqual(sink._coerce_dag_id("demo", ""), "demo")
            self.assertEqual(sink._coerce_dag_id("", ""), "unknown_dag")
            self.assertEqual(sink._coerce_text(None, "x"), "x")
            self.assertEqual(sink._coerce_text("  demo  "), "demo")
            self.assertEqual(sink._coerce_int("bad", default=7), 7)
            self.assertEqual(__import__("json").loads(sink._serialize({"a": 1})), {"a": 1})

            start = CallbackEvent(
                event="execution_start",
                run_id="r1",
                recipe_name="demo",
                recipe_path="/tmp/demo.py",
                payload={"run_type": "scheduled", "hosts": {"gpu": "local"}, "storages": {"artifacts": {"path": "/tmp/out"}}},
            )
            sink.send(start)

            sink.send(
                CallbackEvent(
                    event="step_start",
                    run_id="r1",
                    recipe_name="demo",
                    recipe_path="/tmp/demo.py",
                    step_num=1,
                    payload={"details": "bad", "operation": "echo", "host": "local", "pool": "default", "trigger_rule": "all_success", "try_number": "2"},
                )
            )
            sink.send(
                CallbackEvent(
                    event="step_end",
                    run_id="r1",
                    recipe_name="demo",
                    recipe_path="/tmp/demo.py",
                    step_num=1,
                    payload={"success": False, "state": "weird", "error": {"boom": True}, "try_number": "3"},
                )
            )
            sink.send(
                CallbackEvent(
                    event="xcom_push",
                    run_id="r1",
                    recipe_name="demo",
                    recipe_path="/tmp/demo.py",
                    payload={"task_id": "", "key": "rows", "value": "1", "map_index": "2", "execution_date": ""},
                )
            )
            sink.send(
                CallbackEvent(
                    event="xcom_push",
                    run_id="r1",
                    recipe_name="demo",
                    recipe_path="/tmp/demo.py",
                    payload={"task_id": "task", "key": "", "value": "1"},
                )
            )
            sink.send(
                CallbackEvent(
                    event="execution_end",
                    run_id="r1",
                    recipe_name="demo",
                    recipe_path="/tmp/demo.py",
                    payload={"success": False, "duration_ms": 15},
                )
            )

            with closing(sqlite3.connect(db_path)) as conn:
                dag_run = conn.execute("SELECT state FROM dag_run WHERE run_id='r1'").fetchone()
                self.assertEqual(dag_run[0], "failed")
                ti = conn.execute("SELECT state, try_number FROM task_instance WHERE run_id='r1'").fetchone()
                self.assertEqual(ti[0], "failed")
                self.assertEqual(ti[1], 3)
                xcom = conn.execute("SELECT COUNT(1) FROM xcom WHERE key='rows'").fetchone()
                self.assertEqual(xcom[0], 1)
                events = conn.execute("SELECT COUNT(1) FROM recipe_events WHERE run_id='r1'").fetchone()
                self.assertGreaterEqual(events[0], 4)

            sink.close()
            sink.send(start)
            sink.close()


if __name__ == "__main__":
    unittest.main()
