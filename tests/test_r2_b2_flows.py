import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from trainsh.commands import storage as storage_cmd
from trainsh.commands.transfer import main as transfer_main
from trainsh.core.models import Storage, StorageType
from trainsh.core.recipe_models import RecipeModel
from trainsh.core.secrets import SecretsManager
from trainsh.core.storage_specs import build_storage_from_spec
from trainsh.services.transfer_engine import get_rclone_remote_name

from tests.runtime_test_utils import isolated_executor


_FAKE_RCLONE_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys

log_path = os.environ.get("FAKE_RCLONE_LOG", "")
if log_path:
    payload = {
        "argv": sys.argv[1:],
        "env": {
            key: value
            for key, value in os.environ.items()
            if key.startswith("RCLONE_CONFIG_")
        },
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\\n")

command = sys.argv[1] if len(sys.argv) > 1 else ""

if command == "version":
    print("rclone v1.67.0")
elif command in {"copy", "sync", "move"}:
    print("Transferred: 1.5 MiB / 1.5 MiB, 100%, 10 MiB/s, ETA 0s")
elif command == "lsd":
    print("          -1 2026-03-11 00:00:00        -1 checkpoints")
elif command == "ls":
    print("        123 object.txt")
elif command == "lsf":
    print("checkpoints/")
    print("object.txt")
elif command == "lsjson":
    print('[{"Path":"object.txt","Size":123,"IsDir":false}]')
elif command == "cat":
    print("hello from remote object")
elif command in {"mkdir", "delete", "purge", "moveto"}:
    print(f"{command} ok")
else:
    print(f"unsupported fake rclone command: {command}", file=sys.stderr)
    sys.exit(2)
"""


class R2B2FlowTests(unittest.TestCase):
    def _build_manager(self, values: dict[str, str]) -> SecretsManager:
        manager = SecretsManager()
        backend = MagicMock()
        backend.get.side_effect = lambda key: values.get(str(key))
        manager._backend = backend
        manager._backend_loaded = True
        return manager

    @contextmanager
    def _fake_rclone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            script = bin_dir / "rclone"
            script.write_text(_FAKE_RCLONE_SCRIPT, encoding="utf-8")
            script.chmod(0o755)
            log_path = root / "rclone-log.jsonl"

            env = {
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "FAKE_RCLONE_LOG": str(log_path),
            }
            with patch.dict(os.environ, env, clear=False):
                yield log_path

    def _read_calls(self, log_path: Path) -> list[dict]:
        if not log_path.exists():
            return []
        return [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_storage_test_command_uses_r2_bundle_and_bucket_root(self):
        storage = Storage(
            id="artifacts",
            name="artifacts",
            type=StorageType.R2,
            config={"bucket": "logs"},
        )
        manager = self._build_manager(
            {
                "ARTIFACTS_R2_CREDENTIALS": json.dumps(
                    {
                        "account_id": "r2-account",
                        "access_key_id": "r2-ak",
                        "secret_access_key": "r2-sk",
                    }
                )
            }
        )

        with self._fake_rclone() as log_path, patch(
            "trainsh.commands.storage.load_storages",
            return_value={"artifacts": storage},
        ), patch(
            "trainsh.services.transfer_engine.get_secrets_manager",
            return_value=manager,
        ), redirect_stdout(io.StringIO()) as stdout:
            storage_cmd.cmd_test(["artifacts"])
            calls = self._read_calls(log_path)

        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0]["argv"], ["version"])
        self.assertEqual(calls[-1]["argv"], ["lsd", "artifacts:logs"])
        env = calls[-1]["env"]
        self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_TYPE"], "s3")
        self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_PROVIDER"], "Cloudflare")
        self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_ACCESS_KEY_ID"], "r2-ak")
        self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_SECRET_ACCESS_KEY"], "r2-sk")
        self.assertEqual(
            env["RCLONE_CONFIG_ARTIFACTS_ENDPOINT"],
            "https://r2-account.r2.cloudflarestorage.com",
        )
        self.assertIn("Connection successful!", stdout.getvalue())

    def test_transfer_command_inline_r2_upload_uses_global_bundle_and_safe_remote(self):
        manager = self._build_manager(
            {
                "R2_CREDENTIALS": json.dumps(
                    {
                        "account_id": "global-account",
                        "access_key_id": "global-ak",
                        "secret_access_key": "global-sk",
                    }
                )
            }
        )
        inline_storage = build_storage_from_spec("r2:logs-bucket")
        self.assertIsNotNone(inline_storage)
        expected_remote = get_rclone_remote_name(inline_storage)

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "weights.bin"
            source.write_text("payload", encoding="utf-8")

            with self._fake_rclone() as log_path, patch(
                "trainsh.commands.storage.load_storages",
                return_value={},
            ), patch(
                "trainsh.services.transfer_engine.get_secrets_manager",
                return_value=manager,
            ), redirect_stdout(io.StringIO()) as stdout:
                transfer_main([str(source), "r2:logs-bucket:/checkpoints", "--dry-run"])
                calls = self._read_calls(log_path)

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["argv"],
            [
                "copy",
                "--progress",
                "--dry-run",
                str(source),
                f"{expected_remote}:logs-bucket/checkpoints",
            ],
        )
        env = calls[0]["env"]
        remote_env = expected_remote.upper()
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_TYPE"], "s3")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_ACCESS_KEY_ID"], "global-ak")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_SECRET_ACCESS_KEY"], "global-sk")
        self.assertEqual(
            env[f"RCLONE_CONFIG_{remote_env}_ENDPOINT"],
            "https://global-account.r2.cloudflarestorage.com",
        )
        output = stdout.getvalue()
        self.assertIn("Transfer complete: Transfer complete", output)
        self.assertIn("Transferred: 1,572,864 bytes", output)

    def test_transfer_command_named_b2_download_uses_storage_specific_bundle(self):
        storage = Storage(
            id="backups",
            name="backup archive",
            type=StorageType.B2,
            config={"bucket": "model-cache"},
        )
        manager = self._build_manager(
            {
                "BACKUP_ARCHIVE_B2_CREDENTIALS": json.dumps(
                    {
                        "application_key_id": "b2-key-id",
                        "application_key": "b2-app-key",
                    }
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "downloaded"

            with self._fake_rclone() as log_path, patch(
                "trainsh.commands.storage.load_storages",
                return_value={"backups": storage},
            ), patch(
                "trainsh.services.transfer_engine.get_secrets_manager",
                return_value=manager,
            ), redirect_stdout(io.StringIO()):
                transfer_main(["storage:backups:/models", str(destination)])
                calls = self._read_calls(log_path)

        self.assertEqual(len(calls), 1)
        remote_name = get_rclone_remote_name(storage)
        self.assertEqual(
            calls[0]["argv"],
            [
                "copy",
                "--progress",
                f"{remote_name}:model-cache/models",
                str(destination),
            ],
        )
        env = calls[0]["env"]
        remote_env = remote_name.upper()
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_TYPE"], "b2")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_ACCOUNT"], "b2-key-id")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_KEY"], "b2-app-key")

    def test_runtime_r2_storage_provider_covers_access_usage_and_transfer_flows(self):
        storage = Storage(
            id="artifacts",
            name="artifacts archive",
            type=StorageType.R2,
            config={"bucket": "logs"},
        )
        recipe = RecipeModel(name="r2-runtime", storages={"artifacts": storage})
        manager = self._build_manager(
            {
                "ARTIFACTS_ARCHIVE_R2_CREDENTIALS": json.dumps(
                    {
                        "account_id": "runtime-account",
                        "access_key_id": "runtime-ak",
                        "secret_access_key": "runtime-sk",
                    }
                )
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            local_source = Path(tmpdir) / "artifact.txt"
            local_source.write_text("runtime payload", encoding="utf-8")
            local_download = Path(tmpdir) / "downloaded.txt"

            with self._fake_rclone() as log_path, patch(
                "trainsh.services.transfer_engine.get_secrets_manager",
                return_value=manager,
            ):
                with isolated_executor(recipe) as (executor, _config_dir):
                    ok, message = executor._exec_provider_storage_upload(
                        {
                            "storage": "artifacts",
                            "source": str(local_source),
                            "destination": "/exports",
                        }
                    )
                    self.assertTrue(ok, message)

                    ok, message = executor._exec_provider_storage_download(
                        {
                            "storage": "artifacts",
                            "source": "/exports",
                            "destination": str(local_download),
                        }
                    )
                    self.assertTrue(ok, message)

                    ok, message = executor._exec_provider_storage_test(
                        {"storage": "artifacts", "path": "/exports"}
                    )
                    self.assertTrue(ok, message)

                    ok, listed = executor._exec_provider_storage_list(
                        {"storage": "artifacts", "path": "/exports", "recursive": True}
                    )
                    self.assertTrue(ok, listed)
                    self.assertIn("object.txt", listed)

                    ok, info = executor._exec_provider_storage_info(
                        {"storage": "artifacts", "path": "/exports/object.txt"}
                    )
                    self.assertTrue(ok, info)
                    self.assertEqual(json.loads(info)[0]["Path"], "object.txt")

                    ok, content = executor._exec_provider_storage_read_text(
                        {"storage": "artifacts", "path": "/exports/object.txt", "max_chars": 5}
                    )
                    self.assertTrue(ok, content)
                    self.assertEqual(content, "hello")

                    ok, message = executor._exec_provider_storage_mkdir(
                        {"storage": "artifacts", "path": "/tmpdir"}
                    )
                    self.assertTrue(ok, message)

                    ok, message = executor._exec_provider_storage_rename(
                        {
                            "storage": "artifacts",
                            "source": "/exports/object.txt",
                            "destination": "/exports/object-renamed.txt",
                        }
                    )
                    self.assertTrue(ok, message)

                    ok, message = executor._exec_provider_storage_wait(
                        {"storage": "artifacts", "path": "/exports/object-renamed.txt", "timeout": 1}
                    )
                    self.assertTrue(ok, message)

                    ok, message = executor._exec_provider_storage_delete(
                        {"storage": "artifacts", "path": "/tmpdir", "recursive": True}
                    )
                    self.assertTrue(ok, message)
                calls = self._read_calls(log_path)

        commands = [call["argv"][0] for call in calls if call.get("argv")]
        self.assertGreaterEqual(commands.count("version"), 6)
        self.assertIn("copy", commands)
        self.assertIn("ls", commands)
        self.assertIn("lsf", commands)
        self.assertIn("lsjson", commands)
        self.assertIn("cat", commands)
        self.assertIn("mkdir", commands)
        self.assertIn("moveto", commands)
        self.assertIn("purge", commands)

        remote_name = get_rclone_remote_name(storage)
        upload_call = next(
            call
            for call in calls
            if call["argv"][:3] == ["copy", "--progress", str(local_source)]
        )
        download_call = next(
            call
            for call in calls
            if call["argv"][:2] == ["copy", "--progress"] and call["argv"][-1] == str(local_download)
        )
        remote_path = f"{remote_name}:logs/exports"
        self.assertEqual(upload_call["argv"][-1], remote_path)
        self.assertEqual(download_call["argv"][2], remote_path)

        env = upload_call["env"]
        remote_env = remote_name.upper()
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_TYPE"], "s3")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_ACCESS_KEY_ID"], "runtime-ak")
        self.assertEqual(env[f"RCLONE_CONFIG_{remote_env}_SECRET_ACCESS_KEY"], "runtime-sk")
        self.assertEqual(
            env[f"RCLONE_CONFIG_{remote_env}_ENDPOINT"],
            "https://runtime-account.r2.cloudflarestorage.com",
        )


if __name__ == "__main__":
    unittest.main()
