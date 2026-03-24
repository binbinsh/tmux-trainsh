import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.core.models import Storage as RuntimeStorage, StorageType
from trainsh.core.recipe_models import RecipeModel
from trainsh.pyrecipe.models import ProviderStep

from tests.runtime_test_utils import isolated_executor


class ExecutorMainProviderTests(unittest.TestCase):
    def test_provider_host_and_http_helpers(self):
        with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
            executor.recipe.hosts["gpu"] = "local"
            self.assertEqual(executor._provider_host(None), "local")
            self.assertEqual(executor._provider_host("gpu"), "local")
            self.assertEqual(executor._provider_host("@gpu"), "local")

            ok, err, headers = executor._coerce_http_headers({"A": 1, "B": None})
            self.assertTrue(ok)
            self.assertEqual(headers, {"A": "1", "B": ""})
            ok, err, _ = executor._coerce_http_headers("bad")
            self.assertFalse(ok)
            self.assertIn("headers must be an object", err)

            ok, err, statuses = executor._coerce_http_statuses("200, 201")
            self.assertTrue(ok)
            self.assertEqual(statuses, [200, 201])
            ok, err, statuses = executor._coerce_http_statuses([200, 202])
            self.assertTrue(ok)
            self.assertEqual(statuses, [200, 202])
            ok, err, _ = executor._coerce_http_statuses(True)
            self.assertFalse(ok)

            with patch.object(executor, "_http_request_once", return_value=(True, 200, "ok", "")):
                ok, msg = executor._exec_provider_http_request({"url": "https://example.test", "capture_var": "BODY"})
            self.assertTrue(ok)
            self.assertEqual(executor.ctx.variables["BODY"], "ok")

            with patch.object(executor, "_http_request_once", return_value=(False, 500, "boom", "error")):
                ok, msg = executor._exec_provider_http_request({"url": "https://example.test"})
            self.assertFalse(ok)
            self.assertIn("status 500", msg)

            with patch.object(executor, "_http_request_once", side_effect=[(False, None, "", "offline"), (True, 200, "ok", "")]), patch(
                "trainsh.core.executor_main.time.time", side_effect=[0, 0, 1, 1]
            ), patch("trainsh.core.executor_main.time.sleep"):
                ok, msg = executor._exec_provider_http_wait(
                    {"url": "https://example.test", "timeout": "5s", "poll_interval": "1s", "expected_status": 200}
                )
            self.assertTrue(ok)
            self.assertIn("matched", msg)

            with patch.object(executor, "_http_request_once", return_value=(False, None, "", "offline")), patch(
                "trainsh.core.executor_main.time.time", side_effect=[0, 10]
            ), patch("trainsh.core.executor_main.time.sleep"):
                ok, msg = executor._exec_provider_http_wait(
                    {"url": "https://example.test", "timeout": "5s", "poll_interval": "1s", "expected_status": 200}
                )
            self.assertFalse(ok)
            self.assertIn("Timeout waiting for HTTP condition", msg)

    def test_storage_and_xcom_provider_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_root = Path(tmpdir) / "storage"
            storage_root.mkdir()
            (storage_root / "hello.txt").write_text("hello world", encoding="utf-8")
            db_path = Path(tmpdir) / "runtime.db"

            recipe = RecipeModel(name="providers", storages={"artifacts": RuntimeStorage(name="artifacts", type=StorageType.LOCAL, config={"path": str(storage_root)})})
            with isolated_executor(recipe) as (executor, _config_dir):
                ok, msg = executor._exec_provider_storage_exists({"storage": "artifacts", "path": "/hello.txt"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_storage_info({"storage": "artifacts", "path": "/hello.txt"})
                self.assertTrue(ok)
                self.assertIn('"size"', msg)
                ok, msg = executor._exec_provider_storage_read_text({"storage": "artifacts", "path": "/hello.txt", "max_chars": 5})
                self.assertTrue(ok)
                self.assertEqual(msg, "hello")
                ok, msg = executor._exec_provider_storage_list({"storage": "artifacts", "path": "/", "recursive": False})
                self.assertTrue(ok)
                self.assertIn("hello.txt", msg)
                ok, msg = executor._exec_provider_storage_count({"storage": "artifacts", "path": "/", "capture_var": "COUNT"})
                self.assertTrue(ok)
                self.assertEqual(msg, "1")
                self.assertEqual(executor.ctx.variables["COUNT"], "1")
                ok, msg = executor._exec_provider_storage_wait_count(
                    {"storage": "artifacts", "path": "/", "exact_count": 1, "timeout": "1s", "poll_interval": "1s"}
                )
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_storage_mkdir({"storage": "artifacts", "path": "/nested"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_storage_rename({"storage": "artifacts", "source": "/hello.txt", "destination": "/renamed.txt"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_storage_delete({"storage": "artifacts", "path": "/renamed.txt"})
                self.assertTrue(ok)

                with patch.object(executor, "_exec_provider_transfer", return_value=(True, "copied")) as mocked_transfer:
                    ok, msg = executor._exec_provider_storage_upload({"storage": "artifacts", "source": "/tmp/in", "destination": "/out"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_download({"storage": "artifacts", "source": "/out", "destination": "/tmp/local"})
                    self.assertTrue(ok)
                self.assertEqual(mocked_transfer.call_count, 2)

                ok, msg = executor._exec_provider_xcom_push(
                    {"key": "rows", "value": {"a": 1}, "database": str(db_path), "task_id": "push"}
                )
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_xcom_pull(
                    {"key": "rows", "database": str(db_path), "task_ids": ["push"], "decode_json": True, "output_var": "ROWS"}
                )
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["ROWS"], '{"a": 1}')

                ok, msg = executor._exec_provider_xcom_pull(
                    {"key": "missing", "database": str(db_path), "default": {"fallback": True}, "output_var": "MISS"}
                )
                self.assertTrue(ok)
                self.assertIn("fallback", executor.ctx.variables["MISS"])

    def test_condition_var_shell_cost_and_latest_only_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "runtime.db"
            with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
                executor.recipe_path = "/tmp/providers.py"
                executor.ctx.start_time = __import__("datetime").datetime.now()
                executor.ctx.job_id = "job-1"
                executor.ctx.variables["READY"] = "1"

                ok, msg = executor._exec_provider_wait_condition({"condition": "var:READY==1", "timeout": "5s", "poll_interval": "1s"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_branch({"condition": "var:READY==1", "variable": "BRANCH", "true_value": "go", "false_value": "stop"})
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["BRANCH"], "go")
                ok, msg = executor._exec_provider_branch(
                    {"condition": "var:READY==1", "variable": "BRANCH_ARG", "true_value": "--resume-from-step=${READY}", "false_value": ""}
                )
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["BRANCH_ARG"], "--resume-from-step=1")
                ok, msg = executor._exec_provider_short_circuit({"condition": "var:READY==1"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_short_circuit({"condition": "var:MISSING", "message": "blocked"})
                self.assertFalse(ok)
                self.assertIn("blocked", msg)
                ok, msg = executor._exec_provider_fail({"message": "boom", "exit_code": 2})
                self.assertFalse(ok)
                self.assertIn("exit_code=2", msg)

                with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")):
                    ok, msg = executor._exec_provider_shell({"command": "echo hi", "timeout": "5s"})
                self.assertTrue(ok)

                ok, msg = executor._exec_provider_shell({"command": "echo hi", "env": "bad"})
                self.assertFalse(ok)
                self.assertIn("env must be an object", msg)

                class FakeSocket:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")) as mocked_shell, patch(
                    "trainsh.core.executor_main.socket.create_connection", return_value=FakeSocket()
                ):
                    ok, msg = executor._exec_provider_ssh_command({"host": "gpu", "command": "echo hi", "timeout": "5s"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_uv_run({"command": "python train.py", "packages": ["rich"], "host": "gpu", "timeout": "5s"})
                    self.assertTrue(ok)
                self.assertEqual(mocked_shell.call_count, 2)

                fake_rates = SimpleNamespace(
                    rates={"USD": 1.0, "CNY": 7.0},
                    base="USD",
                    updated_at="now",
                    convert=lambda amount, _from, _to: amount,
                )
                fake_settings = SimpleNamespace(exchange_rates=fake_rates, display_currency="USD")
                with patch("trainsh.services.pricing.fetch_exchange_rates", return_value=fake_rates), patch(
                    "trainsh.services.pricing.load_pricing_settings", return_value=fake_settings
                ), patch("trainsh.services.pricing.save_pricing_settings"):
                    ok, msg = executor._exec_provider_fetch_exchange_rates({})
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["rate_usd"], "1.0")

                with patch("trainsh.services.pricing.load_pricing_settings", return_value=fake_settings), patch(
                    "trainsh.services.pricing.calculate_host_cost",
                    return_value=SimpleNamespace(total_per_hour_usd=1.5, total_per_day_usd=36.0, total_per_month_usd=1080.0),
                ), patch("trainsh.services.pricing.format_currency", side_effect=lambda amount, currency: f"{currency}{amount:.2f}"):
                    ok, msg = executor._exec_provider_calculate_cost({"gpu_hourly_usd": 1.5, "currency": "USD"})
                self.assertTrue(ok)
                self.assertIn("USD1.50", msg)

                ok, msg = executor._exec_provider_latest_only({"runtime_state": str(Path(tmpdir) / "missing"), "fail_if_unknown": False})
                self.assertTrue(ok)

                from trainsh.core.runtime_store import RuntimeStore

                RuntimeStore(db_path).append_run(
                    {
                        "run_id": "job-2",
                        "dag_id": "providers",
                        "recipe_name": "providers",
                        "recipe_path": "/tmp/providers.pyrecipe",
                        "state": "success",
                        "status": "succeeded",
                        "started_at": "9999-01-01T00:00:00",
                        "updated_at": "9999-01-01T00:00:00",
                    }
                )
                ok, msg = executor._exec_provider_latest_only({"runtime_state": str(db_path), "message": "skip latest"})
                self.assertFalse(ok)
                self.assertEqual(msg, "skip latest")

    def test_more_provider_wrappers_and_conditions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_file = Path(tmpdir) / "ready.txt"
            local_file.write_text("ready\n", encoding="utf-8")
            with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
                executor.ctx.variables["VALUE"] = "42"
                executor._resolve_host = lambda value: "local"

                class LocalSocket:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")) as mocked_shell, patch(
                    "trainsh.core.executor_main.socket.create_connection", return_value=LocalSocket()
                ):
                    ok, msg = executor._exec_provider_git_clone({"repo_url": "https://example.com/repo.git", "destination": "/tmp/repo", "branch": "main", "depth": 1, "host": "gpu"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_git_pull({"directory": "/tmp/repo", "remote": "origin", "branch": "main"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_wait_for_file({"path": str(local_file), "timeout": 1, "poll_interval": 1})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_wait_for_port({"port": 8080, "host_name": "localhost", "timeout": 1, "poll_interval": 1})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_python({"code": "print(1)"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_python({"script": "script.py"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_python({"command": "print(1)"})
                    self.assertTrue(ok)
                self.assertGreaterEqual(mocked_shell.call_count, 5)

                executor._resolve_host = lambda value: "gpu"
                with patch.object(executor, "_verify_ssh_connection", return_value=True):
                    ok, msg = executor._exec_provider_host_test({"host": "gpu", "capture_var": "PING"})
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["PING"], "1")

                with patch.object(executor, "_verify_ssh_connection", return_value=False):
                    ok, msg = executor._exec_provider_host_test({"host": "gpu"})
                self.assertFalse(ok)

                executor._resolve_host = lambda value: "local"
                ok, msg = executor._exec_provider_assert({"condition": "var:VALUE==42", "message": "bad"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_assert({"condition": "var:MISSING", "message": "bad"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_assert({"condition": f"file:{local_file}", "message": "bad"})
                self.assertTrue(ok)

                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")):
                    ok, msg = executor._exec_provider_assert({"condition": "command:echo ok", "message": "bad"})
                self.assertTrue(ok)

                ok, msg = executor._exec_provider_get_value({"target": "HOME", "source": "var:VALUE"})
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["HOME"], "42")
                with patch.dict(os.environ, {"TMP_FLAG": "1"}):
                    ok, msg = executor._exec_provider_get_value({"target": "FLAG", "source": "env:TMP_FLAG"})
                self.assertTrue(ok)
                with patch.object(executor.secrets, "get", return_value="secret"):
                    ok, msg = executor._exec_provider_get_value({"target": "TOKEN", "source": "secret:MY_TOKEN"})
                self.assertTrue(ok)
                with patch.object(executor, "_exec_provider_shell", return_value=(True, "value")):
                    ok, msg = executor._exec_provider_get_value({"target": "CMD", "source": "command:echo hi"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_get_value({"target": "BAD", "source": "other:bad"})
                self.assertFalse(ok)

    def test_github_clone_uses_token_without_mutating_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "github.token"
            token_file.write_text("ghs_demo\n", encoding="utf-8")
            with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
                with patch(
                    "trainsh.core.provider_shell.materialize_secret_file",
                    return_value=str(token_file),
                ), patch(
                    "trainsh.core.provider_shell.materialize_git_askpass_script",
                    return_value="/tmp/trainsh-askpass.sh",
                ), patch.object(
                    executor,
                    "_exec_provider_shell",
                    return_value=(True, "fallback"),
                ) as shell_mock, patch(
                    "subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="cloned", stderr=""),
                ) as run_mock:
                    ok, msg = executor._exec_provider_git_clone(
                        {
                            "repo_url": "https://github.com/example/private-repo.git",
                            "destination": "/tmp/repo",
                            "branch": "main",
                            "depth": 1,
                        }
                    )
                self.assertTrue(ok)
                self.assertEqual(msg, "cloned")
                shell_mock.assert_not_called()
                command = run_mock.call_args.args[0]
                env = run_mock.call_args.kwargs["env"]
                self.assertIn("git clone", command)
                self.assertIn("https://github.com/example/private-repo.git", command)
                self.assertEqual(env["GIT_ASKPASS"], "/tmp/trainsh-askpass.sh")
                self.assertEqual(env["TRAINSH_GIT_PASSWORD_FILE"], str(token_file))
                self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
                self.assertTrue(run_mock.call_args.kwargs["shell"])

    def test_github_clone_plain_auth_skips_token_lookup(self):
        with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
            with patch(
                "trainsh.core.provider_shell.materialize_secret_file",
                return_value="/tmp/github.token",
            ) as secret_mock, patch.object(
                executor,
                "_exec_provider_shell",
                return_value=(True, "plain ok"),
            ) as shell_mock:
                ok, msg = executor._exec_provider_git_clone(
                    {
                        "repo_url": "https://github.com/example/private-repo.git",
                        "destination": "/tmp/repo",
                        "auth": "plain",
                    }
                )
            self.assertTrue(ok)
            self.assertEqual(msg, "plain ok")
            secret_mock.assert_not_called()
            shell_mock.assert_called_once()

    def test_github_clone_explicit_token_auth_requires_secret(self):
        with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
            with patch(
                "trainsh.core.provider_shell.materialize_secret_file",
                return_value=None,
            ):
                ok, msg = executor._exec_provider_git_clone(
                    {
                        "repo_url": "https://github.com/example/private-repo.git",
                        "auth": "github_token",
                        "token_secret": "PRIVATE_GITHUB_TOKEN",
                    }
                )
            self.assertFalse(ok)
            self.assertIn("PRIVATE_GITHUB_TOKEN", msg)

    def test_github_clone_uses_token_over_ssh_without_logging_secret(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_file = Path(tmpdir) / "github.token"
            token_file.write_text("ghs_demo\n", encoding="utf-8")
            with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
                with patch(
                    "trainsh.core.provider_shell.materialize_secret_file",
                    return_value=str(token_file),
                ), patch(
                    "trainsh.core.provider_shell.build_remote_git_auth_command",
                    return_value="REMOTE_AUTH_CMD",
                ) as remote_cmd_mock, patch(
                    "trainsh.core.provider_shell._build_ssh_args",
                    return_value=["ssh", "gpu", "REMOTE_AUTH_CMD"],
                ) as ssh_args_mock, patch.object(
                    executor,
                    "_exec_provider_shell",
                    return_value=(True, "fallback"),
                ) as shell_mock, patch(
                    "subprocess.run",
                    return_value=SimpleNamespace(returncode=0, stdout="", stderr="remote ok"),
                ) as run_mock:
                    ok, msg = executor._exec_provider_git_clone(
                        {
                            "repo_url": "https://github.com/example/private-repo.git",
                            "destination": "/tmp/repo",
                            "host": "gpu",
                        }
                    )
                self.assertTrue(ok)
                self.assertEqual(msg, "remote ok")
                shell_mock.assert_not_called()
                remote_cmd_mock.assert_called_once()
                ssh_args_mock.assert_called_once_with("gpu", command="REMOTE_AUTH_CMD", tty=False)
                self.assertEqual(run_mock.call_args.args[0], ["ssh", "gpu", "REMOTE_AUTH_CMD"])
                self.assertEqual(run_mock.call_args.kwargs["input"], "ghs_demo\n")

                ok, msg = executor._exec_provider_set_env({"name": "TRAINSH_TEST_ENV", "value": "1"})
                self.assertTrue(ok)
                self.assertEqual(os.environ["TRAINSH_TEST_ENV"], "1")
                ok, msg = executor._exec_provider_set_env({"name": ""})
                self.assertFalse(ok)

                with patch.object(executor.notifier, "notify", return_value=(True, "sent")):
                    ok, msg = executor._exec_provider_notice({"message": "hello", "channels": ["log"]})
                self.assertTrue(ok)
                self.assertEqual(msg, "sent")
                executor.notify_enabled = False
                ok, msg = executor._exec_provider_notice({"message": "hello"})
                self.assertTrue(ok)
                self.assertIn("skipped", msg)
                executor.notify_enabled = True
                ok, msg = executor._exec_provider_notice({"message": ""})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_empty({})
                self.assertTrue(ok)

    def test_exec_provider_routing_and_error_paths(self):
        with isolated_executor(RecipeModel(name="providers")) as (executor, _config_dir):
            with ExitStack() as stack:
                mocked_notice = stack.enter_context(patch.object(executor, "_exec_provider_notice", return_value=(True, "notice")))
                mocked_python = stack.enter_context(patch.object(executor, "_exec_provider_python", return_value=(True, "python")))
                mocked_clone = stack.enter_context(patch.object(executor, "_exec_provider_git_clone", return_value=(True, "clone")))
                mocked_pull = stack.enter_context(patch.object(executor, "_exec_provider_git_pull", return_value=(True, "pull")))
                mocked_host = stack.enter_context(patch.object(executor, "_exec_provider_host_test", return_value=(True, "host")))
                mocked_assert = stack.enter_context(patch.object(executor, "_exec_provider_assert", return_value=(True, "assert")))
                mocked_get = stack.enter_context(patch.object(executor, "_exec_provider_get_value", return_value=(True, "value")))
                mocked_env = stack.enter_context(patch.object(executor, "_exec_provider_set_env", return_value=(True, "env")))
                mocked_wait_file = stack.enter_context(patch.object(executor, "_exec_provider_wait_for_file", return_value=(True, "file")))
                mocked_wait_port = stack.enter_context(patch.object(executor, "_exec_provider_wait_for_port", return_value=(True, "port")))
                mocked_empty = stack.enter_context(patch.object(executor, "_exec_provider_empty", return_value=(True, "noop")))
                mocked_vast = stack.enter_context(patch.object(executor, "_exec_provider_vast", return_value=(True, "vast")))
                mocked_shell = stack.enter_context(patch.object(executor, "_exec_provider_shell", return_value=(True, "shell")))
                mocked_http = stack.enter_context(patch.object(executor, "_exec_provider_http_request", return_value=(True, "http")))
                mocked_http_wait = stack.enter_context(patch.object(executor, "_exec_provider_http_wait", return_value=(True, "http_wait")))
                mocked_upload = stack.enter_context(patch.object(executor, "_exec_provider_storage_upload", return_value=(True, "upload")))
                mocked_download = stack.enter_context(patch.object(executor, "_exec_provider_storage_download", return_value=(True, "download")))
                mocked_storage_list = stack.enter_context(patch.object(executor, "_exec_provider_storage_list", return_value=(True, "list")))
                mocked_storage_exists = stack.enter_context(patch.object(executor, "_exec_provider_storage_exists", return_value=(True, "exists")))
                mocked_storage_count = stack.enter_context(patch.object(executor, "_exec_provider_storage_count", return_value=(True, "count")))
                mocked_storage_read = stack.enter_context(patch.object(executor, "_exec_provider_storage_read_text", return_value=(True, "read")))
                mocked_storage_info = stack.enter_context(patch.object(executor, "_exec_provider_storage_info", return_value=(True, "info")))
                mocked_storage_wait = stack.enter_context(patch.object(executor, "_exec_provider_storage_wait", return_value=(True, "wait")))
                mocked_storage_wait_count = stack.enter_context(patch.object(executor, "_exec_provider_storage_wait_count", return_value=(True, "wait_count")))
                mocked_storage_mkdir = stack.enter_context(patch.object(executor, "_exec_provider_storage_mkdir", return_value=(True, "mkdir")))
                mocked_storage_bucket = stack.enter_context(patch.object(executor, "_exec_provider_storage_ensure_bucket", return_value=(True, "bucket")))
                mocked_storage_delete = stack.enter_context(patch.object(executor, "_exec_provider_storage_delete", return_value=(True, "delete")))
                mocked_storage_rename = stack.enter_context(patch.object(executor, "_exec_provider_storage_rename", return_value=(True, "rename")))
                mocked_transfer = stack.enter_context(patch.object(executor, "_exec_provider_transfer", return_value=(True, "transfer")))
                mocked_set_var = stack.enter_context(patch.object(executor, "_exec_provider_set_var", return_value=(True, "set_var")))
                mocked_xpush = stack.enter_context(patch.object(executor, "_exec_provider_xcom_push", return_value=(True, "xpush")))
                mocked_xpull = stack.enter_context(patch.object(executor, "_exec_provider_xcom_pull", return_value=(True, "xpull")))
                mocked_rates = stack.enter_context(patch.object(executor, "_exec_provider_fetch_exchange_rates", return_value=(True, "rates")))
                mocked_cost = stack.enter_context(patch.object(executor, "_exec_provider_calculate_cost", return_value=(True, "cost")))
                mocked_wait_condition = stack.enter_context(patch.object(executor, "_exec_provider_wait_condition", return_value=(True, "cond")))
                mocked_ssh = stack.enter_context(patch.object(executor, "_exec_provider_ssh_command", return_value=(True, "ssh")))
                mocked_uv = stack.enter_context(patch.object(executor, "_exec_provider_uv_run", return_value=(True, "uv")))
                mocked_fail = stack.enter_context(patch.object(executor, "_exec_provider_fail", return_value=(False, "fail")))
                mocked_latest = stack.enter_context(patch.object(executor, "_exec_provider_latest_only", return_value=(True, "latest")))
                def step(provider, operation, params=None, sid="s"):
                    return SimpleNamespace(provider=provider, operation=operation, params=params or {}, id=sid)

                self.assertEqual(executor._exec_provider(step("shell", "run")), (True, "shell"))
                self.assertEqual(executor._exec_provider(step("bash", "bash")), (True, "shell"))
                self.assertEqual(executor._exec_provider(step("bash", "local")), (True, "shell"))
                self.assertEqual(executor._exec_provider(step("python", "run")), (True, "python"))
                self.assertEqual(executor._exec_provider(step("git", "clone")), (True, "clone"))
                self.assertEqual(executor._exec_provider(step("git", "pull")), (True, "pull"))
                self.assertEqual(executor._exec_provider(step("host", "test")), (True, "host"))
                self.assertEqual(executor._exec_provider(step("util", "assert")), (True, "assert"))
                self.assertEqual(executor._exec_provider(step("util", "get_value")), (True, "value"))
                self.assertEqual(executor._exec_provider(step("util", "set_env")), (True, "env"))
                self.assertEqual(executor._exec_provider(step("util", "wait_file")), (True, "file"))
                self.assertEqual(executor._exec_provider(step("util", "wait_port")), (True, "port"))
                self.assertEqual(executor._exec_provider(step("util", "empty")), (True, "noop"))
                self.assertEqual(executor._exec_provider(step("vast", "start")), (True, "vast"))
                self.assertEqual(executor._exec_provider(step("email", "send", {"message": "x"})), (True, "notice"))
                self.assertEqual(executor._exec_provider(step("http", "get")), (True, "http"))
                self.assertEqual(executor._exec_provider(step("http", "json", {"json_body": {"ok": True}})), (True, "http"))
                self.assertEqual(executor._exec_provider(step("http", "sensor")), (True, "http_wait"))
                self.assertEqual(executor._exec_provider(step("http", "http")), (True, "http"))
                self.assertEqual(executor._exec_provider(step("cloud", "put", {"bucket": "artifacts"})), (True, "upload"))
                self.assertEqual(executor._exec_provider(step("cloud", "get", {"storage": "artifacts"})), (True, "download"))
                self.assertEqual(executor._exec_provider(step("cloud", "ls", {"storage": "artifacts"})), (True, "list"))
                self.assertEqual(executor._exec_provider(step("cloud", "check", {"storage": "artifacts"})), (True, "exists"))
                self.assertEqual(executor._exec_provider(step("cloud", "count", {"storage": "artifacts"})), (True, "count"))
                self.assertEqual(executor._exec_provider(step("cloud", "cat", {"storage": "artifacts"})), (True, "read"))
                self.assertEqual(executor._exec_provider(step("cloud", "stat", {"storage": "artifacts"})), (True, "info"))
                self.assertEqual(executor._exec_provider(step("cloud", "wait_for", {"storage": "artifacts"})), (True, "wait"))
                self.assertEqual(executor._exec_provider(step("cloud", "wait_count", {"storage": "artifacts"})), (True, "wait_count"))
                self.assertEqual(executor._exec_provider(step("cloud", "mkdir", {"storage": "artifacts"})), (True, "mkdir"))
                self.assertEqual(executor._exec_provider(step("cloud", "ensure_bucket", {"storage": "artifacts"})), (True, "bucket"))
                self.assertEqual(executor._exec_provider(step("cloud", "rm", {"storage": "artifacts"})), (True, "delete"))
                self.assertEqual(executor._exec_provider(step("cloud", "mv", {"storage": "artifacts"})), (True, "rename"))
                self.assertEqual(executor._exec_provider(step("cloud", "transfer", {"storage": "artifacts"})), (True, "transfer"))
                self.assertEqual(executor._exec_provider(step("util", "fetch_exchange_rates")), (True, "rates"))
                self.assertEqual(executor._exec_provider(step("util", "calculate_cost")), (True, "cost"))
                self.assertEqual(executor._exec_provider(step("util", "wait_condition")), (True, "cond"))
                self.assertFalse(executor._exec_provider(step("sqlite", "select"))[0])
                self.assertFalse(executor._exec_provider(step("sqlite", "execute"))[0])
                self.assertFalse(executor._exec_provider(step("sqlite", "script"))[0])
                self.assertEqual(executor._exec_provider(step("util", "ssh_command")), (True, "ssh"))
                self.assertEqual(executor._exec_provider(step("util", "uv_run")), (True, "uv"))
                self.assertEqual(executor._exec_provider(step("storage", "upload")), (True, "upload"))
                self.assertEqual(executor._exec_provider(step("storage", "download")), (True, "download"))
                self.assertEqual(executor._exec_provider(step("storage", "ls")), (True, "list"))
                self.assertEqual(executor._exec_provider(step("storage", "check")), (True, "exists"))
                self.assertEqual(executor._exec_provider(step("storage", "count")), (True, "count"))
                self.assertEqual(executor._exec_provider(step("storage", "cat")), (True, "read"))
                self.assertEqual(executor._exec_provider(step("storage", "stat")), (True, "info"))
                self.assertEqual(executor._exec_provider(step("storage", "wait")), (True, "wait"))
                self.assertEqual(executor._exec_provider(step("storage", "wait_count")), (True, "wait_count"))
                self.assertEqual(executor._exec_provider(step("storage", "mkdir")), (True, "mkdir"))
                self.assertEqual(executor._exec_provider(step("storage", "ensure_bucket")), (True, "bucket"))
                self.assertEqual(executor._exec_provider(step("storage", "delete")), (True, "delete"))
                self.assertEqual(executor._exec_provider(step("storage", "rename")), (True, "rename"))
                self.assertEqual(executor._exec_provider(step("storage", "copy")), (True, "transfer"))
                self.assertEqual(executor._exec_provider(step("util", "set_var")), (True, "set_var"))
                self.assertEqual(executor._exec_provider(step("util", "xcom_push")), (True, "xpush"))
                self.assertEqual(executor._exec_provider(step("util", "xcom_pull")), (True, "xpull"))
                self.assertEqual(executor._exec_provider(step("util", "fail")), (False, "fail"))
                self.assertEqual(executor._exec_provider(step("util", "latest_only")), (True, "latest"))

                ok, msg = executor._exec_provider(SimpleNamespace(provider="", operation="run", params={}, id="s"))
                self.assertFalse(ok)
                ok, msg = executor._exec_provider(SimpleNamespace(provider="shell", operation="", params={}, id="s"))
                self.assertFalse(ok)
                ok, msg = executor._exec_provider(SimpleNamespace(provider="unknown", operation="run", params={}, id="s"))
                self.assertFalse(ok)
                self.assertIn("Unsupported provider step", msg)

                mocked_notice.assert_called()
                mocked_python.assert_called()
                mocked_clone.assert_called()
                mocked_shell.assert_called()
                mocked_http.assert_called()
                mocked_upload.assert_called()

    def test_more_provider_error_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe = RecipeModel(
                name="providers",
                storages={"artifacts": RuntimeStorage(name="artifacts", type=StorageType.LOCAL, config={"path": str(Path(tmpdir) / 'storage')})},
            )
            Path(tmpdir, "storage").mkdir()
            with isolated_executor(recipe) as (executor, _config_dir):
                self.assertFalse(executor._exec_provider(ProviderStep("sqlite", "select", {"sql": "select 1"}, id="q"))[0])
                self.assertFalse(executor._exec_provider(ProviderStep("sqlite", "execute", {"sql": "select 1"}, id="e"))[0])
                self.assertFalse(executor._exec_provider(ProviderStep("sqlite", "script", {"script": "select 1;"}, id="s"))[0])

                ok, msg = executor._exec_provider_storage_wait({"storage": "artifacts", "path": "/missing", "timeout": "1s", "poll_interval": "1s"})
                self.assertFalse(ok)
                self.assertIn("Timeout waiting storage path", msg)
                ok, msg = executor._exec_provider_storage_info({"storage": "artifacts", "path": "/missing"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_read_text({"storage": "artifacts", "path": "/missing"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_list({"storage": "artifacts", "path": "/missing"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_delete({"storage": "artifacts", "path": "/missing"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_rename({"storage": "artifacts", "source": "", "destination": "/b"})
                self.assertFalse(ok)

                with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=False):
                    storage = executor._resolve_storage("artifacts")
                    ok, msg = executor._exec_storage_rclone(storage, ["ls", "artifacts:/"])
                self.assertFalse(ok)
                self.assertIn("rclone is required", msg)

                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")):
                    ok, msg = executor._exec_provider_hf_download({"repo_id": "repo/name", "filename": "f.bin", "filenames": ["a", "b"], "host": "local"})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_hf_download({"repo_id": ""})
                self.assertFalse(ok)

                with patch("trainsh.services.pricing.fetch_exchange_rates", side_effect=RuntimeError("boom")):
                    ok, msg = executor._exec_provider_fetch_exchange_rates({})
                self.assertFalse(ok)
                self.assertIn("boom", msg)

                fake_rates = SimpleNamespace(
                    rates={"USD": 1.0},
                    base="USD",
                    updated_at="now",
                    convert=lambda amount, _from, _to: amount,
                )
                fake_settings = SimpleNamespace(exchange_rates=fake_rates, display_currency="USD")
                vast_instance = SimpleNamespace(id=7, dph_total=1.5, gpu_name="A100")
                with patch("trainsh.services.pricing.load_pricing_settings", return_value=fake_settings), patch(
                    "trainsh.services.pricing.calculate_host_cost",
                    side_effect=lambda **kwargs: SimpleNamespace(total_per_hour_usd=kwargs["gpu_hourly_usd"], total_per_day_usd=kwargs["gpu_hourly_usd"] * 24, total_per_month_usd=kwargs["gpu_hourly_usd"] * 24 * 30),
                ), patch("trainsh.services.pricing.format_currency", side_effect=lambda amount, currency: f"{currency}{amount:.2f}"), patch(
                    "trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(list_instances=lambda: [vast_instance])
                ):
                    ok, msg = executor._exec_provider_calculate_cost({"vast": True, "currency": "USD"})
                self.assertTrue(ok)
                self.assertIn("USD1.50", msg)

                with patch.object(executor, "_exec_provider_shell", return_value=(True, "exists")):
                    ok, msg = executor._eval_condition("file_exists:/tmp/x", host="gpu")
                self.assertTrue(ok)
                with patch.object(executor, "_exec_provider_shell", return_value=(True, "found")):
                    ok, msg = executor._eval_condition("file_contains:/tmp/x:needle", host="gpu")
                self.assertTrue(ok)
                with patch.object(executor, "_exec_provider_storage_exists", return_value=(True, "ok")):
                    ok, msg = executor._eval_condition("storage_exists:artifacts:/tmp/x")
                self.assertTrue(ok)
                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")):
                    ok, msg = executor._eval_condition("command:echo ok")
                self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
