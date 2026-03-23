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
from trainsh.core.secrets import SecretsManager
from trainsh.services.hf_storage import build_hf_env, resolve_hf_bucket_uri


_FAKE_HF_SCRIPT = """#!/usr/bin/env python3
import json
import os
import sys

log_path = os.environ.get("FAKE_HF_LOG", "")
if log_path:
    payload = {
        "argv": sys.argv[1:],
        "env": {key: value for key, value in os.environ.items() if key == "HF_TOKEN"},
    }
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\\n")

args = sys.argv[1:]
command = args[0] if args else ""
subcommand = args[1] if len(args) > 1 else ""

if command == "version":
    print("hf 1.7.1")
elif command == "buckets" and subcommand == "info":
    print('{"id":"team/checkpoints","private":false}')
elif command == "buckets" and subcommand == "list":
    print("config.json")
elif command == "buckets" and subcommand == "sync":
    print("sync ok")
elif command == "buckets" and subcommand == "cp":
    print("cp ok")
elif command == "buckets" and subcommand == "create":
    print("bucket created")
elif command == "buckets" and subcommand == "rm":
    print("rm ok")
else:
    print(f"unsupported fake hf command: {' '.join(args)}", file=sys.stderr)
    sys.exit(2)
"""


class HFStorageFlowTests(unittest.TestCase):
    def _build_manager(self, values: dict[str, str]) -> SecretsManager:
        manager = SecretsManager()
        backend = MagicMock()
        backend.get.side_effect = lambda key: values.get(str(key))
        manager._backend = backend
        manager._backend_loaded = True
        return manager

    @contextmanager
    def _fake_hf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir(parents=True, exist_ok=True)
            script = bin_dir / "hf"
            script.write_text(_FAKE_HF_SCRIPT, encoding="utf-8")
            script.chmod(0o755)
            log_path = root / "hf-log.jsonl"

            env = {
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "FAKE_HF_LOG": str(log_path),
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

    def test_build_hf_env_prefers_scoped_secret(self):
        storage = Storage(name="archive", type=StorageType.HF, config={"bucket": "team/checkpoints"})
        manager = self._build_manager({"ARCHIVE_HF_TOKEN": "scoped-token", "HF_TOKEN": "global-token"})

        with patch("trainsh.services.hf_storage.get_secrets_manager", return_value=manager):
            env = build_hf_env(storage)

        self.assertEqual(env, {"HF_TOKEN": "scoped-token"})

    def test_storage_test_command_uses_hf_bucket_info(self):
        storage = Storage(
            id="artifacts",
            name="artifacts",
            type=StorageType.HF,
            config={"bucket": "team/checkpoints"},
        )
        manager = self._build_manager({"ARTIFACTS_HF_TOKEN": "hf-secret"})

        with self._fake_hf() as log_path, patch(
            "trainsh.commands.storage.load_storages",
            return_value={"artifacts": storage},
        ), patch(
            "trainsh.services.hf_storage.get_secrets_manager",
            return_value=manager,
        ), redirect_stdout(io.StringIO()) as stdout:
            storage_cmd.cmd_test(["artifacts"])
            calls = self._read_calls(log_path)

        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(calls[0]["argv"], ["version"])
        self.assertEqual(calls[-1]["argv"], ["buckets", "info", "team/checkpoints"])
        self.assertEqual(calls[-1]["env"]["HF_TOKEN"], "hf-secret")
        self.assertIn("Connection successful!", stdout.getvalue())

    def test_transfer_command_inline_hf_upload_uses_hf_cli_and_bucket_uri(self):
        manager = self._build_manager({"HF_TOKEN": "global-hf-token"})

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "payload"
            source.mkdir()
            (source / "config.json").write_text("{}", encoding="utf-8")

            with self._fake_hf() as log_path, patch(
                "trainsh.commands.storage.load_storages",
                return_value={},
            ), patch(
                "trainsh.services.hf_storage.get_secrets_manager",
                return_value=manager,
            ), redirect_stdout(io.StringIO()) as stdout:
                transfer_main([str(source), "hf:team/checkpoints:/nightly", "--dry-run"])
                calls = self._read_calls(log_path)

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["argv"], ["version"])
        self.assertEqual(
            calls[-1]["argv"],
            [
                "buckets",
                "sync",
                str(source),
                resolve_hf_bucket_uri(Storage(name="hf_team_checkpoints", type=StorageType.HF, config={"bucket": "team/checkpoints"}), "team/checkpoints/nightly"),
                "--quiet",
                "--dry-run",
            ],
        )
        self.assertEqual(calls[-1]["env"]["HF_TOKEN"], "global-hf-token")
        self.assertIn("Transfer complete: Transfer complete", stdout.getvalue())

