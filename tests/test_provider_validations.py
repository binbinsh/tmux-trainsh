import io
import json
import os
import sqlite3
import subprocess
import tempfile
import urllib.error
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.models import Storage, StorageType
from trainsh.core.triggerer import Triggerer, _WaitTask
from trainsh.core.recipe_models import RecipeModel

from tests.runtime_test_utils import isolated_executor


class ProviderValidationEdgeTests(unittest.TestCase):
    def _storage(self, root: str, *, type_=StorageType.LOCAL, **config):
        merged = {"path": root}
        merged.update(config)
        return Storage(id="artifacts", name="artifacts", type=type_, config=merged)

    def test_http_validation_and_request_edges(self):
        with isolated_executor(RecipeModel(name="http-edges")) as (executor, _config_dir):
            ok, err, headers = executor._coerce_http_headers({None: "x", "A": 1})
            self.assertTrue(ok)
            self.assertEqual(headers, {"A": "1"})

            ok, err, _ = executor._coerce_http_statuses([])
            self.assertFalse(ok)
            self.assertIn("cannot be empty", err)
            ok, err, statuses = executor._coerce_http_statuses(None)
            self.assertTrue(ok)
            self.assertEqual(statuses, [200])
            ok, err, _ = executor._coerce_http_statuses("bad")
            self.assertFalse(ok)
            ok, err, _ = executor._coerce_http_statuses(["200", "bad"])
            self.assertFalse(ok)
            ok, err, _ = executor._coerce_http_statuses([True])
            self.assertFalse(ok)
            ok, err, _ = executor._coerce_http_statuses(" , ")
            self.assertFalse(ok)
            ok, err, _ = executor._coerce_http_statuses(object())
            self.assertFalse(ok)

            header = SimpleNamespace(get_content_charset=lambda: "utf-8")
            self.assertEqual(executor._decode_http_payload(b"ok", headers=header), "ok")
            self.assertEqual(executor._decode_http_payload(123), "123")
            self.assertEqual(executor._decode_http_payload(b""), "")
            bad_header = SimpleNamespace(get_content_charset=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
            self.assertEqual(executor._decode_http_payload(b"ok", headers=bad_header), "ok")

            class BadStr:
                def __str__(self):
                    raise RuntimeError("boom")

            self.assertEqual(executor._decode_http_payload(BadStr()), "")

            http_exc = urllib.error.HTTPError(
                url="https://example.test",
                code=500,
                msg="boom",
                hdrs=None,
                fp=io.BytesIO(b"failed"),
            )
            self.addCleanup(http_exc.close)
            with patch("urllib.request.urlopen", side_effect=http_exc):
                ok, status, body, error = executor._http_request_once("GET", "https://example.test", {}, None, 5)
            self.assertFalse(ok)
            self.assertEqual(status, 500)
            self.assertIn("failed", body)

            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
                ok, status, body, error = executor._http_request_once("GET", "https://example.test", {}, None, 5)
            self.assertFalse(ok)
            self.assertIsNone(status)

            with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
                ok, status, body, error = executor._http_request_once("GET", "https://example.test", {}, None, 5)
            self.assertFalse(ok)
            self.assertIn("boom", error)

            for params in ["bad", {}, {"url": "x", "timeout": "bad"}, {"url": "x", "headers": "bad"}]:
                with self.subTest(params=params):
                    ok, msg = executor._exec_provider_http_request(params)
                    self.assertFalse(ok)

            ok, msg = executor._exec_provider_http_wait("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_http_wait({})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_http_wait({"url": "x", "headers": "bad"})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_http_wait({"url": "x", "expected_status": []})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_http_wait({"url": "x", "timeout": "bad"})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_http_wait({"url": "x", "poll_interval": "bad"})
            self.assertFalse(ok)

            with patch.object(executor, "_http_request_once", return_value=(True, 200, "json-body", "")):
                ok, msg = executor._exec_provider_http_request(
                    {"url": "https://example.test", "body": {"x": 1}, "capture_var": "BODY"}
                )
            self.assertTrue(ok)
            self.assertEqual(executor.ctx.variables["BODY"], "json-body")

            executor.logger = SimpleNamespace(log_detail=MagicMock())
            with patch.object(executor, "_http_request_once", return_value=(True, 201, "bytes-body", "")):
                ok, msg = executor._exec_provider_http_request(
                    {"url": "https://example.test", "body": b"abc"}
                )
            self.assertTrue(ok)
            executor.logger.log_detail.assert_called_once()

            with patch.object(executor, "_http_request_once", return_value=(True, 200, "text-body", "")):
                ok, msg = executor._exec_provider_http_request(
                    {"url": "https://example.test", "body": "hello"}
                )
            self.assertTrue(ok)

            with patch("trainsh.core.provider_http.json.dumps", side_effect=RuntimeError("no json")), patch.object(
                executor, "_http_request_once", return_value=(False, None, "", "offline")
            ):
                ok, msg = executor._exec_provider_http_request(
                    {"url": "https://example.test", "body": {"x": 1}}
                )
            self.assertFalse(ok)
            self.assertIn("offline", msg)

            with patch.object(executor, "_http_request_once", return_value=(False, None, "", "")):
                ok, msg = executor._exec_provider_http_request(
                    {"url": "https://example.test"}
                )
            self.assertFalse(ok)
            self.assertEqual(msg, "HTTP request failed: ")

            executor.logger = SimpleNamespace(log_detail=MagicMock())
            with patch.object(
                executor,
                "_http_request_once",
                side_effect=[
                    (False, 200, "body", ""),
                    (True, 200, "body ok", ""),
                ],
            ), patch("trainsh.core.provider_http.time.sleep"):
                ok, msg = executor._exec_provider_http_wait(
                    {
                        "url": "https://example.test",
                        "expected_status": [200],
                        "expected_text": "ok",
                        "body": b"abc",
                        "poll_interval": 0,
                        "timeout": "5s",
                        "capture_var": "HTTP_WAIT",
                    }
                )
            self.assertTrue(ok)
            self.assertEqual(executor.ctx.variables["HTTP_WAIT"], "body ok")
            executor.logger.log_detail.assert_called_once()

            with patch("trainsh.core.provider_http.json.dumps", side_effect=RuntimeError("no json")), patch.object(
                executor, "_http_request_once", return_value=(False, None, "", "")
            ), patch("trainsh.core.provider_http.time.time", side_effect=[0, 10]):
                ok, msg = executor._exec_provider_http_wait(
                    {"url": "https://example.test", "body": {"x": 1}, "timeout": "5s"}
                )
            self.assertFalse(ok)
            self.assertIn("Timeout waiting for HTTP condition", msg)

            with patch.object(executor, "_http_request_once", return_value=(False, 503, "", "")), patch(
                "trainsh.core.provider_http.time.time", side_effect=[0, 10]
            ):
                ok, msg = executor._exec_provider_http_wait(
                    {"url": "https://example.test", "timeout": "5s"}
                )
            self.assertFalse(ok)
            self.assertIn("Timeout waiting for HTTP condition", msg)

    def test_data_helper_and_sqlite_validation_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            storage = self._storage(str(root), type_=StorageType.R2, bucket="bucket")
            recipe = RecipeModel(name="data-edges", storages={"artifacts": storage})
            with isolated_executor(recipe) as (executor, _config_dir):
                self.assertEqual(executor._coerce_float("1.5"), 1.5)
                self.assertEqual(executor._coerce_float("bad", default=7.0), 7.0)
                self.assertEqual(executor._coerce_int(True), 1)
                self.assertEqual(executor._coerce_int("bad", default=9), 9)
                self.assertIsNone(executor._resolve_storage(None))
                self.assertEqual(executor._storage_local_path(self._storage(str(root)), ""), str(root))
                with patch("trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"):
                    self.assertEqual(executor._storage_rclone_path(storage, "path"), "remote:bucket/path")
                smb_storage = self._storage(str(root), type_=StorageType.SMB, share="share")
                with patch("trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"):
                    self.assertEqual(executor._storage_rclone_path(smb_storage, "path"), "remote:share/path")
                gcs_storage = self._storage(str(root), type_=StorageType.GCS, bucket="bucket")
                with patch("trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"):
                    self.assertEqual(executor._storage_rclone_path(gcs_storage, "path"), "remote:bucket/path")

                with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=False):
                    ok, msg = executor._exec_storage_rclone(storage, ["ls"])
                self.assertFalse(ok)
                self.assertIn("rclone is required", msg)

                with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                    "trainsh.services.transfer_engine.build_rclone_env", return_value={}
                ), patch("subprocess.run", side_effect=FileNotFoundError()):
                    ok, msg = executor._exec_storage_rclone(storage, ["ls"])
                self.assertFalse(ok)
                self.assertIn("command not found", msg)

                with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                    "trainsh.services.transfer_engine.build_rclone_env", return_value={}
                ), patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="rclone", timeout=1)):
                    ok, msg = executor._exec_storage_rclone(storage, ["ls"], timeout=1)
                self.assertFalse(ok)
                self.assertIn("timed out", msg)

                ok, msg = executor._exec_provider_hf_download("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_hf_download({})
                self.assertFalse(ok)
                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")) as mocked_shell:
                    ok, msg = executor._exec_provider_hf_download(
                        {"repo_id": "repo/demo", "revision": "main", "local_dir": "/tmp/out", "filenames": ["a.bin", "b.bin"]}
                    )
                self.assertTrue(ok)
                self.assertIn("--filename", mocked_shell.call_args.args[0]["command"])

                ok, msg = executor._exec_provider_fetch_exchange_rates("bad")
                self.assertFalse(ok)
                with patch("trainsh.services.pricing.fetch_exchange_rates", side_effect=RuntimeError("offline")):
                    ok, msg = executor._exec_provider_fetch_exchange_rates({})
                self.assertFalse(ok)
                self.assertIn("offline", msg)

                fake_rates = SimpleNamespace(convert=lambda amount, _from, _to: amount)
                fake_settings = SimpleNamespace(display_currency="USD", exchange_rates=fake_rates)
                ok, msg = executor._exec_provider_calculate_cost("bad")
                self.assertFalse(ok)
                with patch("trainsh.services.pricing.load_pricing_settings", return_value=fake_settings):
                    ok, msg = executor._exec_provider_calculate_cost({})
                self.assertFalse(ok)
                with patch("trainsh.services.pricing.load_pricing_settings", return_value=fake_settings), patch(
                    "trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("boom")
                ):
                    ok, msg = executor._exec_provider_calculate_cost({"vast": True})
                self.assertFalse(ok)
                with patch("trainsh.services.pricing.load_pricing_settings", return_value=fake_settings), patch(
                    "trainsh.services.vast_api.get_vast_client", return_value=SimpleNamespace(list_instances=lambda: [])
                ):
                    ok, msg = executor._exec_provider_calculate_cost({"vast": True})
                self.assertFalse(ok)

                executor.recipe_path = ""
                executor.recipe.name = ""
                self.assertEqual(executor._runtime_dag_id(), "unknown_dag")

                ok, msg = executor._exec_provider_xcom_push("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_xcom_push({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_xcom_pull("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_xcom_pull({})
                self.assertFalse(ok)
                self.assertEqual(executor._coerce_float(None, default=7.5), 7.5)
                self.assertEqual(executor._storage_local_path(Storage(id="local", name="local", type=StorageType.LOCAL, config={}), ""), os.path.expanduser("."))
                with patch("trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"):
                    self.assertEqual(executor._storage_rclone_path(storage, ""), "remote:bucket")

                with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                    "trainsh.services.transfer_engine.build_rclone_env", return_value={}
                ), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
                    ok, msg = executor._exec_storage_rclone(storage, ["ls"])
                self.assertTrue(ok)
                self.assertIn("completed", msg)

                with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                    "trainsh.services.transfer_engine.build_rclone_env", return_value={}
                ), patch("subprocess.run", return_value=SimpleNamespace(returncode=2, stdout="", stderr="bad")):
                    ok, msg = executor._exec_storage_rclone(storage, ["ls"])
                self.assertFalse(ok)
                self.assertEqual(msg, "bad")

                with patch.object(executor, "_exec_provider_shell", return_value=(True, "ok")) as mocked_shell:
                    ok, msg = executor._exec_provider_hf_download(
                        {
                            "repo_id": "repo/demo",
                            "revision": "main",
                            "local_dir": "/tmp/out",
                            "token": "abc",
                            "filename": "weights.bin",
                            "host": "gpu",
                        }
                    )
                self.assertTrue(ok)
                cmd = mocked_shell.call_args.args[0]["command"]
                self.assertIn("--token", cmd)
                self.assertIn("--filename", cmd)

                with patch("trainsh.services.pricing.load_pricing_settings", return_value=fake_settings), patch(
                    "trainsh.services.pricing.calculate_host_cost",
                    return_value=SimpleNamespace(total_per_hour_usd=1.5, total_per_day_usd=36.0, total_per_month_usd=1080.0),
                ), patch("trainsh.services.pricing.format_currency", side_effect=lambda amount, currency: f"{currency}{amount:.2f}"):
                    ok, msg = executor._exec_provider_calculate_cost({"host_id": "gpu1", "currency": "USD"})
                self.assertTrue(ok)
                self.assertEqual(executor.ctx.variables["host_cost_per_hour_usd"], "1.5")

                executor.recipe_path = "/tmp/demo.py"
                self.assertEqual(executor._runtime_dag_id(), "/tmp/demo.py")
                executor.recipe_path = ""
                executor.recipe.name = "demo"
                self.assertEqual(executor._runtime_dag_id(), "demo")

                bad_db = root / "bad.db"
                bad_db.write_text("not-sqlite", encoding="utf-8")
                ok, msg = executor._exec_provider_xcom_push({"runtime_state": str(bad_db), "key": "x", "value": 1})
                self.assertTrue(ok)
                ok, msg = executor._exec_provider_xcom_pull({"runtime_state": str(bad_db), "key": "x"})
                self.assertTrue(ok)
                self.assertEqual(msg, "1")

                ok, msg = executor._exec_provider_xcom_push({"runtime_state": str(root / "ok"), "key": "k", "default": None})
                self.assertTrue(ok)

    def test_storage_shell_condition_and_triggerer_edges(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            local_storage = self._storage(str(root))
            recipe = RecipeModel(name="store-edges", storages={"artifacts": local_storage})
            with isolated_executor(recipe) as (executor, _config_dir):
                ok, msg = executor._exec_provider_storage_test("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_test({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_info("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_info({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_read_text("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_read_text({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_list("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_list({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_mkdir("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_mkdir({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_delete("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_delete({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_rename("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_rename({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_upload("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_upload({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_download("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_download({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_transfer("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_transfer({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait({"storage": "artifacts", "path": "/x", "timeout": "bad"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_count("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_count({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait_count("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait_count({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait_count({"storage": "artifacts", "path": "/x", "min_count": "bad"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_wait_count({"storage": "artifacts", "path": "/x"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_ensure_bucket("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_ensure_bucket({})
                self.assertFalse(ok)
                with patch.object(executor, "_exec_provider_storage_exists", return_value=(False, "missing")), patch(
                    "trainsh.core.provider_storage.time.time", side_effect=[0, 10]
                ), patch("trainsh.core.provider_storage.time.sleep"):
                    ok, msg = executor._exec_provider_storage_wait({"storage": "artifacts", "path": "/x", "timeout": "5s"})
                self.assertFalse(ok)
                self.assertIn("Timeout waiting storage path", msg)

                ok, msg = executor._exec_provider_shell("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_shell({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_shell({"command": "echo hi", "timeout": "bad"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_shell({"command": "echo hi", "env": "bad"})
                self.assertFalse(ok)

                ok, msg = executor._eval_condition("")
                self.assertFalse(ok)
                ok, msg = executor._eval_condition("file_contains:/tmp/x")
                self.assertFalse(ok)
                ok, msg = executor._eval_condition("storage_exists:")
                self.assertFalse(ok)
                ok, msg = executor._eval_condition("command:")
                self.assertFalse(ok)
                ok, msg = executor._eval_condition("command_output:echo")
                self.assertFalse(ok)
                ok, msg = executor._eval_condition("host_online:")
                self.assertFalse(ok)
                ok, msg = executor._eval_condition("unsupported:thing")
                self.assertFalse(ok)

                ok, msg = executor._exec_provider_wait_condition("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_wait_condition({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_wait_condition({"condition": "var:READY", "timeout": "bad"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_wait_condition({"condition": "var:READY", "poll_interval": "bad"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_branch("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_branch({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_short_circuit("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_short_circuit({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_fail("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_ssh_command("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_ssh_command({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_uv_run("bad")
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_uv_run({})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_uv_run({"command": "echo hi", "timeout": "bad"})
                self.assertFalse(ok)

                remote_storage = self._storage(str(root), type_=StorageType.R2, bucket="bucket")
                executor.recipe.storages["remote"] = remote_storage
                with patch.object(executor, "_exec_storage_rclone", return_value=(True, "ok")) as mocked_rclone:
                    ok, msg = executor._exec_provider_storage_test({"storage": "remote", "path": "/x"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_count({"storage": "remote", "path": "/x"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_info({"storage": "remote", "path": "/x"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_list({"storage": "remote", "path": "/x", "recursive": True})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_wait_count({"storage": "remote", "path": "/x", "min_count": 0, "timeout": 1})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_mkdir({"storage": "remote", "path": "/x"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_ensure_bucket({"storage": "remote"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_delete({"storage": "remote", "path": "/x", "recursive": True})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_rename({"storage": "remote", "source": "/a", "destination": "/b"})
                    self.assertTrue(ok)
                self.assertGreaterEqual(mocked_rclone.call_count, 6)

                (root / "dir").mkdir()
                ok, msg = executor._exec_provider_storage_list({"storage": "artifacts", "path": "/dir/file.txt"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_delete({"storage": "artifacts", "path": "/dir", "recursive": False})
                self.assertFalse(ok)
                self.assertIn("set recursive=True", msg)

                with patch("trainsh.core.provider_storage.os.path.exists", return_value=True), patch(
                    "trainsh.core.provider_storage.os.stat", side_effect=OSError("boom")
                ):
                    ok, msg = executor._exec_provider_storage_info({"storage": "artifacts", "path": "/"})
                self.assertFalse(ok)
                self.assertIn("boom", msg)

                target = root / "text.txt"
                target.write_text("hello", encoding="utf-8")
                ok, msg = executor._exec_provider_storage_read_text({"storage": "artifacts", "path": "/text.txt", "max_chars": 0})
                self.assertTrue(ok)
                self.assertEqual(msg, "hello")
                with patch("builtins.open", side_effect=OSError("boom")):
                    ok, msg = executor._exec_provider_storage_read_text({"storage": "artifacts", "path": "/text.txt"})
                self.assertFalse(ok)
                self.assertIn("boom", msg)

                with patch.object(executor, "_exec_storage_rclone", return_value=(False, "bad")):
                    ok, msg = executor._exec_provider_storage_read_text({"storage": "remote", "path": "/x"})
                self.assertFalse(ok)
                self.assertEqual(msg, "bad")
                with patch.object(executor, "_exec_storage_rclone", return_value=(True, "abcdef")):
                    ok, msg = executor._exec_provider_storage_read_text({"storage": "remote", "path": "/x", "max_chars": 3})
                self.assertTrue(ok)
                self.assertEqual(msg, "abc")

                with patch("os.makedirs", side_effect=OSError("boom")):
                    ok, msg = executor._exec_provider_storage_mkdir({"storage": "artifacts", "path": "/x"})
                self.assertFalse(ok)
                self.assertIn("boom", msg)
                with patch("os.rename", side_effect=OSError("boom")):
                    ok, msg = executor._exec_provider_storage_rename({"storage": "artifacts", "source": "/a", "destination": "/b"})
                self.assertFalse(ok)
                self.assertIn("boom", msg)

                source = root / "file.txt"
                source.write_text("x", encoding="utf-8")
                with patch("os.remove", side_effect=OSError("boom")):
                    ok, msg = executor._exec_provider_storage_delete({"storage": "artifacts", "path": "/file.txt"})
                self.assertFalse(ok)
                self.assertIn("boom", msg)

                with patch.object(executor.transfer_helper, "transfer", return_value=(True, "ok")) as mocked_transfer:
                    ok, msg = executor._exec_provider_transfer({"source": "a", "destination": "b", "operation": "move"})
                    self.assertTrue(ok)
                    self.assertEqual(mocked_transfer.call_args.kwargs["operation"], "sync")
                    self.assertTrue(mocked_transfer.call_args.kwargs["delete"])
                    ok, msg = executor._exec_provider_storage_upload({"storage": "remote", "source": "/tmp/in"})
                    self.assertTrue(ok)
                    ok, msg = executor._exec_provider_storage_download({"storage": "remote", "source": "/tmp/in", "destination": "/tmp/out"})
                    self.assertTrue(ok)
                ok, msg = executor._exec_provider_storage_download({"storage": "remote", "source": "", "destination": "/tmp/out"})
                self.assertFalse(ok)
                ok, msg = executor._exec_provider_storage_download({"storage": "remote", "source": "/tmp/in", "destination": ""})
                self.assertFalse(ok)

    def test_triggerer_start_submit_cancel_and_run_paths(self):
        triggerer = Triggerer(poll_interval=0.1)
        self.assertIs(triggerer.events, triggerer.events)

        fake_thread = SimpleNamespace(start=MagicMock())
        with patch("trainsh.core.triggerer.threading.Thread", return_value=fake_thread):
            triggerer.start()
            triggerer.start()
        fake_thread.start.assert_called_once()

        fake_join_thread = SimpleNamespace(join=MagicMock())
        triggerer._thread = fake_join_thread
        triggerer.stop()
        fake_join_thread.join.assert_called_once()

        task_id = triggerer.submit(step_id="s1", check_fn=lambda: (True, "ok"), timeout=2, poll_interval=0)
        self.assertIn(task_id, triggerer._tasks)
        self.assertIsNotNone(triggerer._tasks[task_id].deadline)
        self.assertGreaterEqual(triggerer._tasks[task_id].poll_interval, 1.0)
        triggerer.cancel(task_id)
        self.assertNotIn(task_id, triggerer._tasks)

        class FakeStop:
            def __init__(self):
                self.called = False

            def is_set(self):
                return False

            def wait(self, delay):
                self.called = True
                return True

        triggerer = Triggerer()
        triggerer._stop = FakeStop()
        triggerer._tasks = {
            "ok": _WaitTask("ok", "step-ok", lambda: (True, "done"), None, 1.0, created_at=0.0, next_check_at=0.0),
            "timeout": _WaitTask("timeout", "step-time", lambda: (False, "later"), 0.0, 1.0, created_at=0.0, next_check_at=0.0),
            "err": _WaitTask("err", "step-err", lambda: (_ for _ in ()).throw(RuntimeError("boom")), 0.0, 1.0, created_at=0.0, next_check_at=0.0),
        }
        with patch("trainsh.core.triggerer.time.time", return_value=1.0):
            triggerer._run()

        events = [triggerer.events.get_nowait() for _ in range(3)]
        self.assertEqual([(e.step_id, e.status) for e in events], [("step-ok", "success"), ("step-time", "timeout"), ("step-err", "timeout")])

    def test_shell_ops_more_edges(self):
        with isolated_executor(RecipeModel(name="shell-more")) as (executor, _config_dir):
            executor.logger = SimpleNamespace(log_ssh=lambda *a, **k: None)

            with patch("trainsh.core.provider_shell.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
                ok, msg = executor._exec_provider_shell({"command": "echo hi", "capture_var": "OUT"})
            self.assertTrue(ok)
            self.assertIn("completed", msg)
            self.assertEqual(executor.ctx.variables["OUT"], "")

            with patch.object(executor, "_provider_host", return_value="gpu"), patch(
                "trainsh.core.provider_shell.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok", stderr="")
            ) as mocked_run:
                ok, msg = executor._exec_provider_shell({"command": "echo hi", "host": "gpu", "cwd": "/tmp"})
            self.assertTrue(ok)
            self.assertEqual(mocked_run.call_args.args[0][0], "ssh")

            with patch("trainsh.core.provider_shell.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
                ok, msg = executor._exec_provider_shell({"command": "echo hi", "timeout": 1})
            self.assertFalse(ok)
            self.assertIn("timed out", msg)

            with patch("trainsh.core.provider_shell.subprocess.run", side_effect=RuntimeError("boom")):
                ok, msg = executor._exec_provider_shell({"command": "echo hi"})
            self.assertFalse(ok)
            self.assertIn("boom", msg)

            with patch.dict(os.environ, {"FLAG": "1"}, clear=False):
                self.assertEqual(executor._eval_condition("env:FLAG==1"), (True, "FLAG == 1"))
                self.assertEqual(executor._eval_condition("env:FLAG"), (True, "env:FLAG is set"))

            with tempfile.TemporaryDirectory() as tmpdir:
                target = Path(tmpdir) / "data.txt"
                target.write_text("hello world", encoding="utf-8")
                ok, msg = executor._eval_condition(f"file_exists:{target}")
                self.assertTrue(ok)
                ok, msg = executor._eval_condition(f"file_contains:{target}:world")
                self.assertTrue(ok)
                ok, msg = executor._eval_condition(f"file_contains:{target}:missing")
                self.assertFalse(ok)

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "exists")):
                ok, msg = executor._eval_condition("file_exists:/tmp/demo", host="gpu")
            self.assertTrue(ok)

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "found")):
                ok, msg = executor._eval_condition("file_contains:/tmp/demo:ok", host="gpu")
            self.assertTrue(ok)

            with patch.object(executor, "_exec_provider_storage_exists", return_value=(True, "ok")):
                ok, msg = executor._eval_condition("storage_exists:@artifacts:/tmp/out")
            self.assertTrue(ok)

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "done")):
                self.assertTrue(executor._eval_condition("command:echo hi")[0])
                self.assertTrue(executor._eval_condition("command_output:echo hi:done")[0])

            with patch.object(executor, "_verify_ssh_connection", return_value=True):
                self.assertTrue(executor._eval_condition("host_online:gpu")[0])

            ok, msg = executor._exec_provider_git_clone({})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_git_clone("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_git_clone({"repo_url": "https://github.com/example/repo.git", "auth": "mystery"})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_git_pull("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_host_test("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_assert("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_assert({})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_get_value("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_get_value({})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_set_env("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_wait_for_file("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_wait_for_file({})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_wait_for_port("bad")
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_wait_for_port({})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_wait_for_port({"port": "bad"})
            self.assertFalse(ok)
            ok, msg = executor._exec_provider_wait_for_port({"port": 0})
            self.assertFalse(ok)

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "exists")):
                ok, msg = executor._exec_provider_wait_for_file({"path": "/tmp/x", "host": "gpu", "timeout": 1, "poll_interval": 1})
            self.assertTrue(ok)

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "open")):
                ok, msg = executor._exec_provider_wait_for_port({"port": 8080, "host": "gpu", "timeout": 1, "poll_interval": 1})
            self.assertTrue(ok)

            with patch.object(executor, "_exec_provider_shell", return_value=(True, "open")) as mocked_shell:
                ok, msg = executor._exec_provider_wait_for_port(
                    {"port": 8080, "host": "gpu", "host_name": "127.0.0.1", "timeout": 1, "poll_interval": 1}
                )
            self.assertTrue(ok)
            self.assertIn("127.0.0.1", mocked_shell.call_args.args[0]["command"])


if __name__ == "__main__":
    unittest.main()
