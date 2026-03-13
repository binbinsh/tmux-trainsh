import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.commands import config_cmd, recipe
from trainsh.core.executor_tmux import TmuxControlHelper
from trainsh.core.local_tmux import TmuxCmdResult
from trainsh.core.provider_dispatch import ExecutorProviderDispatchMixin
from trainsh.core.provider_conditions import ExecutorProviderConditionsMixin
from trainsh.core.remote_tmux import RemoteTmuxClient
from trainsh.runtime_executors import (
    AirflowExecutor,
    CeleryExecutor,
    DaskExecutor,
    DebugExecutor,
    LocalExecutor,
    NoopExecutor,
    ProcessPoolExecutor,
    SequentialExecutor,
    ThreadPoolExecutor,
    _coerce_max_workers,
    get_executor,
    normalize_executor_name,
)
from trainsh.services.transfer_support import (
    TransferPlan,
    TransferProgress,
    analyze_transfer,
    build_rclone_env,
    check_rclone_available,
    check_rsync_available,
    get_rclone_remote_name,
    rsync_with_progress,
)
from trainsh.core.models import Host, HostType, AuthMethod, Storage, StorageType, TransferEndpoint


def capture(fn, *args, **kwargs):
    stream = io.StringIO()
    code = None
    result = None
    with redirect_stdout(stream):
        try:
            result = fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code, result


class RuntimeExecutorsTests(unittest.TestCase):
    def test_executor_helpers_and_resolution(self):
        self.assertEqual(normalize_executor_name("Thread Pool"), "threadpool")
        self.assertEqual(_coerce_max_workers({"parallelism": "8", "max_workers": 2}), 8)
        self.assertEqual(_coerce_max_workers({"workers": "bad"}, default=3), 3)

        self.assertIsInstance(get_executor("sequential"), SequentialExecutor)
        self.assertIsInstance(get_executor("debug"), DebugExecutor)
        self.assertIsInstance(get_executor("local"), AirflowExecutor)
        self.assertIsInstance(get_executor("celery"), CeleryExecutor)
        self.assertIsInstance(get_executor("dask"), DaskExecutor)
        self.assertIsInstance(get_executor("process_pool"), ProcessPoolExecutor)
        with self.assertRaises(ValueError):
            get_executor("kubernetes")
        with self.assertRaises(ValueError):
            get_executor("missing")

    def test_executor_classes_execute_paths(self):
        self.assertTrue(SequentialExecutor().execute(lambda: True))
        self.assertTrue(NoopExecutor().execute(lambda: True))
        self.assertTrue(DebugExecutor().execute(lambda: True))

        pool = MagicMock()
        future = MagicMock(result=lambda timeout=None: True)
        pool.submit.return_value = future
        pool.__enter__.return_value = pool
        pool.__exit__.return_value = False
        with patch("trainsh.runtime_executors.concurrent.futures.ThreadPoolExecutor", return_value=pool):
            self.assertTrue(ThreadPoolExecutor(max_workers=2).execute(lambda: True))
            self.assertTrue(ProcessPoolExecutor(max_workers=2).execute(lambda: True))
            self.assertTrue(DaskExecutor(max_workers=2).execute(lambda: True))
        self.assertTrue(ThreadPoolExecutor(max_workers=1).execute(lambda: True))
        self.assertTrue(ProcessPoolExecutor(max_workers=1).execute(lambda: True))
        self.assertTrue(DaskExecutor(max_workers=1).execute(lambda: True))
        self.assertTrue(LocalExecutor(max_workers=1).execute(lambda: True))
        self.assertTrue(CeleryExecutor(max_workers=1).execute(lambda: True))


class ProviderDispatchAndConditionsTests(unittest.TestCase):
    def _executor(self):
        class Fake(ExecutorProviderDispatchMixin, ExecutorProviderConditionsMixin):
            def __init__(self):
                self.ctx = SimpleNamespace(job_id="job1", start_time=None, variables={})
                self.recipe = SimpleNamespace(name="demo")
                self.recipe_path = ""

            def _resolve_host(self, value):
                return f"resolved:{value}"

            def _parse_duration(self, value):
                if value == "bad":
                    raise ValueError("bad")
                return 5

            def _coerce_bool(self, value, default=False):
                return str(value).lower() in {"1", "true", "yes", "y"} if value is not None else default

            def _exec_provider_shell(self, params):
                return True, "shell"

            def _exec_provider_python(self, params):
                return True, "python"

            def _exec_provider_storage_upload(self, params):
                return True, "upload"

            def _exec_provider_storage_download(self, params):
                return True, "download"

            def _exec_provider_storage_list(self, params):
                return True, "list"

            def _exec_provider_storage_exists(self, params):
                return True, "exists"

            def _exec_provider_storage_read_text(self, params):
                return True, "read"

            def _exec_provider_storage_info(self, params):
                return True, "info"

            def _exec_provider_storage_wait(self, params):
                return True, "wait"

            def _exec_provider_storage_mkdir(self, params):
                return True, "mkdir"

            def _exec_provider_storage_delete(self, params):
                return True, "delete"

            def _exec_provider_storage_rename(self, params):
                return True, "rename"

            def _exec_provider_transfer(self, params):
                return True, "transfer"

            def _exec_provider_http_request(self, params):
                return True, "http"

            def _exec_provider_http_wait(self, params):
                return True, "httpwait"

            def _exec_provider_hf_download(self, params):
                return True, "hf"

            def _exec_provider_fetch_exchange_rates(self, params):
                return True, "rates"

            def _exec_provider_calculate_cost(self, params):
                return True, "cost"

            def _exec_provider_wait_condition(self, params):
                return True, "cond"

            def _exec_provider_sqlite_query(self, params):
                return True, "query"

            def _exec_provider_sqlite_exec(self, params):
                return True, "exec"

            def _exec_provider_sqlite_script(self, params):
                return True, "script"

            def _exec_provider_ssh_command(self, params):
                return True, "ssh"

            def _exec_provider_uv_run(self, params):
                return True, "uv"

            def _exec_provider_set_var(self, params):
                return True, "setvar"

            def _exec_provider_xcom_push(self, params):
                return True, "xpush"

            def _exec_provider_xcom_pull(self, params):
                return True, "xpull"

            def _exec_provider_notice(self, params):
                return True, "notice"

            def _exec_provider_branch(self, params):
                return True, "branch"

            def _exec_provider_short_circuit(self, params):
                return True, "short"

            def _exec_provider_fail(self, params):
                return False, "fail"

            def _exec_provider_latest_only(self, params):
                return True, "latest"

            def _cmd_sleep(self, args):
                return True, "sleep"

            def _exec_provider_empty(self, params):
                return True, "noop"

            def _exec_provider_vast(self, operation, params):
                return True, "vast"

            def _exec_provider_git_clone(self, params):
                return True, "clone"

            def _exec_provider_git_pull(self, params):
                return True, "pull"

            def _exec_provider_host_test(self, params):
                return True, "host"

            def _exec_provider_assert(self, params):
                return True, "assert"

            def _exec_provider_get_value(self, params):
                return True, "get"

            def _exec_provider_set_env(self, params):
                return True, "setenv"

            def _exec_provider_wait_for_file(self, params):
                return True, "waitfile"

            def _exec_provider_wait_for_port(self, params):
                return True, "waitport"

            def _interpolate(self, text):
                return text

            def _eval_condition(self, condition, host="local"):
                return False, "detail"

        return Fake()

    def test_dispatch_and_conditions_misc_paths(self):
        ex = self._executor()
        self.assertEqual(ex._extract_provider_metadata(SimpleNamespace(provider="", operation="", params={}, command="provider", raw="provider util.empty {bad}"))[:2], ("util", "empty"))
        self.assertEqual(ex._normalize_provider_timeout(None), 0)
        self.assertIsNone(ex._normalize_provider_timeout(-1))
        self.assertEqual(ex._normalize_provider_timeout(True), 1)
        self.assertIsNone(ex._normalize_provider_timeout("bad"))
        self.assertEqual(ex._positive_provider_timeout("bad", default=7), 7)
        self.assertEqual(ex._provider_host(None), "local")
        self.assertEqual(ex._provider_host("@gpu"), "resolved:@gpu")
        self.assertEqual(ex._provider_host("gpu"), "resolved:@gpu")

        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="", operation="run", params={}, id="s"))[0], False)
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="shell", operation="", params={}, id="s"))[0], False)
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="http", operation="request_json", params={"json_body": {"ok": True}}, id="s")), (True, "http"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="util", operation="sleep", params={"duration": "5s"}, id="s")), (True, "sleep"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="cloud", operation="unknown", params={"storage": "x"}, id="s"))[0], False)
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="missing", operation="run", params={}, id="s"))[0], False)

        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_wait_condition(ex, {"condition": "x", "timeout": "bad"})[0], False)
        self.assertEqual(ex._exec_provider_branch({"condition": "x", "variable": ""}), (True, "branch"))
        self.assertEqual(ex._exec_provider_short_circuit({"condition": "x", "invert": True, "message": "m"})[0], True)
        self.assertEqual(
            ExecutorProviderConditionsMixin._exec_provider_fail(ex, {"message": "", "exit_code": 0})[1],
            "Failed by recipe. (exit_code=1)",
        )
        self.assertEqual(ex._exec_provider_ssh_command({"command": "echo hi", "host": "gpu"})[0], True)
        self.assertEqual(ex._exec_provider_uv_run({"command": "echo hi", "packages": "rich"})[0], True)


class TmuxAndRemoteTests(unittest.TestCase):
    def test_tmux_control_and_remote_tmux_paths(self):
        local_tmux = SimpleNamespace(
            has_session=MagicMock(return_value=True),
            new_session=MagicMock(return_value=TmuxCmdResult(1, "", "fail")),
            kill_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            run=MagicMock(return_value=TmuxCmdResult(0, "", "")),
        )
        remote_tmux = SimpleNamespace(
            has_session=MagicMock(return_value=False),
            new_session=MagicMock(return_value=TmuxCmdResult(1, "", "fail")),
            build_attach_command=MagicMock(return_value="attach"),
            kill_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            write_text=MagicMock(return_value=TmuxCmdResult(1, "", "write fail")),
            run=MagicMock(return_value=TmuxCmdResult(1, "", "source fail")),
            list_sessions=MagicMock(return_value=[]),
        )
        executor = SimpleNamespace(
            _resolve_host=lambda host: "local" if host == "@local" else "gpu",
            allocate_window_session_name=lambda: "sess1",
            logger=SimpleNamespace(log_detail=MagicMock()),
            local_tmux=local_tmux,
            ctx=SimpleNamespace(windows={}),
            log=MagicMock(),
            _ensure_bridge_window=MagicMock(),
            get_tmux_client=lambda host: remote_tmux,
            tmux_bridge=SimpleNamespace(disconnect=MagicMock()),
        )
        helper = TmuxControlHelper(executor, SimpleNamespace)
        self.assertEqual(helper.cmd_tmux_open(["@local"])[0], False)
        ok, msg = helper.cmd_tmux_open(["@local", "as", "main"])
        self.assertTrue(ok)
        self.assertIn("Created local tmux session", msg)
        local_tmux.has_session.return_value = False
        ok, msg = helper.cmd_tmux_open(["@local", "as", "main2"])
        self.assertFalse(ok)
        self.assertIn("Failed to create local tmux session", msg)
        local_tmux.has_session.side_effect = RuntimeError("boom")
        ok, msg = helper.cmd_tmux_open(["@local", "as", "main3"])
        self.assertFalse(ok)
        self.assertIn("boom", msg)
        local_tmux.has_session.side_effect = None

        ok, msg = helper.cmd_tmux_open(["@gpu", "as", "remote"])
        self.assertFalse(ok)
        self.assertIn("Failed to create remote tmux session", msg)
        remote_tmux.new_session.return_value = TmuxCmdResult(0, "", "")
        ok, msg = helper.cmd_tmux_open(["@gpu", "as", "remote2"])
        self.assertTrue(ok)

        self.assertEqual(helper.cmd_tmux_close([])[0], False)
        self.assertEqual(helper.cmd_tmux_close(["main"])[0], False)
        self.assertEqual(helper.cmd_tmux_close(["@missing"])[0], False)
        executor.ctx.windows["plain"] = SimpleNamespace(host="gpu", remote_session="")
        ok, msg = helper.cmd_tmux_close(["@plain"])
        self.assertTrue(ok)
        executor.ctx.windows["local"] = SimpleNamespace(host="local", remote_session="sess")
        local_tmux.kill_session.side_effect = RuntimeError("boom")
        ok, msg = helper.cmd_tmux_close(["@local"])
        self.assertFalse(ok)
        local_tmux.kill_session.side_effect = None
        executor.ctx.windows["remote"] = SimpleNamespace(host="gpu", remote_session="sess")
        remote_tmux.kill_session.side_effect = RuntimeError("boom")
        ok, msg = helper.cmd_tmux_close(["@remote"])
        self.assertFalse(ok)
        remote_tmux.kill_session.side_effect = None

        self.assertEqual(helper.cmd_tmux_config([])[0], False)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmux_conf = Path(tmpdir) / ".tmux.conf"
            with patch("trainsh.core.executor_tmux.load_config", return_value={"tmux": {"options": []}}), patch(
                "trainsh.core.executor_tmux.get_default_config", return_value={"tmux": {"options": ["set -g mouse on"]}}
            ), patch("os.path.expanduser", return_value=str(tmux_conf)):
                ok, msg = helper.cmd_tmux_config(["@local"])
            self.assertTrue(ok)
            self.assertTrue(tmux_conf.exists())

        with patch("trainsh.core.executor_tmux.load_config", return_value={"tmux": {"options": []}}), patch(
            "trainsh.core.executor_tmux.get_default_config", return_value={"tmux": {"options": ["set -g mouse on"]}}
        ):
            ok, msg = helper.cmd_tmux_config(["@gpu"])
        self.assertFalse(ok)
        self.assertIn("Failed to write ~/.tmux.conf", msg)
        remote_tmux.write_text.return_value = TmuxCmdResult(0, "", "")
        ok, msg = helper.cmd_tmux_config(["@gpu"])
        self.assertTrue(ok)

        client = RemoteTmuxClient("gpu", lambda host, command=None, tty=False, set_term=False: ["ssh", host, command or ""])
        with patch("trainsh.core.remote_tmux.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
            self.assertEqual(client._run_shell("echo hi").stdout, "ok\n")
        with patch("trainsh.core.remote_tmux.subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            self.assertEqual(client._run_shell("echo hi").returncode, 124)
        with patch("trainsh.core.remote_tmux.subprocess.run", side_effect=RuntimeError("boom")):
            self.assertEqual(client._run_shell("echo hi").returncode, 1)
        self.assertIn("-t", client.build_shell_command("echo hi", tty=True, force_extra_tty=True))
        self.assertIn("status-position bottom", client.build_attach_command("sess", status_mode="bottom"))
        self.assertIn("status off", client.build_attach_command("sess", status_mode="off"))
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(1, "", "")):
            self.assertEqual(client.list_sessions(), [])
            self.assertEqual(client.list_windows("sess"), [])
            self.assertEqual(client.list_panes("sess"), [])
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(0, "", "")) as mocked_run, patch.object(
            client, "_run_shell", return_value=TmuxCmdResult(0, "", "")
        ):
            client.run_line("tmux list-sessions")
            client.wait_for("sig", timeout=1)
            client.capture_pane("sess", start="-10", end="-1")
            client.send_keys("sess", "echo hi", enter=False)
            client.write_text("~/file.txt", "hello")
        self.assertTrue(mocked_run.called)


class TransferSupportAndViewsTests(unittest.TestCase):
    def test_transfer_support_and_views_edges(self):
        secrets = MagicMock()
        secrets.get.return_value = None
        smb = Storage(name="smb", type=StorageType.SMB, config={"host": "smb"})
        gdrive = Storage(name="drive", type=StorageType.GOOGLE_DRIVE, config={"remote_name": "drive-remote"})
        with patch("trainsh.services.transfer_support.get_secrets_manager", return_value=secrets):
            env = build_rclone_env(Storage(name="s3", type=StorageType.S3, config={}))
        self.assertEqual(env["RCLONE_CONFIG_S3_TYPE"], "s3")
        self.assertEqual(build_rclone_env(gdrive)["RCLONE_CONFIG_DRIVE_REMOTE_TYPE"], "drive")
        self.assertEqual(build_rclone_env(smb)["RCLONE_CONFIG_SMB_TYPE"], "smb")
        self.assertEqual(get_rclone_remote_name(gdrive), "drive-remote")
        self.assertEqual(repr(TransferPlan("rsync", "local")), "TransferPlan(method=rsync, via=local)")
        plan = analyze_transfer(TransferEndpoint(type="local", path="/a"), TransferEndpoint(type="local", path="/b"))
        self.assertEqual(plan.via, "local")
        with patch("trainsh.services.transfer_support.subprocess.Popen", side_effect=RuntimeError("boom")):
            self.assertFalse(rsync_with_progress("/a", "/b").success)
        with patch("trainsh.services.transfer_support.subprocess.run", side_effect=FileNotFoundError()):
            self.assertFalse(check_rsync_available())
            self.assertFalse(check_rclone_available())

        out, code, _ = capture(recipe.main, ["--help"])
        self.assertIsNone(code)
        self.assertIn("train recipe", out)
        out, code, _ = capture(config_cmd.main, ["tmux", "--help"])
        self.assertIsNone(code)
        self.assertIn("train config tmux", out)


if __name__ == "__main__":
    unittest.main()
