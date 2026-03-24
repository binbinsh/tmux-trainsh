import sqlite3
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.bridge_exec import BridgeExecutionHelper
from trainsh.core.dag_executor import DagExecutionResult
from trainsh.core.dag_processor import ParsedDag, parse_schedule
from trainsh.core.executor_execute import ExecuteHelper
from trainsh.core.executor_tmux import TmuxControlHelper
from trainsh.core.executor_wait import WaitHelper
from trainsh.core.local_tmux import TmuxCmdResult
from trainsh.core.scheduler import DagRunState, DagScheduler
from trainsh.core.tmux_session import TmuxSession, kill_session, list_sessions, session_exists


def ok(stdout="", stderr=""):
    return TmuxCmdResult(0, stdout, stderr)


class FakeTmuxClient:
    def __init__(self):
        self.sent = []
        self.wait_calls = []
        self.sessions = set()
        self.capture = ok("line1\nline2\nline3\n")
        self.display = ok("bash\n")
        self.panes = ["123"]
        self.wait = ok("")
        self.attach = "tmux attach"
        self.write = ok("")
        self.run_result = ok("")
        self.listed = []

    def build_attach_command(self, session, nested=False, status_mode="keep"):
        return f"attach {session} {nested} {status_mode}"

    def send_keys(self, target, text, enter=True, literal=True):
        self.sent.append((target, text, enter, literal))
        return ok("")

    def capture_pane(self, target, start=None):
        return self.capture

    def display_message(self, target, template):
        return self.display

    def list_panes(self, target, fmt=None):
        return list(self.panes)

    def wait_for(self, signal, timeout=1):
        self.wait_calls.append((signal, timeout))
        return self.wait

    def has_session(self, name):
        return name in self.sessions

    def new_session(self, name, detached=True, window_name=None, command=None):
        self.sessions.add(name)
        return ok("")

    def kill_session(self, name):
        self.sessions.discard(name)
        return ok("")

    def list_sessions(self, fmt):
        return list(self.sessions)

    def write_text(self, path, content):
        self.listed.append((path, content))
        return self.write

    def run(self, *args, timeout=30):
        return self.run_result


class SchedulerTests(unittest.TestCase):
    def test_run_once_and_drain_futures(self):
        due = ParsedDag(
            dag_id="demo-dag",
            path=Path("/tmp/demo.py"),
            recipe_name="demo",
            is_python=True,
            schedule="@every 5m",
            schedule_meta=parse_schedule("@every 5m"),
        )
        disabled = ParsedDag(
            dag_id="disabled-dag",
            path=Path("/tmp/disabled.py"),
            recipe_name="disabled",
            is_python=True,
            schedule="@every 5m",
            schedule_meta=parse_schedule("@every 5m"),
            is_paused=True,
        )
        processor = SimpleNamespace(discover_dags=lambda: [due, disabled])
        executor = SimpleNamespace(run=lambda dag, **kwargs: DagExecutionResult(
            dag_id=dag.dag_id,
            run_id=kwargs["run_id"],
            recipe_path=str(dag.path),
            state="success",
            success=True,
            started_at=kwargs.get("started_at") or __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            ended_at=kwargs.get("started_at") or __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            message="ok",
        ))

        scheduler = DagScheduler(dag_processor=processor, dag_executor=executor, max_active_runs=2)
        future = Future()
        future.set_result(executor.run(due, run_id="job1"))
        scheduler._pool.submit = MagicMock(return_value=future)

        records = scheduler.run_once(wait=False)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].dag_id, "demo-dag")
        scheduler._drain_futures()
        self.assertEqual(records[0].state, DagRunState.SUCCESS)

        failed_future = Future()
        failed_future.set_exception(RuntimeError("boom"))
        record = SimpleNamespace(dag_id="demo-dag", state=DagRunState.RUNNING, future=failed_future, message="", ended_at=None)
        with scheduler._running_lock:
            scheduler._active = {failed_future: record}
        scheduler._drain_futures()
        self.assertEqual(record.state, DagRunState.ERROR)

    def test_due_and_db_helpers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE dag_run (dag_id TEXT, state TEXT, start_date TEXT)")
            conn.execute(
                "INSERT INTO dag_run VALUES (?, ?, ?)",
                ("demo-dag", "running", "2026-03-12T08:00:00+00:00"),
            )
            conn.commit()
            conn.close()

            dag = ParsedDag(
                dag_id="demo-dag",
                path=Path("/tmp/demo.py"),
                recipe_name="demo",
                is_python=True,
                schedule="@every 5m",
                schedule_meta=parse_schedule("@every 5m"),
            )
            from trainsh.core.runtime_store import RuntimeStore

            RuntimeStore(db_path).append_run(
                {
                    "run_id": "run-1",
                    "dag_id": "demo-dag",
                    "recipe_name": "demo",
                    "recipe_path": "/tmp/demo.pyrecipe",
                    "state": "running",
                    "status": "running",
                    "started_at": "2026-03-12T08:00:00+00:00",
                    "updated_at": "2026-03-12T08:00:00+00:00",
                }
            )
            scheduler = DagScheduler(dag_processor=SimpleNamespace(discover_dags=lambda: []), runtime_state=str(db_path))
            self.assertEqual(scheduler._count_db_running("demo-dag"), 1)
            self.assertIsNotNone(scheduler._latest_run_start("demo-dag"))
            self.assertTrue(scheduler._parse_time("2026-03-12T08:00:00+00:00"))
            self.assertIsNone(scheduler._parse_time("bad"))
            self.assertTrue(scheduler._matches_filter(dag, {"demo-dag"}))
            self.assertFalse(scheduler._matches_filter(dag, {"missing"}))
            self.assertFalse(scheduler._is_due(ParsedDag(
                dag_id="manual",
                path=Path("/tmp/manual.py"),
                recipe_name="manual",
                is_python=True,
                schedule=None,
                schedule_meta=parse_schedule(None),
            ), now=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))


class BridgeExecutionHelperTests(unittest.TestCase):
    def make_helper(self):
        tmux = FakeTmuxClient()
        bridge = SimpleNamespace(
            tmux=tmux,
            connect=lambda name, cmd: (True, f"connected {name}"),
            disconnect=lambda name: None,
            get_pane=lambda name: "%1",
        )
        remote = FakeTmuxClient()
        helper = BridgeExecutionHelper(
            tmux_bridge=bridge,
            prefer_bridge_exec=True,
            bridge_remote_status="keep",
            get_tmux_client=lambda host: remote,
            log=lambda msg: None,
            log_detail=lambda *args, **kwargs: None,
            format_duration=lambda seconds: f"{int(seconds)}s",
        )
        return helper, tmux, remote

    def test_attach_and_bridge_execution_paths(self):
        helper, tmux, remote = self.make_helper()
        self.assertEqual(helper.build_bridge_attach_command(SimpleNamespace(host="local", remote_session="sess")), "attach sess True keep")
        self.assertEqual(helper.build_bridge_attach_command(SimpleNamespace(host="gpu", remote_session="sess")), "attach sess False keep")
        self.assertEqual(helper.build_bridge_attach_command(SimpleNamespace(host="gpu", remote_session="")), "bash -l")
        helper.ensure_bridge_window(SimpleNamespace(name="main", host="gpu", remote_session="sess"))

        helper.tmux_bridge.connect = lambda name, cmd: (False, "skip")
        helper.ensure_bridge_window(SimpleNamespace(name="main", host="gpu", remote_session="sess"))

        with patch("time.sleep", return_value=None):
            with patch.object(helper, "_is_bridge_pane_idle", side_effect=[True, True, True]):
                ok_idle, msg = helper.wait_for_bridge_idle("main", "%1", 10)
        self.assertTrue(ok_idle)
        self.assertIn("confirmed", msg)

        tmux.capture = ok("marker0\n")
        with patch("time.sleep", return_value=None):
            found, code = helper._wait_bridge_marker("%1", "marker", 2)
        self.assertTrue(found)
        self.assertEqual(code, 0)

        tmux.capture = ok("marker0\n")
        found, code = helper._wait_bridge_marker("%1", "marker", None)
        self.assertTrue(found)
        self.assertEqual(code, 0)

        window = SimpleNamespace(name="main", host="gpu", remote_session="sess")
        result = helper.exec_via_bridge(window, "echo hi", timeout=10, background=True, start_time=0)
        self.assertEqual(result, (True, "Command sent (background via bridge)"))

        with patch.object(helper, "_wait_bridge_marker", return_value=(True, 0)), patch(
            "time.time", side_effect=[0, 1]
        ):
            result = helper.exec_via_bridge(window, "echo hi", timeout=10, background=False, start_time=0)
        self.assertEqual(result, (True, "Command completed (0s)"))

        with patch.object(helper, "_wait_bridge_marker", return_value=(False, None)):
            result = helper.exec_via_bridge(window, "echo hi", timeout=10, background=False, start_time=0)
        self.assertEqual(result, (False, "Command timed out after 10s"))

        with patch.object(helper, "_wait_bridge_marker", return_value=(True, 0)) as mocked_wait, patch(
            "time.time", side_effect=[0, 1]
        ):
            result = helper.exec_via_bridge(window, "echo hi", timeout=None, background=False, start_time=0)
        self.assertEqual(result, (True, "Command completed (0s)"))
        self.assertIsNone(mocked_wait.call_args.args[2])


class ExecuteHelperTests(unittest.TestCase):
    def make_helper(self):
        tmux = FakeTmuxClient()
        executor = SimpleNamespace(
            _interpolate=lambda text: text.replace("$NAME", "demo"),
            logger=SimpleNamespace(log_detail=lambda *a, **k: None, log_ssh=lambda *a, **k: None),
            _resolve_window=lambda name: None,
            _exec_via_bridge=lambda **kwargs: None,
            get_tmux_client=lambda host: tmux,
            is_resuming=False,
            _wait_for_idle=lambda window, timeout: (True, "idle"),
            ctx=SimpleNamespace(variables={}),
        )
        helper = ExecuteHelper(executor, build_ssh_args=lambda host, command=None, tty=False: ["ssh", host, command or ""], window_cls=SimpleNamespace)
        return helper, executor, tmux

    def test_execute_paths(self):
        helper, executor, tmux = self.make_helper()
        step = SimpleNamespace(host="main", commands="echo $NAME", background=False, timeout=5, capture_var="", capture_path="")
        ok_run, msg = helper.exec_execute(step)
        self.assertFalse(ok_run)
        self.assertIn("Unknown window", msg)

        executor._resolve_window = lambda name: SimpleNamespace(host="gpu", remote_session="sess")
        executor._exec_via_bridge = lambda **kwargs: (True, "bridge")
        self.assertEqual(helper.exec_execute(step), (True, "bridge"))

        executor._exec_via_bridge = lambda **kwargs: None
        step.background = True
        ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertIn("background", msg)

        step.background = False
        executor.is_resuming = True
        ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertEqual(msg, "idle")

        executor.is_resuming = False
        tmux.wait = ok("")
        ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertIn("Command completed", msg)
        tmux.wait = TmuxCmdResult(1, "", "")
        ok_run, msg = helper.exec_execute(step)
        self.assertFalse(ok_run)

        executor._resolve_window = lambda name: SimpleNamespace(host="local", remote_session="")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")):
            self.assertEqual(helper.exec_execute(step), (True, "ok"))
        with patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("cmd", 1)):
            ok_run, msg = helper.exec_execute(step)
        self.assertFalse(ok_run)
        self.assertIn("timed out", msg)

        executor._resolve_window = lambda name: SimpleNamespace(host="gpu", remote_session="")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")):
            self.assertEqual(helper.exec_execute(step), (True, "ok"))
        with patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired("cmd", 1)):
            ok_run, msg = helper.exec_execute(step)
        self.assertFalse(ok_run)
        self.assertIn("timed out", msg)

        helper.tmux_send_keys("gpu", "sess", "echo hi")
        tmux.wait = ok("")
        self.assertTrue(helper.tmux_wait_for_signal("gpu", "sig"))
        tmux.wait = MagicMock(side_effect=__import__("subprocess").TimeoutExpired("wait", 1))
        self.assertFalse(helper.tmux_wait_for_signal("gpu", "sig"))

    def test_execute_zero_timeout_disables_runtime_timeout(self):
        helper, executor, tmux = self.make_helper()
        step = SimpleNamespace(host="main", commands="echo $NAME", background=False, timeout=0, capture_var="", capture_path="")

        bridge_calls = []
        executor._resolve_window = lambda name: SimpleNamespace(host="gpu", remote_session="sess")
        executor._exec_via_bridge = lambda **kwargs: bridge_calls.append(kwargs) or None
        tmux.wait = ok("")
        ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertIn("Command completed", msg)
        self.assertIsNone(bridge_calls[-1]["timeout"])
        self.assertIsNone(tmux.wait_calls[-1][1])

        resume_calls = []
        executor.is_resuming = True
        executor._wait_for_idle = lambda window, timeout: resume_calls.append(timeout) or (True, "idle")
        ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertEqual(msg, "idle")
        self.assertIsNone(resume_calls[-1])

        executor.is_resuming = False
        executor._resolve_window = lambda name: SimpleNamespace(host="local", remote_session="")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")) as mocked_run:
            self.assertEqual(helper.exec_execute(step), (True, "ok"))
        self.assertIsNone(mocked_run.call_args.kwargs["timeout"])

    def test_execute_capture_var_paths(self):
        helper, executor, tmux = self.make_helper()
        step = SimpleNamespace(
            host="main",
            commands="echo hi",
            background=False,
            timeout=5,
            capture_var="OUT",
            capture_path="/tmp/capture.txt",
        )

        executor._resolve_window = lambda name: SimpleNamespace(host="local", remote_session="")
        with tempfile.TemporaryDirectory() as tmpdir:
            capture_path = Path(tmpdir) / "capture.txt"
            capture_path.write_text("hello\n", encoding="utf-8")
            step.capture_path = str(capture_path)
            with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="hello\n", stderr="")):
                ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertEqual(executor.ctx.variables["OUT"], "hello")

        executor._resolve_window = lambda name: SimpleNamespace(host="gpu", remote_session="sess")
        tmux.wait = ok("")
        with patch.object(helper, "_read_captured_output", return_value="remote\n") as mocked_read, patch.object(
            helper,
            "_cleanup_captured_output",
        ) as mocked_cleanup:
            ok_run, msg = helper.exec_execute(step)
        self.assertTrue(ok_run)
        self.assertEqual(executor.ctx.variables["OUT"], "remote")
        mocked_read.assert_called_once_with("gpu", str(step.capture_path))
        mocked_cleanup.assert_called_once_with("gpu", str(step.capture_path))

        executor._resolve_window = lambda name: SimpleNamespace(host="gpu", remote_session="")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")), patch.object(
            helper,
            "_read_captured_output",
            return_value="ssh\n",
        ) as mocked_read, patch.object(helper, "_cleanup_captured_output") as mocked_cleanup:
            self.assertEqual(helper.exec_execute(step), (True, "ok"))
        mocked_read.assert_called_once_with("gpu", str(step.capture_path))
        mocked_cleanup.assert_called_once_with("gpu", str(step.capture_path))


class WaitHelperTests(unittest.TestCase):
    def make_helper(self):
        tmux = FakeTmuxClient()
        executor = SimpleNamespace(
            get_tmux_client=lambda host: tmux,
            logger=SimpleNamespace(log_detail=lambda *a, **k: None, log_ssh=lambda *a, **k: None, log_wait=lambda *a, **k: None),
            _resolve_window=lambda target: SimpleNamespace(name=target, host="local", remote_session="sess"),
            _interpolate=lambda text: text,
            log=lambda msg: None,
            ssh_max_retries=2,
            ssh_retry_base_interval=1,
            ssh_retry_max_interval=2,
            tmux_bridge=SimpleNamespace(get_pane=lambda name: None),
            _wait_for_bridge_idle=lambda name, pane, remaining: (True, "bridge idle"),
        )
        helper = WaitHelper(executor, build_ssh_args=lambda host, command=None, tty=False: ["ssh", host, command or ""], host_from_ssh_spec=lambda spec: SimpleNamespace(hostname="remote"), format_duration=lambda seconds: f"{int(seconds)}s")
        return helper, executor, tmux

    def test_wait_helper_paths(self):
        helper, executor, tmux = self.make_helper()
        self.assertEqual(helper.get_pane_recent_output("local", "sess", lines=2), "line2\nline3")

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="0\n")):
            self.assertTrue(helper.is_pane_idle("local", "sess"))
        tmux.display = TmuxCmdResult(1, "", "")
        self.assertFalse(helper.is_pane_idle("local", "sess"))

        tmux.display = ok("bash\n")
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="123 0 0 cmd\n")):
            current, tree = helper.get_pane_process_info("local", "sess")
        self.assertEqual(current, "bash")
        self.assertIn("cmd", tree)

        with patch("time.sleep", return_value=None), patch.object(helper, "is_pane_idle", side_effect=[True, True, True]):
            ok_wait, msg = helper.wait_for_idle(SimpleNamespace(name="main", host="local", remote_session="sess"), 5)
        self.assertTrue(ok_wait)
        self.assertIn("confirmed", msg)

        with patch("time.sleep", return_value=None), patch.object(helper, "is_pane_idle", side_effect=[True, True, True]):
            ok_wait, msg = helper.wait_for_idle(SimpleNamespace(name="main", host="local", remote_session="sess"), None)
        self.assertTrue(ok_wait)
        self.assertIn("confirmed", msg)

        executor._resolve_window = lambda target: None
        ok_wait, msg = helper.exec_wait(SimpleNamespace(target="missing", pattern="", condition="", timeout=5))
        self.assertFalse(ok_wait)
        self.assertIn("Unknown window", msg)

        executor._resolve_window = lambda target: SimpleNamespace(name=target, host="local", remote_session="sess")
        tmux.capture = ok("training complete\n")
        ok_wait, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="training", condition="", timeout=5))
        self.assertTrue(ok_wait)

        ok_wait, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="[", condition="", timeout=5))
        self.assertFalse(ok_wait)
        self.assertIn("Invalid wait pattern", msg)

        with patch("os.path.exists", return_value=True):
            ok_wait, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="file:/tmp/ready", timeout=5))
        self.assertTrue(ok_wait)

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
            ok_wait, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="port:8080", timeout=5))
        self.assertTrue(ok_wait)

        executor.tmux_bridge.get_pane = lambda name: "%1"
        ok_wait, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="idle", timeout=5))
        self.assertTrue(ok_wait)


class TmuxControlAndSessionTests(unittest.TestCase):
    def make_executor(self):
        local = FakeTmuxClient()
        remote = FakeTmuxClient()
        executor = SimpleNamespace(
            _resolve_host=lambda ref: "local" if ref == "@local" else "gpu",
            allocate_window_session_name=lambda: "train_demo_0",
            logger=SimpleNamespace(log_detail=lambda *a, **k: None),
            local_tmux=local,
            ctx=SimpleNamespace(windows={}),
            log=lambda msg: None,
            _ensure_bridge_window=lambda window: None,
            get_tmux_client=lambda host: remote,
            tmux_bridge=SimpleNamespace(disconnect=lambda name: None),
        )
        return executor, local, remote

    def test_tmux_control_helper_paths(self):
        executor, local, remote = self.make_executor()
        helper = TmuxControlHelper(executor, SimpleNamespace)
        self.assertEqual(helper.cmd_tmux_open([]), (False, "Usage: tmux.open @host as name"))
        ok_open, msg = helper.cmd_tmux_open(["@local", "as", "main"])
        self.assertTrue(ok_open)
        self.assertIn("Created local", msg)
        ok_open, msg = helper.cmd_tmux_open(["@gpu", "as", "remote"])
        self.assertTrue(ok_open)
        self.assertIn("Created remote", msg)

        self.assertEqual(helper.cmd_tmux_close([]), (False, "Usage: tmux.close @session"))
        self.assertEqual(helper.cmd_tmux_close(["main"]), (False, "Usage: tmux.close @session"))
        ok_close, _ = helper.cmd_tmux_close(["@main"])
        self.assertTrue(ok_close)
        ok_close, _ = helper.cmd_tmux_close(["@remote"])
        self.assertTrue(ok_close)
        self.assertEqual(helper.cmd_tmux_close(["@missing"])[0], False)

        self.assertEqual(helper.cmd_tmux_config([]), (False, "Usage: tmux.config @host"))
        with tempfile.TemporaryDirectory() as tmpdir, patch("trainsh.core.executor_tmux.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}), patch(
            "os.path.expanduser", return_value=str(Path(tmpdir) / ".tmux.conf")
        ):
            ok_cfg, msg = helper.cmd_tmux_config(["@local"])
        self.assertTrue(ok_cfg)
        self.assertIn("Applied tmux config to local", msg)

    def test_tmux_session_and_convenience_functions(self):
        fake_tmux = FakeTmuxClient()
        def run_side_effect(*args, timeout=30):
            if args and args[0] in {"new-window", "split-window"}:
                return ok("%1")
            if args and args[0] == "capture-pane":
                return ok("done\n")
            if args and args[0] == "list-panes":
                return ok("%0:@1:main:0:1:0:123:bash\n")
            return ok("")
        fake_tmux.run = MagicMock(side_effect=run_side_effect)
        fake_tmux.capture = ok("done\n")
        fake_tmux.sessions.add("demo")

        with patch("trainsh.core.tmux_session.LocalTmuxClient", return_value=fake_tmux):
            session = TmuxSession("demo", create=True)
            self.assertTrue(session.exists)
            pane_id = session.create_pane("main", command="bash -l")
            self.assertTrue(pane_id)
            pane_id2 = session.create_pane("gpu", ssh_host="root@example -p 22")
            self.assertTrue(pane_id2)
            self.assertTrue(session.send_keys("main", "echo hi"))
            self.assertTrue(session.run_command("main", "echo hi", timeout=1, signal="sig"))
            self.assertTrue(session.run_background("main", "sleep 1"))
            self.assertEqual(session.capture("main", start=-10), "done\n")
            with patch("time.sleep", return_value=None):
                self.assertTrue(session.wait_for_pattern("main", "done", timeout=1, poll_interval=0))
            self.assertEqual(session.attach_command(), "tmux attach -t demo")
            self.assertTrue(session.select_pane("main"))
            self.assertTrue(session.rm())

            panes = session.list_panes()
            self.assertEqual(panes[0].pane_id, "%0")

            self.assertTrue(session_exists("demo"))
            self.assertEqual(list_sessions(), ["demo"])
            self.assertTrue(kill_session("demo"))


if __name__ == "__main__":
    unittest.main()
