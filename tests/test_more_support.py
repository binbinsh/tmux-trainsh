import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.commands import config_cmd, recipe, transfer
from trainsh.core.executor_tmux import TmuxControlHelper
from trainsh.core.local_tmux import TmuxCmdResult
from trainsh.core.provider_conditions import ExecutorProviderConditionsMixin
from trainsh.core.provider_dispatch import ExecutorProviderDispatchMixin
from trainsh.core.remote_tmux import RemoteTmuxClient
from trainsh.runtime_executors import get_executor
from trainsh.services.transfer_support import (
    TransferPlan,
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
    with redirect_stdout(stream):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code


class SmallModuleSweepTests(unittest.TestCase):
    def test_config_transfer_remote_tmux_and_helpers(self):
        with patch("trainsh.config.load_config", return_value={"tmux": {"options": ["set -g mouse on"]}}):
            out, code = capture(config_cmd.cmd_tmux_list, [])
        self.assertIsNone(code)
        self.assertIn("set -g mouse on", out)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmux_conf = Path(tmpdir) / ".tmux.conf"
            tmux_conf.write_text("old", encoding="utf-8")
            with patch("os.path.expanduser", return_value=str(tmux_conf)), patch(
                "trainsh.config.load_config", return_value={"tmux": {"options": ["new"]}}
            ), patch("trainsh.commands.config_cmd.prompt_input", return_value="n"):
                out, code = capture(config_cmd.cmd_tmux_setup, [])
            self.assertIsNone(code)
            self.assertIn("Cancelled.", out)

            with patch("trainsh.config.load_config", return_value={"tmux": {"options": []}}), patch(
                "trainsh.config.get_default_config", return_value={"tmux": {"options": []}}
            ), patch("tempfile.NamedTemporaryFile") as mocked_tmp, patch(
                "subprocess.run", side_effect=FileNotFoundError("nano missing")
            ), patch("os.unlink"):
                mocked_tmp.return_value.__enter__.return_value.name = str(Path(tmpdir) / "tmp.tmux.conf")
                mocked_tmp.return_value.__enter__.return_value.write = lambda *_a, **_k: None
                with self.assertRaises(FileNotFoundError):
                    config_cmd.cmd_tmux_edit([])

        self.assertEqual(transfer.parse_endpoint("@gpu:/tmp/out"), ("host", "/tmp/out", "gpu"))
        self.assertEqual(transfer.parse_endpoint("host:gpu:/tmp/out"), ("host", "/tmp/out", "gpu"))
        self.assertEqual(transfer.parse_endpoint("storage:artifacts:/tmp/out"), ("storage", "/tmp/out", "artifacts"))
        self.assertEqual(transfer.parse_endpoint("plain.txt"), ("local", "plain.txt", None))

        with patch("trainsh.services.transfer_engine.TransferEngine") as mocked_engine, patch(
            "trainsh.commands.storage.load_storages", return_value={}
        ):
            mocked_engine.return_value.rsync.return_value = SimpleNamespace(success=False, message="boom", bytes_transferred=0)
            out, code = capture(transfer.main, ["./a", "./b"])
        self.assertEqual(code, 1)
        self.assertIn("Transfer failed: boom", out)

        client = RemoteTmuxClient("gpu", lambda host, command=None, tty=False, set_term=False: ["ssh", host, command or ""])
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(0, "", "")):
            self.assertTrue(client.has_session("sess"))
            self.assertEqual(client.new_session("sess", detached=False, window_name="w", command="bash").returncode, 0)
            self.assertEqual(client.kill_session("sess").returncode, 0)
            self.assertEqual(client.display_message("sess", "#{pane_id}").returncode, 0)
            self.assertEqual(client.split_window("sess", "bash", horizontal=False).returncode, 0)
            self.assertEqual(client.set_pane_title("%1", "title").returncode, 0)
            self.assertEqual(client.select_layout("sess", "tiled").returncode, 0)
            self.assertEqual(client.kill_pane("%1").returncode, 0)
            self.assertEqual(client.send_keys("sess", "echo hi").returncode, 0)
            self.assertEqual(client.wait_for("sig").returncode, 0)
        self.assertIn("attach -t", client.build_attach_command("sess"))

    def test_provider_dispatch_conditions_tmux_and_transfer_support(self):
        class FakeDispatch(ExecutorProviderDispatchMixin, ExecutorProviderConditionsMixin):
            def __init__(self):
                self.ctx = SimpleNamespace(job_id="job1", start_time=None, variables={})
                self.recipe = SimpleNamespace(name="demo")
                self.recipe_path = ""

            def _resolve_host(self, value): return value
            def _parse_duration(self, value): return 5
            def _coerce_bool(self, value, default=False): return bool(value)
            def _interpolate(self, text): return text
            def _eval_condition(self, condition, host="local"): return True, "ok"
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
            def _exec_provider_vast(self, op, params): return True, "vast"
            def _exec_provider_git_clone(self, params): return True, "clone"
            def _exec_provider_git_pull(self, params): return True, "pull"
            def _exec_provider_host_test(self, params): return True, "host"
            def _exec_provider_assert(self, params): return True, "assert"
            def _exec_provider_get_value(self, params): return True, "get"
            def _exec_provider_set_env(self, params): return True, "setenv"
            def _exec_provider_wait_for_file(self, params): return True, "waitfile"
            def _exec_provider_wait_for_port(self, params): return True, "waitport"

        ex = FakeDispatch()
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="http", operation="json_request", params={"json_body": {"x": 1}}, id="s")), (True, "http"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="email", operation="send", params={"message": "x"}, id="s")), (True, "notice"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="storage", operation="upload", params={"storage": "x"}, id="s")), (True, "upload"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="storage", operation="download", params={"storage": "x"}, id="s")), (True, "download"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="storage", operation="mkdir", params={"storage": "x"}, id="s")), (True, "mkdir"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="storage", operation="delete", params={"storage": "x"}, id="s")), (True, "delete"))
        self.assertEqual(ex._exec_provider(SimpleNamespace(provider="storage", operation="rename", params={"storage": "x"}, id="s")), (True, "rename"))
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_branch(ex, {"condition": "x", "variable": "", "true_value": "go"})[0], True)
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_short_circuit(ex, {"condition": "x", "invert": False})[0], True)
        self.assertEqual(ExecutorProviderConditionsMixin._exec_provider_latest_only(ex, {"enabled": False}), (True, "latest_only disabled"))

        local_tmux = SimpleNamespace(has_session=lambda name: False, new_session=lambda *a, **k: TmuxCmdResult(0, "", ""), kill_session=lambda name: TmuxCmdResult(0, "", ""), run=lambda *a, **k: TmuxCmdResult(0, "", ""))
        executor = SimpleNamespace(
            _resolve_host=lambda host: "local",
            allocate_window_session_name=lambda: "sess1",
            logger=None,
            local_tmux=local_tmux,
            ctx=SimpleNamespace(windows={}),
            log=lambda msg: None,
            _ensure_bridge_window=lambda window: None,
            get_tmux_client=lambda host: local_tmux,
            tmux_bridge=SimpleNamespace(disconnect=lambda name: None),
        )
        helper = TmuxControlHelper(executor, SimpleNamespace)
        self.assertTrue(helper.cmd_tmux_open(["@local", "as", "main"])[0])
        executor.ctx.windows["main"] = SimpleNamespace(host="local", remote_session="sess1")
        self.assertTrue(helper.cmd_tmux_close(["@main"])[0])

        secrets = MagicMock()
        secrets.get.side_effect = lambda key: {
            "R2_ACCESS_KEY": "AKIA",
            "R2_SECRET_KEY": "SECRET",
        }.get(key)
        with patch("trainsh.services.transfer_support.get_secrets_manager", return_value=secrets):
            env = build_rclone_env(Storage(name="cloud", type=StorageType.R2, config={"account_id": "acct"}))
        self.assertIn("RCLONE_CONFIG_CLOUD_ENDPOINT", env)
        self.assertEqual(get_rclone_remote_name(Storage(name="plain", type=StorageType.S3, config={})), "plain")
        self.assertEqual(TransferPlan("rclone", "cloud").via, "cloud")
        with patch("trainsh.services.transfer_support.subprocess.Popen", side_effect=RuntimeError("boom")):
            self.assertFalse(rsync_with_progress("/a", "/b").success)
        with patch("trainsh.services.transfer_support.subprocess.run", side_effect=FileNotFoundError()):
            self.assertFalse(check_rclone_available())


if __name__ == "__main__":
    unittest.main()
