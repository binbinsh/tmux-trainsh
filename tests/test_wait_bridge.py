import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.bridge_exec import BridgeExecutionHelper
from trainsh.core.executor_wait import WaitHelper
from trainsh.core.local_tmux import TmuxCmdResult


class BridgeExecEdgeTests(unittest.TestCase):
    def _helper(self):
        tmux = SimpleNamespace(
            build_attach_command=MagicMock(return_value="local-attach"),
            send_keys=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            capture_pane=MagicMock(return_value=TmuxCmdResult(0, "line1\nline2\n", "")),
            display_message=MagicMock(return_value=TmuxCmdResult(0, "123\n", "")),
        )
        bridge = SimpleNamespace(
            tmux=tmux,
            connect=MagicMock(return_value=(True, "connected")),
            get_pane=MagicMock(return_value="%1"),
        )
        remote_client = SimpleNamespace(build_attach_command=MagicMock(return_value="remote-attach"))
        logs = []
        details = []
        helper = BridgeExecutionHelper(
            tmux_bridge=bridge,
            prefer_bridge_exec=True,
            bridge_remote_status="keep",
            get_tmux_client=lambda host: remote_client,
            log=lambda msg: logs.append(msg),
            log_detail=lambda event, message, data: details.append((event, message, data)),
            format_duration=lambda value: f"{int(value)}s",
        )
        return helper, bridge, tmux, remote_client, logs, details

    def test_attach_building_and_basic_helpers(self):
        helper, bridge, tmux, remote_client, logs, details = self._helper()
        self.assertEqual(helper.build_bridge_attach_command(SimpleNamespace(host="local", remote_session=None)), "bash -l")
        self.assertEqual(helper.build_bridge_attach_command(SimpleNamespace(host="local", remote_session="sess")), "local-attach")
        self.assertEqual(helper.build_bridge_attach_command(SimpleNamespace(host="gpu", remote_session="sess")), "remote-attach")
        remote_client.build_attach_command.assert_called_once_with("sess", status_mode="keep")

        helper.ensure_bridge_window(SimpleNamespace(name="main", host="local", remote_session="sess"))
        self.assertTrue(any("Bridge @main" in line for line in logs))
        bridge.connect.return_value = (False, "no bridge")
        helper.ensure_bridge_window(SimpleNamespace(name="gpu", host="gpu", remote_session="sess"))
        self.assertEqual(details[-1][0], "tmux_bridge_skip")

        helper.restore_tmux_bridge([SimpleNamespace(name="main", host="local", remote_session="sess")])
        self.assertGreaterEqual(bridge.connect.call_count, 3)

        helper._tmux_send_keys_local_target("%1", "echo hi")
        tmux.send_keys.assert_called_with("%1", "echo hi", enter=True, literal=True)
        self.assertEqual(helper._get_bridge_pane_recent_output("%1"), "line1\nline2")
        tmux.capture_pane.return_value = TmuxCmdResult(1, "", "err")
        self.assertEqual(helper._get_bridge_pane_recent_output("%1"), "")
        self.assertEqual(helper._get_local_pane_pid("%1"), "123")
        tmux.display_message.return_value = TmuxCmdResult(1, "", "err")
        self.assertEqual(helper._get_local_pane_pid("%1"), "")

    def test_idle_checks_marker_wait_and_exec_paths(self):
        helper, bridge, tmux, remote_client, logs, details = self._helper()

        tmux.display_message.return_value = TmuxCmdResult(0, "python\n", "")
        self.assertFalse(helper._is_bridge_pane_idle("%1"))
        tmux.display_message.return_value = TmuxCmdResult(0, "bash\n", "")
        with patch("trainsh.core.bridge_exec.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="0\n")):
            self.assertTrue(helper._is_bridge_pane_idle("%1"))
        with patch("trainsh.core.bridge_exec.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="2\n")):
            self.assertFalse(helper._is_bridge_pane_idle("%1"))
        with patch("trainsh.core.bridge_exec.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="bad")):
            self.assertFalse(helper._is_bridge_pane_idle("%1"))

        tmux.display_message.return_value = TmuxCmdResult(0, "bash\n", "")
        with patch("trainsh.core.bridge_exec.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="tree\n")):
            current, tree = helper._get_bridge_pane_process_info("%1")
        self.assertEqual(current, "bash")
        self.assertEqual(tree, "tree")

        helper._is_bridge_pane_idle = MagicMock(side_effect=[True, True, True])
        with patch("trainsh.core.bridge_exec.time.sleep"):
            ok, msg = helper.wait_for_bridge_idle("main", "%1", 5)
        self.assertTrue(ok)
        self.assertIn("confirmed", msg)

        helper._is_bridge_pane_idle = MagicMock(side_effect=RuntimeError("boom"))
        helper._get_bridge_pane_process_info = MagicMock(return_value=("bash", "pid"))
        helper._get_bridge_pane_recent_output = MagicMock(return_value="out")
        with patch("trainsh.core.bridge_exec.time.time", side_effect=[0, 0, 40, 40]), patch(
            "trainsh.core.bridge_exec.time.sleep"
        ):
            ok, msg = helper.wait_for_bridge_idle("main", "%1", 5)
        self.assertFalse(ok)
        self.assertIn("Timeout", msg)

        tmux.capture_pane.return_value = TmuxCmdResult(0, "__done__0\n", "")
        with patch("trainsh.core.bridge_exec.time.time", side_effect=[0, 0]):
            ok, code = helper._wait_bridge_marker("%1", "__done__", 5)
        self.assertTrue(ok)
        self.assertEqual(code, 0)

        bridge.get_pane.return_value = None
        self.assertIsNone(helper.exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, False, 0))
        bridge.get_pane.return_value = "%1"

        self.assertIsNone(
            BridgeExecutionHelper(
                tmux_bridge=bridge,
                prefer_bridge_exec=False,
                bridge_remote_status="keep",
                get_tmux_client=lambda host: remote_client,
                log=lambda _msg: None,
                log_detail=lambda *_a: None,
                format_duration=lambda value: f"{int(value)}s",
            ).exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, False, 0)
        )

        with patch.object(helper, "_tmux_send_keys_local_target") as mocked_send:
            ok, msg = helper.exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, True, 0)
        self.assertTrue(ok)
        mocked_send.assert_called_once()

        with patch.object(helper, "_tmux_send_keys_local_target"), patch.object(
            helper, "_wait_bridge_marker", return_value=(True, 0)
        ), patch("trainsh.core.bridge_exec.time.time", side_effect=[0, 3]):
            ok, msg = helper.exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, False, 0)
        self.assertTrue(ok)
        self.assertIn("completed", msg)

        with patch.object(helper, "_tmux_send_keys_local_target"), patch.object(
            helper, "_wait_bridge_marker", return_value=(True, 2)
        ), patch("trainsh.core.bridge_exec.time.time", side_effect=[0, 3]):
            ok, msg = helper.exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, False, 0)
        self.assertFalse(ok)
        self.assertIn("exit code 2", msg)

        with patch.object(helper, "_tmux_send_keys_local_target"), patch.object(
            helper, "_wait_bridge_marker", return_value=(False, None)
        ), patch("trainsh.core.bridge_exec.time.time", side_effect=[0, 3]):
            ok, msg = helper.exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, False, 0)
        self.assertFalse(ok)
        self.assertIn("timed out", msg)

        with patch.object(helper, "_tmux_send_keys_local_target", side_effect=RuntimeError("boom")):
            self.assertIsNone(helper.exec_via_bridge(SimpleNamespace(name="main", remote_session="sess"), "echo hi", 5, False, 0))
        self.assertEqual(details[-1][0], "bridge_exec_error")


class WaitHelperEdgeTests(unittest.TestCase):
    def _helper(self):
        tmux = SimpleNamespace(
            run_line=MagicMock(return_value="run"),
            capture_pane=MagicMock(return_value=TmuxCmdResult(0, "a\nb\n", "")),
            display_message=MagicMock(return_value=TmuxCmdResult(0, "bash\n", "")),
            list_panes=MagicMock(return_value=["321"]),
        )
        executor = SimpleNamespace(
            get_tmux_client=lambda host: tmux,
            log=MagicMock(),
            logger=SimpleNamespace(log_detail=MagicMock(), log_wait=MagicMock(), log_ssh=MagicMock()),
            ssh_max_retries=2,
            ssh_retry_base_interval=1,
            ssh_retry_max_interval=2,
            _resolve_window=MagicMock(),
            _interpolate=lambda text: text,
            tmux_bridge=SimpleNamespace(get_pane=MagicMock(return_value="%1")),
            _wait_for_bridge_idle=MagicMock(return_value=(True, "bridge-idle")),
        )
        helper = WaitHelper(
            executor=executor,
            build_ssh_args=lambda host, command, tty=False: ["ssh", host, command],
            host_from_ssh_spec=lambda host: SimpleNamespace(hostname="remote-host"),
            format_duration=lambda value: f"{int(value)}s",
        )
        return helper, executor, tmux

    def test_wait_helper_basics_and_exec_wait_paths(self):
        helper, executor, tmux = self._helper()
        with patch("trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")) as mocked_run:
            result = helper._run_remote_shell("gpu", "echo hi", timeout=7)
        self.assertEqual(result.stdout, "ok")
        mocked_run.assert_called_once()
        self.assertEqual(helper.run_tmux_cmd("local", "list-sessions"), "run")

        self.assertEqual(helper.get_pane_recent_output("local", "sess"), "a\nb")
        tmux.capture_pane.return_value = TmuxCmdResult(1, "", "err")
        self.assertEqual(helper.get_pane_recent_output("local", "sess"), "")
        tmux.capture_pane.return_value = TmuxCmdResult(0, "a\nb\n", "")

        tmux.display_message.return_value = TmuxCmdResult(1, "", "err")
        self.assertFalse(helper.is_pane_idle("local", "sess"))
        tmux.display_message.return_value = TmuxCmdResult(0, "python\n", "")
        self.assertFalse(helper.is_pane_idle("local", "sess"))
        tmux.display_message.return_value = TmuxCmdResult(0, "bash\n", "")
        tmux.list_panes.return_value = [""]
        self.assertFalse(helper.is_pane_idle("local", "sess"))
        tmux.list_panes.return_value = ["321"]
        with patch("trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="0\n")):
            self.assertTrue(helper.is_pane_idle("local", "sess"))
        with patch("trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="1\n")):
            self.assertFalse(helper.is_pane_idle("local", "sess"))

        with patch("trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="tree\n")):
            current, tree = helper.get_pane_process_info("local", "sess")
        self.assertEqual(current, "bash")
        self.assertEqual(tree, "tree")
        tmux.display_message.return_value = TmuxCmdResult(1, "", "err")
        current, tree = helper.get_pane_process_info("local", "sess")
        self.assertEqual(current, "unknown")
        tmux.display_message.return_value = TmuxCmdResult(0, "bash\n", "")
        tmux.list_panes.return_value = [""]
        current, tree = helper.get_pane_process_info("local", "sess")
        self.assertEqual(tree, "")
        tmux.list_panes.return_value = ["321"]
        with patch.object(helper, "_run_remote_shell", return_value=SimpleNamespace(returncode=0, stdout="remote-tree\n")):
            current, tree = helper.get_pane_process_info("gpu", "sess")
        self.assertEqual(tree, "remote-tree")
        with patch.object(helper, "_run_remote_shell", return_value=SimpleNamespace(returncode=1, stdout="", stderr="")):
            current, tree = helper.get_pane_process_info("gpu", "sess")
        self.assertEqual(tree, "")

        window = SimpleNamespace(name="main", host="local", remote_session="sess")
        with patch("trainsh.core.executor_wait.time.sleep"), patch.object(
            helper, "is_pane_idle", side_effect=[True, True, True]
        ):
            ok, msg = helper.wait_for_idle(window, 5)
        self.assertTrue(ok)
        self.assertIn("confirmed", msg)

        with patch("trainsh.core.executor_wait.time.sleep"), patch.object(
            helper, "is_pane_idle", side_effect=RuntimeError("boom")
        ), patch.object(
            helper, "get_pane_process_info", return_value=("bash", "tree")
        ), patch.object(
            helper, "get_pane_recent_output", return_value="out"
        ), patch("trainsh.core.executor_wait.time.time", side_effect=[0, 0, 40, 40]):
            ok, msg = helper.wait_for_idle(window, 5)
        self.assertFalse(ok)
        self.assertIn("Timeout", msg)
        self.assertTrue(executor.log.called)

        executor._resolve_window.return_value = None
        ok, msg = helper.exec_wait(SimpleNamespace(target="missing", pattern="", condition="", timeout=5))
        self.assertFalse(ok)
        self.assertIn("Unknown window", msg)

        executor._resolve_window.return_value = window
        tmux.capture_pane.return_value = TmuxCmdResult(0, "training done\n", "")
        with patch("trainsh.core.executor_wait.time.sleep"):
            ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="done", condition="", timeout=5))
        self.assertTrue(ok)
        self.assertIn("Pattern found", msg)

        ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="(", condition="", timeout=5))
        self.assertFalse(ok)
        self.assertIn("Invalid wait pattern", msg)

        with patch("trainsh.core.executor_wait.os.path.exists", return_value=True):
            ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="file:/tmp/ready", timeout=5))
        self.assertTrue(ok)
        self.assertIn("File found", msg)

        executor.logger = None
        with patch("trainsh.core.executor_wait.os.path.exists", return_value=True):
            ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="file:/tmp/ready", timeout=5))
        self.assertTrue(ok)
        executor.logger = SimpleNamespace(log_detail=MagicMock(), log_wait=MagicMock(), log_ssh=MagicMock())

        window_remote = SimpleNamespace(name="gpu", host="gpu", remote_session="sess")
        executor._resolve_window.return_value = window_remote
        with patch(
            "trainsh.core.executor_wait.subprocess.run",
            side_effect=[
                OSError("ssh down"),
                OSError("ssh still down"),
                SimpleNamespace(returncode=0, stdout="exists\n", stderr=""),
            ],
        ), patch("trainsh.core.executor_wait.time.sleep"):
            ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="", condition="file:/tmp/ready", timeout=5))
        self.assertTrue(ok)
        self.assertIn("File found", msg)

        with patch("trainsh.core.executor_wait.subprocess.run", side_effect=OSError("ssh down")), patch(
            "trainsh.core.executor_wait.time.sleep"
        ), patch(
            "trainsh.core.executor_wait.time.time",
            side_effect=[0, 0, 0, 2, 2, 4, 4, 6, 6],
        ):
            ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="", condition="file:/tmp/ready", timeout=5))
        self.assertFalse(ok)
        self.assertIn("Timeout", msg)
        self.assertIn("last SSH error", msg)

        executor._resolve_window.return_value = window
        with patch("trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="port:8080", timeout=5))
        self.assertTrue(ok)
        self.assertIn("Port 8080 is open", msg)

        executor._resolve_window.return_value = window_remote
        with patch.object(helper, "host_from_ssh_spec", return_value=SimpleNamespace(hostname="remote")), patch(
            "trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0)
        ):
            ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="", condition="port:8080", timeout=5))
        self.assertTrue(ok)

        executor._resolve_window.return_value = window_remote
        ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="", condition="idle", timeout=5))
        self.assertTrue(ok)
        self.assertEqual(msg, "bridge-idle")

        executor.tmux_bridge.get_pane.return_value = None
        executor._resolve_window.return_value = window
        ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="idle", timeout=5))
        self.assertTrue(ok)
        self.assertIn("confirmed", msg)

        executor._resolve_window.return_value = SimpleNamespace(name="none", host="local", remote_session=None)
        ok, msg = helper.exec_wait(SimpleNamespace(target="none", pattern="", condition="idle", timeout=5))
        self.assertFalse(ok)
        self.assertIn("has no tmux session", msg)

        tmux.capture_pane.return_value = TmuxCmdResult(0, "", "")
        executor._resolve_window.return_value = window
        with patch("trainsh.core.executor_wait.time.time", side_effect=[0, 31]), patch("trainsh.core.executor_wait.time.sleep"):
            ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="", timeout=5))
        self.assertFalse(ok)
        self.assertIn("Timeout after", msg)


if __name__ == "__main__":
    unittest.main()
