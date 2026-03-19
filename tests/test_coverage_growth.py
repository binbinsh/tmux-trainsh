import io
import os
import runpy
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.commands import config_cmd, recipe_views
from trainsh.core.executor_main import DSLExecutor, run_recipe
from trainsh.core.executor_tmux import TmuxControlHelper
from trainsh.core.job_state import JobState
from trainsh.core.local_tmux import TmuxCmdResult
from trainsh.core.models import Host, Storage, StorageType, TransferEndpoint
from trainsh.core.recipe_models import RecipeModel
from trainsh.core.remote_tmux import RemoteTmuxClient
from trainsh.services.ssh import SSHClient, SSHConnectionTarget
from trainsh.services.transfer_support import analyze_transfer, build_rclone_env, rsync_with_progress

from tests.runtime_test_utils import isolated_executor


def capture_output(fn, *args, **kwargs):
    stream = io.StringIO()
    code = None
    result = None
    with redirect_stdout(stream):
        try:
            result = fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return stream.getvalue(), code, result


class CoverageGrowthTests(unittest.TestCase):
    def test_transfer_support_and_tmux_edges(self):
        secrets = SimpleNamespace(get=lambda _key: None)
        with patch("trainsh.services.transfer_support.get_secrets_manager", return_value=secrets):
            s3_env = build_rclone_env(Storage(name="s3", type=StorageType.S3, config={}))
            smb_env = build_rclone_env(
                Storage(
                    name="smb",
                    type=StorageType.SMB,
                    config={"host": "smb.example", "user": "demo", "pass": "secret", "domain": "workgroup"},
                )
            )
        self.assertEqual(s3_env["RCLONE_CONFIG_S3_TYPE"], "s3")
        self.assertEqual(smb_env["RCLONE_CONFIG_SMB_PASS"], "secret")

        plan = analyze_transfer(
            TransferEndpoint(type="mystery", path="/src"),
            TransferEndpoint(type="mystery", path="/dst"),
        )
        self.assertEqual(plan.method, "rsync")

        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "id_ed25519"
            key_path.write_text("secret", encoding="utf-8")
            process = SimpleNamespace(
                stdout=SimpleNamespace(readline=MagicMock(side_effect=["1,024 10% 1.0MiB/s 0:01\n", ""])),
                wait=MagicMock(return_value=0),
            )
            host = Host(name="gpu", hostname="gpu.example", username="root", ssh_key_path=str(key_path))
            with patch("trainsh.services.transfer_support.os.path.exists", return_value=True), patch(
                "trainsh.services.transfer_support.subprocess.Popen", return_value=process
            ) as mocked_popen:
                result = rsync_with_progress("~/src", "/remote/dst", host=host, upload=True)
            self.assertTrue(result.success)
            popen_args = mocked_popen.call_args.args[0]
            self.assertIn("-e", popen_args)
            self.assertIn(str(Path("~/src").expanduser()), popen_args)
            self.assertIn("root@gpu.example:/remote/dst", popen_args)

        local_tmux = SimpleNamespace(
            has_session=MagicMock(return_value=True),
            new_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            kill_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            run=MagicMock(side_effect=RuntimeError("source failed")),
        )
        remote_tmux = SimpleNamespace(
            has_session=MagicMock(side_effect=RuntimeError("remote boom")),
            new_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            build_attach_command=MagicMock(return_value="attach"),
            kill_session=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            write_text=MagicMock(side_effect=RuntimeError("write boom")),
            run=MagicMock(return_value=TmuxCmdResult(0, "", "")),
            list_sessions=MagicMock(return_value=[]),
        )
        executor = SimpleNamespace(
            _resolve_host=lambda host: "local" if host == "@local" else "gpu",
            allocate_window_session_name=lambda: "sess-1",
            logger=SimpleNamespace(log_detail=MagicMock()),
            local_tmux=local_tmux,
            ctx=SimpleNamespace(windows={}),
            log=MagicMock(),
            _ensure_bridge_window=MagicMock(),
            get_tmux_client=lambda host: remote_tmux,
            tmux_bridge=SimpleNamespace(disconnect=MagicMock()),
        )
        helper = TmuxControlHelper(executor, SimpleNamespace)
        ok, msg = helper.cmd_tmux_open(["@gpu", "as", "main"])
        self.assertFalse(ok)
        self.assertIn("remote boom", msg)
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "trainsh.core.executor_tmux.load_config",
            return_value={"tmux": {"options": ["set -g mouse on"]}},
        ), patch("trainsh.core.executor_tmux.os.path.expanduser", return_value=str(Path(tmpdir) / ".tmux.conf")):
            ok, msg = helper.cmd_tmux_config(["@local"])
            self.assertTrue(ok)
            ok, msg = helper.cmd_tmux_config(["@gpu"])
            self.assertFalse(ok)
            self.assertIn("write boom", msg)

        client = RemoteTmuxClient(
            "gpu",
            lambda host, command=None, tty=False, set_term=False: ["ssh", host, command or ""],
        )
        with patch.object(client, "_run_tmux", return_value=TmuxCmdResult(0, "ok", "")) as mocked_tmux:
            client.new_session("sess")
            client.send_keys("%1", "echo hi", literal=False)
        self.assertIn("-d", mocked_tmux.call_args_list[0].args[0])
        self.assertEqual(mocked_tmux.call_args_list[1].args[0], ["send-keys", "-t", "%1", "echo hi"])

        with patch.object(client, "_run_shell", return_value=TmuxCmdResult(0, "ok", "")) as mocked_shell, patch(
            "trainsh.core.remote_tmux.uuid.uuid4",
            side_effect=[SimpleNamespace(hex="abc"), SimpleNamespace(hex="def")],
        ):
            client.write_text("/tmp/demo.txt", "contains TRAINSH_EOF_abc")
        shell_cmd = mocked_shell.call_args.args[0]
        self.assertIn("TRAINSH_EOF_def", shell_cmd)
        self.assertIn("/tmp/demo.txt", shell_cmd)

    def test_config_command_edges_and_module_entrypoints(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmux_conf = Path(tmpdir) / ".tmux.conf"
            with patch("trainsh.config.load_config", return_value={"tmux": {"options": []}}), patch(
                "trainsh.config.get_default_config",
                return_value={"tmux": {"options": ["set -g mouse on"]}},
            ), patch("trainsh.commands.config_cmd.prompt_input", return_value="n"), patch.dict(
                os.environ,
                {"HOME": tmpdir},
                clear=False,
            ):
                output, code, _ = capture_output(config_cmd.cmd_tmux_setup, [])
            self.assertIn("Using defaults", output)
            self.assertIn("Cancelled.", output)

            with patch("trainsh.config.load_config", return_value={"tmux": {"options": []}}), patch(
                "trainsh.config.get_default_config",
                return_value={"tmux": {"options": ["set -g status off"]}},
            ):
                output, code, _ = capture_output(config_cmd.cmd_tmux_list, [])
            self.assertIn("set -g status off", output)

        stream = io.StringIO()
        with patch.object(sys, "argv", ["config_cmd.py", "--help"]), redirect_stdout(stream):
            runpy.run_module("trainsh.commands.config_cmd", run_name="__main__")
        self.assertIn("train config", stream.getvalue())

        old_cli_docs = getattr(sys, "cli_docs", None)
        try:
            sys.cli_docs = {}
            runpy.run_module("trainsh.commands.config_cmd", run_name="__doc__")
            self.assertIn("usage", sys.cli_docs)
            self.assertIn("short_desc", sys.cli_docs)
        finally:
            if old_cli_docs is None:
                delattr(sys, "cli_docs")
            else:
                sys.cli_docs = old_cli_docs

    def test_provider_dispatch_condition_and_shell_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir, isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
            executor.recipe.hosts["gpu"] = "gpu"

            with patch.object(executor, "_parse_duration", return_value=-1):
                self.assertIsNone(executor._normalize_provider_timeout("1s"))
            with patch.object(executor, "_parse_duration", return_value=0):
                self.assertIsNone(executor._normalize_provider_timeout("1s", allow_zero=False))

            self.assertEqual(
                executor._extract_provider_metadata(
                    SimpleNamespace(provider="", operation="", params={}, command="provider", raw="provider util")
                )[:2],
                ("util", ""),
            )

            with patch.object(executor, "_exec_provider_hf_download", return_value=(True, "hf")), patch.object(
                executor, "_exec_provider_storage_test", return_value=(True, "test")
            ):
                self.assertEqual(
                    executor._exec_provider(SimpleNamespace(provider="util", operation="hf_download", params={}, id="s")),
                    (True, "hf"),
                )
                self.assertEqual(
                    executor._exec_provider(SimpleNamespace(provider="storage", operation="test", params={}, id="s")),
                    (True, "test"),
                )
            self.assertEqual(
                executor._exec_provider(SimpleNamespace(provider="cloud", operation="put", params={}, id="s"))[0],
                False,
            )

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "shell")), patch.object(
                executor, "_exec_provider_notice", return_value=(True, "notice")
            ):
                self.assertEqual(
                    executor._exec_provider(SimpleNamespace(provider="shell", operation="local", params={}, id="s")),
                    (True, "shell"),
                )
                self.assertEqual(
                    executor._exec_provider(SimpleNamespace(provider="email", operation="send", params={}, id="s")),
                    (True, "notice"),
                )

            with patch("trainsh.constants.CONFIG_DIR", Path(tmpdir)), patch(
                "trainsh.core.provider_conditions.time.time",
                side_effect=[0, 0, 1, 1],
            ), patch("trainsh.core.provider_conditions.time.sleep"):
                ok, msg = executor._exec_provider_wait_condition(
                    {"condition": "var:MISSING", "timeout": 1, "poll_interval": 0}
                )
            self.assertFalse(ok)
            self.assertIn("Timeout waiting for condition", msg)
            self.assertEqual(executor._exec_provider_latest_only("bad")[0], False)

            missing_db = Path(tmpdir) / "runtime.db"
            with patch("trainsh.constants.RUNTIME_STATE_DIR", Path(tmpdir) / "runtime"):
                ok, msg = executor._exec_provider_latest_only({"fail_if_unknown": True})
            self.assertFalse(ok)
            self.assertIn("runtime state not found", msg)
            missing_db.touch()
            (missing_db.with_suffix("")).mkdir(parents=True, exist_ok=True)
            executor.ctx.start_time = None
            ok, msg = executor._exec_provider_latest_only({"sqlite_db": str(missing_db), "fail_if_unknown": True})
            self.assertFalse(ok)
            self.assertIn("start time", msg)
            ok, msg = executor._exec_provider_latest_only({"sqlite_db": str(missing_db), "fail_if_unknown": False})
            self.assertTrue(ok)
            self.assertIn("unavailable", msg)

            executor.ctx.start_time = __import__("datetime").datetime.now()
            with patch("trainsh.core.runtime_store.RuntimeStore", side_effect=RuntimeError("db boom")):
                ok, msg = executor._exec_provider_latest_only({"sqlite_db": str(missing_db), "fail_if_unknown": False})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_latest_only({"sqlite_db": str(missing_db), "fail_if_unknown": True})
                self.assertFalse(ok)

            ok, msg = executor._exec_provider_uv_run(
                {"command": "echo hi", "packages": ["", "rich"], "timeout": "bad"}
            )
            self.assertFalse(ok)

            ok, msg = executor._exec_provider_shell({})
            self.assertFalse(ok)
            with patch("trainsh.core.provider_shell.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as mocked_run:
                ok, msg = executor._exec_provider_shell({"command": "echo hi", "env": {"A": 1}})
            self.assertTrue(ok)
            self.assertEqual(mocked_run.call_args.kwargs["env"]["A"], "1")

            ok, msg = executor._eval_condition("file_contains::needle")
            self.assertFalse(ok)
            missing_text = Path(tmpdir) / "missing.txt"
            ok, msg = executor._eval_condition(f"file_contains:{missing_text}:needle")
            self.assertFalse(ok)
            self.assertIn("File not found", msg)

            original_interpolate = executor._interpolate
            executor._interpolate = lambda text: None if text == "TOKEN" else original_interpolate(text)
            ok, msg = executor._eval_condition("storage_exists:@artifacts:TOKEN")
            self.assertFalse(ok)
            ok, msg = executor._eval_condition("storage_exists::/tmp")
            self.assertFalse(ok)
            executor._interpolate = original_interpolate

            ok, msg = executor._eval_condition("command_output::needle")
            self.assertFalse(ok)
            ok, msg = executor._eval_condition("host_online:")
            self.assertFalse(ok)
            executor._resolve_host = lambda value: "local" if value in {"@local", "local"} else "gpu"
            ok, msg = executor._eval_condition("host_online:local")
            self.assertTrue(ok)

            ok, msg = executor._exec_provider_host_test({"host": "local"})
            self.assertTrue(ok)
            executor.ctx.variables["READY"] = "1"
            ok, msg = executor._exec_provider_assert({"condition": "var:READY", "message": "bad"})
            self.assertTrue(ok)
            ok, msg = executor._exec_provider_assert({"condition": f"file:{missing_text}", "message": "bad"})
            self.assertFalse(ok)

            executor._resolve_host = lambda value: "gpu"
            with patch.object(executor, "_exec_provider_shell", side_effect=[(True, "exists"), (False, "")]):
                ok, msg = executor._exec_provider_assert({"condition": "file_exists:/tmp/ok", "message": "bad", "host": "gpu"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_assert({"condition": "file_exists:/tmp/miss", "message": "bad", "host": "gpu"})
                self.assertFalse(ok)
            with patch.object(executor, "_exec_provider_shell", return_value=(False, "")):
                ok, msg = executor._exec_provider_assert({"condition": "command:false", "message": "bad"})
            self.assertFalse(ok)

            ok, msg = executor._exec_provider_get_value({"target": "VALUE"})
            self.assertFalse(ok)
            with patch.object(executor, "_exec_provider_shell", return_value=(False, "")):
                ok, msg = executor._exec_provider_get_value({"target": "VALUE", "source": "command:echo hi"})
            self.assertFalse(ok)

            with patch("trainsh.core.provider_shell.os.path.exists", return_value=False), patch(
                "trainsh.core.provider_shell.time.time",
                side_effect=[0, 0, 2],
            ), patch("trainsh.core.provider_shell.time.sleep"):
                ok, msg = executor._exec_provider_wait_for_file({"path": "/tmp/missing", "timeout": 1, "poll_interval": 1})
            self.assertFalse(ok)

            ok, msg = executor._exec_provider_wait_for_port({"port": ""})
            self.assertFalse(ok)
            with patch("trainsh.core.provider_shell.socket.create_connection", side_effect=OSError("closed")), patch(
                "trainsh.core.provider_shell.time.time",
                side_effect=[0, 0, 2],
            ), patch("trainsh.core.provider_shell.time.sleep"):
                ok, msg = executor._exec_provider_wait_for_port({"port": 8080, "timeout": 1, "poll_interval": 1})
            self.assertFalse(ok)

    def test_ssh_wait_and_recipe_view_edges(self):
        host = Host(name="gpu", hostname="gpu.example", port=2200, env_vars={"connection_candidates": {"hostname": "alt"}})
        client = SSHClient.from_host(host)
        self.assertIsNone(SSHClient._build_cloudflared_proxy_command({"tunnel_type": "cloudflared", "cloudflared_hostname": ""}, host.hostname))
        candidates = SSHClient._parse_connection_candidates(
            Host(name="gpu", hostname="gpu.example", env_vars={}),
            {"connection_candidates": "ssh://dup.example:22,ssh://dup.example:22"},
        )
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(SSHClient._parse_connection_candidate_entry(" ", host, {}))
        self.assertIsNone(SSHClient._parse_connection_candidate_dict({"type": "cloudflared"}, host, {}))
        parsed = SSHClient._parse_connection_candidate_dict(
            {"type": "cloudflared", "hostname": "cf.example", "target_port": "bad"},
            host,
            {},
        )
        self.assertEqual(parsed.port, host.port)
        parsed = SSHClient._parse_connection_candidate_dict({"hostname": "alt.example", "port": "bad"}, host, {})
        self.assertEqual(parsed.port, 22)
        self.assertIsNone(SSHClient._parse_connection_candidate_token("ssh://", host, {}))
        self.assertIsNone(SSHClient._parse_connection_candidate_token("cloudflared://", host, {}))

        with tempfile.TemporaryDirectory() as tmpdir:
            key_path = Path(tmpdir) / "id_ed25519"
            key_path.write_text("key", encoding="utf-8")
            client = SSHClient("gpu.example", port=2200, key_path=str(key_path))
            args = client._build_ssh_args("echo hi")
            self.assertIn("-p", args)
            self.assertIn("-i", args)
            self.assertIn("gpu.example", args)

            client.connection_targets = []
            result = client.run("echo hi")
            self.assertIn("No connection candidates", result.stderr)
            self.assertEqual(client.connect_interactive(), 255)
            self.assertIn("-P", client._build_scp_upload_args("/tmp/in", "/tmp/out", True, SSHConnectionTarget("alt.example", port=2200)))
            self.assertIn(
                "alt.example:/tmp/out",
                client._build_scp_upload_args("/tmp/in", "/tmp/out", True, SSHConnectionTarget("alt.example", port=2200)),
            )
            self.assertIn(
                "alt.example:/tmp/in",
                client._build_scp_download_args("/tmp/in", "/tmp/out", True, SSHConnectionTarget("alt.example", port=2200)),
            )
            self.assertIn("No connection candidates", client.upload_file("/tmp/in", "/tmp/out").stderr)
            self.assertIn("No connection candidates", client.download_file("/tmp/in", "/tmp/out").stderr)

        with isolated_executor(RecipeModel(name="wait")) as (executor, _config_dir):
            tmux = SimpleNamespace(
                run_line=MagicMock(return_value="run"),
                capture_pane=MagicMock(return_value=TmuxCmdResult(0, "line\n", "")),
                display_message=MagicMock(return_value=TmuxCmdResult(0, "bash\n", "")),
                list_panes=MagicMock(return_value=["321"]),
            )
            executor.get_tmux_client = lambda host_name: tmux
            executor.log = MagicMock()
            executor.logger = SimpleNamespace(log_detail=MagicMock(), log_wait=MagicMock(), log_ssh=MagicMock())
            executor.ssh_max_retries = 1
            executor.ssh_retry_base_interval = 1
            executor.ssh_retry_max_interval = 2
            executor._resolve_window = MagicMock()
            executor._interpolate = lambda text: text
            executor.tmux_bridge = SimpleNamespace(get_pane=MagicMock(return_value=None))
            executor._wait_for_bridge_idle = MagicMock(return_value=(True, "idle"))
            helper = executor.wait_helper

            with patch.object(helper, "_run_remote_shell", return_value=SimpleNamespace(returncode=1, stdout="", stderr="")):
                self.assertFalse(helper.is_pane_idle("gpu", "sess"))
            with patch.object(helper, "_run_remote_shell", return_value=SimpleNamespace(returncode=0, stdout="bad", stderr="")):
                self.assertFalse(helper.is_pane_idle("gpu", "sess"))

            window = SimpleNamespace(name="main", host="local", remote_session="sess")
            with patch("trainsh.core.executor_wait.time.sleep"), patch.object(
                helper, "is_pane_idle", side_effect=[True, False]
            ), patch.object(helper, "get_pane_process_info", return_value=("bash", "")), patch.object(
                helper, "get_pane_recent_output", side_effect=RuntimeError("boom")
            ), patch("trainsh.core.executor_wait.time.time", side_effect=[0, 0, 10, 20, 5000, 5000]):
                ok, msg = helper.wait_for_idle(window, 4000)
            self.assertFalse(ok)
            self.assertTrue(executor.log.called)

            remote_window = SimpleNamespace(name="gpu", host="gpu", remote_session="sess")
            executor._resolve_window.return_value = remote_window
            with patch("trainsh.core.executor_wait.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="exists\n", stderr="")), patch(
                "trainsh.core.executor_wait.time.time",
                side_effect=[0, 0, 0, 1, 1],
            ):
                ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="", condition="file:/tmp/ready", timeout=4001))
            self.assertTrue(ok)

            executor._resolve_window.return_value = SimpleNamespace(name="gpu", host="gpu", remote_session=None)
            ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="done", condition="", timeout=5))
            self.assertFalse(ok)

            executor._resolve_window.return_value = remote_window
            with patch.object(helper, "host_from_ssh_spec", return_value=SimpleNamespace(hostname="remote")), patch(
                "trainsh.core.executor_wait.subprocess.run", side_effect=OSError("nc boom")
            ), patch("trainsh.core.executor_wait.time.time", side_effect=[0, 0, 0, 31, 31]), patch(
                "trainsh.core.executor_wait.time.sleep"
            ):
                ok, msg = helper.exec_wait(SimpleNamespace(target="gpu", pattern="", condition="port:8080", timeout=5))
            self.assertFalse(ok)

            executor._resolve_window.return_value = window
            with patch("trainsh.core.executor_wait.time.time", side_effect=[0, 0, 0, 31, 31]), patch(
                "trainsh.core.executor_wait.time.sleep"
            ):
                ok, msg = helper.exec_wait(SimpleNamespace(target="main", pattern="", condition="other", timeout=5))
            self.assertFalse(ok)

        job = JobState(
            job_id="job-123456",
            recipe_path="/tmp/demo.py",
            recipe_name="demo",
            current_step=1,
            total_steps=3,
            status="failed",
            variables={f"K{i}": f"V{i}" for i in range(12)},
            hosts={"gpu": "gpu-spec"},
            storages={"artifacts": "storage-spec"},
            window_sessions={"gpu": "sess-1"},
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:01:00",
        )
        summary = {
            "job_id": "job-123456",
            "recipe": "demo",
            "recipe_path": "/tmp/demo.py",
            "started": "2026-01-01T00:00:00",
            "ended": "2026-01-01T00:02:00",
            "success": False,
            "variables": {f"K{i}": f"VALUE-{i}" for i in range(12)},
            "hosts": {"gpu": "gpu-spec"},
            "storages": {"artifacts": "storage-spec"},
            "steps": [{"step_num": 1, "success": False, "duration_ms": 3, "error": "boom", "result": ""}],
            "recent_events": [{"ts": "2026-01-01T00:00:01", "event": "detail", "category": "info", "message": "hello"}],
        }
        reader = SimpleNamespace(
            list_executions=MagicMock(side_effect=[[{"job_id": "job-123456", "recipe": "demo", "started": "2026-01-01", "success": False, "host_count": 1, "storage_count": 1, "duration_ms": 5}], [], [{"job_id": "job-123456"}]]),
            get_execution_summary=MagicMock(return_value=summary),
            list_recent_events=MagicMock(return_value=[{"ts": "2026-01-01T00:00:02", "event": "execution_end", "success": False}]),
        )
        reader_ctx = MagicMock()
        reader_ctx.__enter__.return_value = reader
        reader_ctx.__exit__.return_value = False

        with patch("trainsh.core.execution_log.ExecutionLogReader", return_value=reader_ctx):
            output, code, _ = capture_output(recipe_views.cmd_logs, [])
            self.assertIn("failed", output)
            output, code, _ = capture_output(recipe_views.cmd_logs, ["--last"])
            self.assertIn("No execution logs found.", output)
            output, code, _ = capture_output(recipe_views.cmd_logs, ["job-123456"])
            self.assertIn("... and 2 more", output)
            self.assertIn("Error: boom", output)

        state_manager = SimpleNamespace(
            list_running=MagicMock(side_effect=[[job], [], [], []]),
            list_all=MagicMock(side_effect=[[job], [job], [], [job] * 20]),
            load=MagicMock(side_effect=[None, None]),
        )
        with patch("trainsh.core.job_state.JobStateManager", return_value=state_manager), patch(
            "trainsh.core.local_tmux.LocalTmuxClient",
            return_value=SimpleNamespace(build_attach_command=lambda session, nested=False: f"local:{session}:{nested}"),
        ), patch(
            "trainsh.core.remote_tmux.RemoteTmuxClient",
            return_value=SimpleNamespace(build_attach_command=lambda session, status_mode="keep": f"remote:{session}:{status_mode}"),
        ), patch("trainsh.core.tmux_session.session_exists", return_value=False):
            output, code, _ = capture_output(recipe_views.cmd_status, ["--help"])
            self.assertIn("train recipe status", output)
            output, code, _ = capture_output(recipe_views.cmd_status, ["--last"])
            self.assertIn("Job ID: job-123456", output)
            output, code, _ = capture_output(recipe_views.cmd_status, ["--last"])
            self.assertIn("No running jobs found. Showing latest job instead.", output)
            output, code, _ = capture_output(recipe_views.cmd_status, ["job-123"])
            self.assertIn("Job ID: job-123456", output)
            output, code, _ = capture_output(recipe_views.cmd_status, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Job not found", output)
            output, code, _ = capture_output(recipe_views.cmd_jobs, ["--help"])
            self.assertIn("train recipe jobs", output)
            output, code, _ = capture_output(recipe_views.cmd_jobs, [])
            self.assertIn("Use '--all' to show all jobs.", output)

        stream = io.StringIO()
        with redirect_stdout(stream):
            recipe_views._show_attach_commands(
                JobState(
                    job_id="job-empty",
                    recipe_path="/tmp/empty.py",
                    recipe_name="empty",
                    hosts={},
                )
            )
        self.assertEqual(stream.getvalue(), "")

    def test_executor_main_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "trainsh.core.executor_main.CONFIG_DIR", Path(tmpdir)
        ), patch("trainsh.runtime.CONFIG_DIR", Path(tmpdir)), patch(
            "trainsh.core.executor_main.load_config",
            return_value={
                "tmux": {"auto_bridge": False, "bridge_remote_status": "weird"},
                "notifications": {
                    "enabled": "not-a-bool",
                    "channels": "bad-channel",
                    "timeout_secs": "bad",
                    "fail_on_error": "bad",
                },
            },
        ):
            recipe = RecipeModel(name="main")
            executor = DSLExecutor(recipe, log_callback=lambda *_args, **_kwargs: None)
            try:
                executor.recipe_path = "/tmp/demo.py"
                window = SimpleNamespace(host="gpu", remote_session="sess-1")
                executor.ctx.windows["main"] = window
                executor._save_checkpoint(0)
                self.assertEqual(executor.job_state.hosts["main"], "gpu")
                self.assertEqual(executor.job_state.window_sessions["main"], "sess-1")
                self.assertIsNotNone(executor._load_checkpoint(executor.ctx.job_id))

                executor.callback_manager.emit = MagicMock()
                executor._emit_event("detail", try_number="bad")
                payload = executor.callback_manager.emit.call_args.args[0]
                self.assertEqual(payload.try_number, 1)

                executor._step_runtime_ctx.step_num = "bad"
                executor._step_runtime_ctx.try_number = "bad"
                self.assertEqual(executor._current_step_num(), 0)
                self.assertEqual(executor._current_try_number(), 1)

                with patch.object(executor, "_cmd_notify", return_value=(True, "ok")):
                    self.assertEqual(executor._exec_control(SimpleNamespace(command="notify", args=["hello"])), (True, "ok"))
            finally:
                executor.close()

        class FakeRunner:
            def execute(self, fn):
                return fn()

        class FakeExecutor:
            last_init = None

            def __init__(self, recipe_obj, **kwargs):
                FakeExecutor.last_init = {"recipe": recipe_obj, **kwargs}
                self.ctx = SimpleNamespace(next_window_index=0, windows={})
                self.restore_tmux_bridge = MagicMock()

            def execute(self, resume_from=0):
                FakeExecutor.last_init["resume_from"] = resume_from
                return True

        class FakeManager:
            def __init__(self, _db_path):
                pass

            def find_resumable(self, _path):
                return JobState(
                    job_id="job-resume",
                    recipe_path="/tmp/demo.py",
                    recipe_name="demo",
                    current_step=1,
                    total_steps=3,
                    variables={"READY": "1"},
                    hosts={"gpu": "ssh.example"},
                    window_sessions={"gpu": ""},
                    next_window_index=4,
                    bridge_session="bridge-1",
                )

            def load(self, _job_id):
                return JobState(
                    job_id="job-resume",
                    recipe_path="/tmp/demo.py",
                    recipe_name="demo",
                    current_step=1,
                    total_steps=3,
                    variables={"READY": "1"},
                    hosts={"gpu": "ssh.example", "plain": "local"},
                    window_sessions={"gpu": "", "plain": ""},
                    next_window_index=4,
                    bridge_session="bridge-1",
                )

        logs = []
        fake_recipe = SimpleNamespace(
            name="demo",
            steps=[],
            variables={},
            hosts={},
            executor="",
            executor_kwargs={},
            callbacks=[],
        )
        with patch("trainsh.pyrecipe.load_python_recipe", return_value=fake_recipe), patch(
            "trainsh.core.executor_main.DSLExecutor", FakeExecutor
        ), patch("trainsh.runtime.get_executor", return_value=FakeRunner()), patch(
            "trainsh.runtime.build_sinks", return_value=[]
        ), patch("trainsh.runtime.JsonlCallbackSink", return_value="jsonl-sink"), patch(
            "trainsh.core.executor_main.JobStateManager", FakeManager
        ):
            ok = run_recipe(
                "/tmp/demo.pyrecipe",
                log_callback=logs.append,
                resume=True,
                callbacks=["", "console, jsonl"],
            )
        self.assertTrue(ok)
        self.assertEqual(FakeExecutor.last_init["executor_name"], "sequential")
        self.assertEqual(FakeExecutor.last_init["resume_from"], 1)
        self.assertIn("Found saved state", logs[0])
        self.assertTrue(FakeExecutor.last_init["callback_sinks"])

        class EmptyManager:
            def __init__(self, _db_path):
                pass

            def find_resumable(self, _path):
                return None

        override_recipe = SimpleNamespace(
            name="override",
            steps=[],
            variables={},
            hosts={},
            executor="",
            executor_kwargs={},
            callbacks=[],
        )
        with patch("trainsh.pyrecipe.load_python_recipe", return_value=override_recipe), patch(
            "trainsh.core.executor_main.DSLExecutor", FakeExecutor
        ), patch("trainsh.runtime.get_executor", return_value=FakeRunner()), patch(
            "trainsh.runtime.build_sinks", return_value=[]
        ), patch("trainsh.runtime.JsonlCallbackSink", return_value="jsonl-sink"), patch(
            "trainsh.core.executor_main.JobStateManager", EmptyManager
        ):
            ok = run_recipe("/tmp/override.pyrecipe", host_overrides={"plain": "local"})
        self.assertTrue(ok)
        self.assertEqual(FakeExecutor.last_init["recipe"].hosts["plain"], "local")

        fresh_logs = []
        fresh_recipe = SimpleNamespace(
            name="fresh",
            steps=[],
            variables={},
            hosts={},
            executor="",
            executor_kwargs={},
            callbacks=[],
        )
        with patch("trainsh.pyrecipe.load_python_recipe", return_value=fresh_recipe), patch(
            "trainsh.core.executor_main.DSLExecutor", FakeExecutor
        ), patch("trainsh.runtime.get_executor", return_value=FakeRunner()), patch(
            "trainsh.runtime.build_sinks", return_value=[]
        ), patch("trainsh.runtime.JsonlCallbackSink", return_value="jsonl-sink"), patch(
            "trainsh.core.executor_main.JobStateManager", EmptyManager
        ):
            ok = run_recipe("/tmp/fresh.pyrecipe", log_callback=fresh_logs.append, resume=True)
        self.assertTrue(ok)
        self.assertIn("starting fresh", fresh_logs[0])


if __name__ == "__main__":
    unittest.main()
