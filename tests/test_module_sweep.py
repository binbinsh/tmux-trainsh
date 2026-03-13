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
from trainsh.core.provider_conditions import ExecutorProviderConditionsMixin
from trainsh.core.provider_dispatch import ExecutorProviderDispatchMixin
from trainsh.core.remote_tmux import RemoteTmuxClient
from trainsh.runtime_executors import NoopExecutor
from trainsh.services.transfer_support import (
    TransferPlan,
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


class DispatchAndConditionSweepTests(unittest.TestCase):
    def _executor(self):
        class Fake(ExecutorProviderDispatchMixin, ExecutorProviderConditionsMixin):
            def __init__(self):
                self.ctx = SimpleNamespace(job_id="job1", start_time=None, variables={})
                self.recipe = SimpleNamespace(name="demo")
                self.recipe_path = ""

            def _resolve_host(self, value):
                return f"host:{value}"

            def _parse_duration(self, value):
                if value == "bad":
                    raise ValueError("bad")
                return 5

            def _coerce_bool(self, value, default=False):
                return str(value).lower() in {"1", "true", "yes", "y"} if value is not None else default

            def _interpolate(self, text):
                return text

            def _eval_condition(self, condition, host="local"):
                return True, f"{condition}@{host}"

            def _exec_provider_shell(self, params): return True, "shell"
            def _exec_provider_python(self, params): return True, "python"
            def _exec_provider_storage_upload(self, params): return True, "upload"
            def _exec_provider_storage_download(self, params): return True, "download"
            def _exec_provider_storage_list(self, params): return True, "list"
            def _exec_provider_storage_exists(self, params): return True, "exists"
            def _exec_provider_storage_read_text(self, params): return True, "read"
            def _exec_provider_storage_info(self, params): return True, "info"
            def _exec_provider_storage_wait(self, params): return True, "wait"
            def _exec_provider_storage_mkdir(self, params): return True, "mkdir"
            def _exec_provider_storage_delete(self, params): return True, "delete"
            def _exec_provider_storage_rename(self, params): return True, "rename"
            def _exec_provider_transfer(self, params): return True, "transfer"
            def _exec_provider_http_request(self, params): return True, "http"
            def _exec_provider_http_wait(self, params): return True, "httpwait"
            def _exec_provider_hf_download(self, params): return True, "hf"
            def _exec_provider_fetch_exchange_rates(self, params): return True, "rates"
            def _exec_provider_calculate_cost(self, params): return True, "cost"
            def _exec_provider_wait_condition(self, params): return True, "cond"
            def _exec_provider_sqlite_query(self, params): return True, "query"
            def _exec_provider_sqlite_exec(self, params): return True, "exec"
            def _exec_provider_sqlite_script(self, params): return True, "script"
            def _exec_provider_ssh_command(self, params): return True, "ssh"
            def _exec_provider_uv_run(self, params): return True, "uv"
            def _exec_provider_set_var(self, params): return True, "setvar"
            def _exec_provider_xcom_push(self, params): return True, "xpush"
            def _exec_provider_xcom_pull(self, params): return True, "xpull"
            def _exec_provider_notice(self, params): return True, "notice"
            def _exec_provider_branch(self, params): return True, "branch"
            def _exec_provider_short_circuit(self, params): return True, "short"
            def _exec_provider_fail(self, params): return False, "fail"
            def _exec_provider_latest_only(self, params): return True, "latest"
            def _cmd_sleep(self, args): return True, "sleep"
            def _exec_provider_empty(self, params): return True, "noop"
            def _exec_provider_vast(self, operation, params): return True, "vast"
            def _exec_provider_git_clone(self, params): return True, "clone"
            def _exec_provider_git_pull(self, params): return True, "pull"
            def _exec_provider_host_test(self, params): return True, "host"
            def _exec_provider_assert(self, params): return True, "assert"
            def _exec_provider_get_value(self, params): return True, "get"
            def _exec_provider_set_env(self, params): return True, "setenv"
            def _exec_provider_wait_for_file(self, params): return True, "waitfile"
            def _exec_provider_wait_for_port(self, params): return True, "waitport"

        return Fake()

    def test_dispatch_and_conditions_branch_sweep(self):
        ex = self._executor()
        self.assertEqual(ex._extract_provider_metadata(SimpleNamespace(provider="", operation="", params=None, command="provider", raw="provider util.branch {\"x\":1}")), ("util", "branch", {"x": 1}))
        self.assertEqual(ex._normalize_provider_timeout(""), 0)
        self.assertIsNone(ex._normalize_provider_timeout("bad"))
        self.assertEqual(ex._positive_provider_timeout(None, default=7), 7)
        self.assertEqual(ex._provider_host(""), "local")
        self.assertEqual(ex._provider_host("gpu"), "host:@gpu")

        step = lambda provider, operation, params=None, sid="s": SimpleNamespace(provider=provider, operation=operation, params=params or {}, id=sid, command="provider", raw="")
        self.assertEqual(ex._exec_provider(step("bash", "local_run")), (True, "shell"))
        self.assertEqual(ex._exec_provider(step("python", "local")), (True, "shell"))
        self.assertEqual(ex._exec_provider(step("http", "sensor")), (True, "httpwait"))
        self.assertEqual(ex._exec_provider(step("http", "http")), (True, "http"))
        self.assertEqual(ex._exec_provider(step("storage", "copy")), (True, "transfer"))
        self.assertEqual(ex._exec_provider(step("transfer", "mirror")), (True, "transfer"))
        self.assertEqual(ex._exec_provider(step("email", "notice", {"message": "x"})), (True, "notice"))
        self.assertEqual(ex._exec_provider(step("util", "latest_only")), (True, "latest"))
        self.assertEqual(ex._exec_provider(step("vast", "cost")), (True, "vast"))
        self.assertFalse(ex._exec_provider(step("cloud", "oops", {"storage": "x"}))[0])

        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_wait_condition(ex, {"condition": "x", "capture": True}), (True, "x@host:@local"))
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_branch(ex, {"condition": "x", "variable": "BR", "true_value": "go"})[0], True)
        self.assertEqual(ex.ctx.variables["BR"], "go")
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_short_circuit(ex, {"condition": "x", "invert": True})[0], False)
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_fail(ex, {"message": "", "exit_code": 0})[1], "Failed by recipe. (exit_code=1)")
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_ssh_command(ex, {"command": "echo hi"})[0], True)
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_uv_run(ex, {"command": "echo hi", "packages": ["rich"], "timeout": 5})[0], True)


class TmuxAndRemoteSweepTests(unittest.TestCase):
    def test_tmux_control_and_remote_tmux_sweep(self):
        local_tmux = SimpleNamespace(
            has_session=MagicMock(return_value=False),
            new_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            kill_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            run=MagicMock(return_value=TmuxCmdResult(1, "", "source fail")),
        )
        remote_tmux = SimpleNamespace(
            has_session=MagicMock(return_value=True),
            new_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            build_attach_command=MagicMock(return_value="attach"),
            kill_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            write_text=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            run=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            list_sessions=MagicMock(return_value=["sess"]),
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
        self.assertTrue(helper.cmd_tmux_open(["@local", "as", "main"])[0])
        self.assertTrue(helper.cmd_tmux_open(["@gpu", "as", "main"])[0])
        executor.ctx.windows["main"] = SimpleNamespace(host="gpu", remote_session="sess")
        self.assertTrue(helper.cmd_tmux_close(["@main"])[0])

        with tempfile.TemporaryDirectory() as tmpdir:
            tmux_conf = Path(tmpdir) / ".tmux.conf"
            with patch("trainsh.core.executor_tmux.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}), patch(
                "os.path.expanduser", return_value=str(tmux_conf)
            ):
                ok, msg = helper.cmd_tmux_config(["@local"])
            self.assertTrue(ok)

        remote_tmux.run.return_value = TmuxCmdResult(1, "", "source fail")
        remote_tmux.list_sessions.return_value = ["sess"]
        with patch("trainsh.core.executor_tmux.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}):
            ok, msg = helper.cmd_tmux_config(["@gpu"])
        self.assertFalse(ok)
        self.assertIn("Failed to source", msg)

        client = RemoteTmuxClient("gpu", lambda host, command=None, tty=False, set_term=False: ["ssh", host, command or ""])
        with patch("trainsh.core.remote_tmux.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
            self.assertEqual(client._run_shell("echo hi").stdout, "ok\n")
        with patch("trainsh.core.remote_tmux.subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            self.assertEqual(client._run_shell("echo hi").stderr, "remote tmux command timed out")
        with patch("trainsh.core.remote_tmux.subprocess.run", side_effect=RuntimeError("boom")):
            self.assertEqual(client._run_shell("echo hi").returncode, 1)
        self.assertIn("tmux set-option -gq status off", client.build_attach_command("sess", status_mode="off"))
        self.assertIn("status-position bottom", client.build_attach_command("sess", status_mode="bottom"))
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(1, "", "")):
            self.assertFalse(client.has_session("sess"))
            self.assertEqual(client.list_sessions(), [])
            self.assertEqual(client.list_windows("sess"), [])
            self.assertEqual(client.list_panes("sess"), [])
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(0, "", "")) as mocked_tmux, patch.object(
            client, "_run_shell", return_value=TmuxCmdResult(0, "", "")
        ):
            client.run_line("tmux list-sessions")
            client.new_session("sess", detached=False, window_name="w", command="bash")
            client.kill_session("sess")
            client.display_message("sess", "#{pane_id}")
            client.split_window("sess", "bash", horizontal=True)
            client.set_pane_title("%1", "title")
            client.select_layout("sess", "tiled")
            client.kill_pane("%1")
            client.send_keys("sess", "echo hi")
            client.capture_pane("sess", start="-10", end="-1")
            client.wait_for("sig", timeout=1)
            client.write_text("~", "hello")
        self.assertTrue(mocked_tmux.called)


class TransferSupportSweepTests(unittest.TestCase):
    def test_transfer_support_sweep(self):
        secrets = MagicMock()
        secrets.get.side_effect = lambda key: {
            "DRIVE_TOKEN": "token",
            "S3_ACCESS_KEY_ID": "AKIA",
            "S3_SECRET_ACCESS_KEY": "SECRET",
        }.get(key)
        with patch("trainsh.services.transfer_support.get_secrets_manager", return_value=secrets):
            s3 = Storage(name="s3", type=StorageType.S3, config={"region": "us-east-1"})
            self.assertIn("RCLONE_CONFIG_S3_ACCESS_KEY_ID", build_rclone_env(s3))
            drive = Storage(name="drive", type=StorageType.GOOGLE_DRIVE, config={"client_id": "cid", "client_secret": "sec", "root_folder_id": "root"})
            self.assertIn("TOKEN", "".join(build_rclone_env(drive).keys()))
            gcs = Storage(name="gcs", type=StorageType.GCS, config={"project_id": "pid", "service_account_json": "{}", "bucket": "b"})
            self.assertIn("PROJECT_NUMBER", "".join(build_rclone_env(gcs).keys()))
            ssh = Storage(name="sshbox", type=StorageType.SSH, config={"host": "ssh", "user": "root", "port": 22, "key_file": "~/.ssh/id"})
            self.assertIn("KEY_FILE", "".join(build_rclone_env(ssh).keys()))
        self.assertEqual(get_rclone_remote_name(Storage(name="drive", type=StorageType.GOOGLE_DRIVE, config={"remote_name": "g"})), "g")
        self.assertEqual(analyze_transfer(TransferEndpoint(type="host", path="/a", host_id="gpu"), TransferEndpoint(type="local", path="/b")).method, "rsync")
        self.assertEqual(analyze_transfer(TransferEndpoint(type="storage", path="/a", storage_id="s"), TransferEndpoint(type="local", path="/b"), storages={"s": Storage(name="s", type=StorageType.SSH, config={})}).method, "rsync")

        host = Host(name="gpu", type=HostType.SSH, hostname="gpu.example.com", username="root", auth_method=AuthMethod.KEY)
        cb = MagicMock()
        process = MagicMock()
        process.stdout.readline.side_effect = ["1,024  12%    1.23MB/s    0:01:23\n", ""]
        process.wait.return_value = 1
        with patch("trainsh.services.transfer_support.subprocess.Popen", return_value=process):
            result = rsync_with_progress("/a", "/b", host=host, upload=False, delete=True, exclude=["*.tmp"], progress_callback=cb)
        self.assertFalse(result.success)
        cb.assert_called()
        with patch("trainsh.services.transfer_support.subprocess.run", side_effect=FileNotFoundError()):
            self.assertFalse(check_rsync_available())
            self.assertFalse(check_rclone_available())


if __name__ == "__main__":
    unittest.main()
