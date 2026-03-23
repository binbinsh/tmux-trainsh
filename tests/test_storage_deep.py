import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from trainsh.commands import storage
from trainsh.core.models import Storage, StorageType


@contextmanager
def patched_storage_store():
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        config_dir = Path(tmpdir) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        stack.enter_context(patch("trainsh.constants.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.constants.STORAGES_FILE", config_dir / "storages.yaml"))
        yield config_dir


def capture(fn, *args, **kwargs):
    out = StringIO()
    code = None
    with redirect_stdout(out):
        try:
            fn(*args, **kwargs)
        except SystemExit as exc:
            code = exc.code
    return out.getvalue(), code


class StorageDeepTests(unittest.TestCase):
    def test_cmd_add_all_storage_types_and_defaults(self):
        with patched_storage_store():
            cases = [
                ("localbox", ["localbox", "1", "/tmp/local", "y"], StorageType.LOCAL, {"path": "/tmp/local"}),
                ("sshbox", ["sshbox", "2", "root@example", "/srv/data", "1", "~/.ssh/id_ed25519", "n"], StorageType.SSH, {"host": "root@example", "path": "/srv/data", "key_path": "~/.ssh/id_ed25519"}),
                ("drivebox", ["drivebox", "3", "gdrive-remote", "n"], StorageType.GOOGLE_DRIVE, {"remote_name": "gdrive-remote"}),
                ("r2box", ["r2box", "4", "acct123", "bucket-a", "n", "n"], StorageType.R2, {"account_id": "acct123", "bucket": "bucket-a", "endpoint": "https://acct123.r2.cloudflarestorage.com"}),
                ("b2box", ["b2box", "5", "bucket-b", "n", "n"], StorageType.B2, {"bucket": "bucket-b"}),
                ("s3box", ["s3box", "6", "bucket-c", "us-west-2", "https://s3.example.com", "n", "n"], StorageType.S3, {"bucket": "bucket-c", "region": "us-west-2", "endpoint": "https://s3.example.com"}),
                ("gcsbox", ["gcsbox", "7", "bucket-d", "", "n", "n"], StorageType.GCS, {"bucket": "bucket-d"}),
                ("smbbox", ["smbbox", "8", "server", "share", "alice", "n", "n"], StorageType.SMB, {"server": "server", "share": "share", "username": "alice"}),
                ("hfbox", ["hfbox", "9", "team/checkpoints", "n", "n"], StorageType.HF, {"bucket": "team/checkpoints"}),
            ]
            for name, inputs, expected_type, expected_config in cases:
                with patch("trainsh.commands.storage.prompt_input", side_effect=inputs):
                    out, code = capture(storage.cmd_add, [])
                self.assertIsNone(code)
                self.assertIn(f"Added storage: {name}", out)
                created = storage.load_storages()[name]
                self.assertEqual(created.type, expected_type)
                for key, value in expected_config.items():
                    self.assertEqual(created.config[key], value)

            storages = storage.load_storages()
            self.assertTrue(storages["localbox"].is_default)
            self.assertFalse(storages["sshbox"].is_default)

    def test_cmd_add_cancellation_and_unknown_choice_defaults_local(self):
        with patched_storage_store():
            with patch("trainsh.commands.storage.prompt_input", side_effect=[None]):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Add new storage backend", out)

            with patch("trainsh.commands.storage.prompt_input", side_effect=[""]):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Cancelled - name is required.", out)

            with patch("trainsh.commands.storage.prompt_input", side_effect=["demo", None]):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)

            with patch("trainsh.commands.storage.prompt_input", side_effect=["fallback", "99", "/tmp/fallback", "n"]):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            created = storage.load_storages()["fallback"]
            self.assertEqual(created.type, StorageType.LOCAL)

            cancel_cases = [
                ["ssh-cancel", "2", None],
                ["ssh-cancel2", "2", "host", None],
                ["ssh-cancel3", "2", "host", "/srv", None],
                ["ssh-cancel4", "2", "host", "/srv", "1", None],
                ["drive-cancel", "3", None],
                ["r2-cancel", "4", None],
                ["r2-cancel2", "4", "acct", None],
                ["r2-cancel3", "4", "acct", "bucket", None],
                ["b2-cancel", "5", None],
                ["b2-cancel2", "5", "bucket", None],
                ["s3-cancel", "6", None],
                ["s3-cancel2", "6", "bucket", None],
                ["s3-cancel3", "6", "bucket", "us-east-1", None],
                ["s3-cancel4", "6", "bucket", "us-east-1", "", None],
                ["gcs-cancel", "7", None],
                ["gcs-cancel2", "7", "bucket", None],
                ["smb-cancel", "8", None],
                ["smb-cancel2", "8", "server", None],
                ["smb-cancel3", "8", "server", "share", None],
                ["smb-cancel4", "8", "server", "share", "user", None],
                ["hf-cancel", "9", None],
                ["hf-cancel2", "9", "team/checkpoints", None],
                ["local-cancel", "1", "/tmp/local", None],
            ]
            for inputs in cancel_cases:
                with self.subTest(inputs=inputs):
                    with patch("trainsh.commands.storage.prompt_input", side_effect=inputs):
                        out, code = capture(storage.cmd_add, [])
                    self.assertIsNone(code)

    def test_cmd_add_can_store_cloud_and_file_credentials_in_secrets(self):
        with patched_storage_store():
            secrets = SimpleNamespace(set_bundle=unittest.mock.MagicMock(), set=unittest.mock.MagicMock())

            with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets), patch(
                "trainsh.commands.storage.prompt_input",
                side_effect=["r2secret", "4", "acct123", "bucket-a", "y", "n"],
            ), patch("trainsh.commands.storage.getpass.getpass", side_effect=["AKIA", "SECRET"]):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Stored R2 credentials in train secrets.", out)
            secrets.set_bundle.assert_called_once()

            secrets = SimpleNamespace(set_bundle=unittest.mock.MagicMock(), set=unittest.mock.MagicMock())
            with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets), patch(
                "trainsh.commands.storage.prompt_input",
                side_effect=["s3secret", "6", "bucket-c", "us-west-2", "", "y", "n"],
            ), patch("trainsh.commands.storage.getpass.getpass", side_effect=["AKIA2", "SECRET2"]):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            created = storage.load_storages()["s3secret"]
            self.assertNotIn("access_key_secret", created.config)
            self.assertNotIn("secret_key_secret", created.config)
            self.assertEqual(secrets.set.call_count, 2)

            with patch("trainsh.commands.storage._store_secret_file") as store_file, patch(
                "trainsh.commands.storage.prompt_input",
                side_effect=["gcssecret", "7", "bucket-d", "project-1", "y", "/tmp/gcs.json", "n"],
            ):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Stored GCS service account JSON in train secrets.", out)
            store_file.assert_called_once_with("GCSSECRET_SERVICE_ACCOUNT_JSON", "/tmp/gcs.json")

            secrets = SimpleNamespace(set_bundle=unittest.mock.MagicMock(), set=unittest.mock.MagicMock())
            with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets), patch(
                "trainsh.commands.storage.prompt_input",
                side_effect=["hfsecret", "9", "team/checkpoints", "y", "n"],
            ), patch("trainsh.commands.storage.getpass.getpass", return_value="hf-token"):
                out, code = capture(storage.cmd_add, [])
            self.assertIsNone(code)
            self.assertIn("Stored HF token in train secrets.", out)
            secrets.set.assert_called_with("HFSECRET_HF_TOKEN", "hf-token")

    def test_show_remove_test_and_main_paths(self):
        with patched_storage_store():
            local = Storage(name="localbox", type=StorageType.LOCAL, config={"path": "/tmp"}, is_default=True)
            sshbox = Storage(name="sshbox", type=StorageType.SSH, config={"host": "root@example"})
            cloud = Storage(name="cloud", type=StorageType.R2, config={"bucket": "bucket"})
            storage.save_storages({"localbox": local, "sshbox": sshbox, "cloud": cloud})

            out, code = capture(storage.cmd_show, [])
            self.assertEqual(code, 1)
            self.assertIn("Usage: train storage show <name>", out)
            out, code = capture(storage.cmd_show, ["missing"])
            self.assertEqual(code, 1)
            self.assertIn("Storage not found: missing", out)
            out, code = capture(storage.cmd_show, ["localbox"])
            self.assertIsNone(code)
            self.assertIn("Default: Yes", out)

            storage.save_storages(
                {
                    "localbox": local,
                    "sshbox": sshbox,
                    "cloud": cloud,
                    "s3box": Storage(
                        name="s3box",
                        type=StorageType.S3,
                        config={"bucket": "bucket", "access_key_secret": "S3BOX_ACCESS_KEY_ID"},
                    ),
                }
            )
            secrets = SimpleNamespace(
                exists=lambda key: key in {"S3BOX_ACCESS_KEY_ID"},
            )
            with patch("trainsh.core.secrets.get_secrets_manager", return_value=secrets):
                out, code = capture(storage.cmd_show, ["s3box"])
            self.assertIsNone(code)
            self.assertIn("Managed secrets:", out)
            self.assertIn("S3 access key", out)
            self.assertNotIn("access_key_secret", out)

            out, code = capture(storage.cmd_rm, [])
            self.assertEqual(code, 1)
            out, code = capture(storage.cmd_rm, ["missing"])
            self.assertEqual(code, 1)
            with patch("trainsh.commands.storage.prompt_input", return_value="n"):
                out, code = capture(storage.cmd_rm, ["localbox"])
            self.assertIsNone(code)
            self.assertIn("Cancelled.", out)
            with patch("trainsh.commands.storage.prompt_input", return_value="y"):
                out, code = capture(storage.cmd_rm, ["localbox"])
            self.assertIsNone(code)
            self.assertIn("Storage removed: localbox", out)

            out, code = capture(storage.cmd_test, [])
            self.assertEqual(code, 1)
            out, code = capture(storage.cmd_test, ["missing"])
            self.assertEqual(code, 1)

            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                "trainsh.services.transfer_engine.build_rclone_env", return_value={"A": "1"}
            ), patch(
                "trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"
            ), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="dir1\ndir2\n", stderr="")):
                out, code = capture(storage.cmd_test, ["cloud"])
            self.assertIsNone(code)
            self.assertIn("Connection successful!", out)
            self.assertIn("...", out)

            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                "trainsh.services.transfer_engine.build_rclone_env", return_value={}
            ), patch(
                "trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"
            ), patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom")):
                out, code = capture(storage.cmd_test, ["cloud"])
            self.assertEqual(code, 1)
            self.assertIn("Connection failed: boom", out)

            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=SimpleNamespace(run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="ok\n", stderr=""))):
                out, code = capture(storage.cmd_test, ["sshbox"])
            self.assertIsNone(code)
            self.assertIn("Connection successful!", out)

            storage.save_storages({"sshbad": Storage(name="sshbad", type=StorageType.SSH, config={})})
            out, code = capture(storage.cmd_test, ["sshbad"])
            self.assertEqual(code, 1)
            self.assertIn("No host configured for SSH storage.", out)

            storage.save_storages({"sshbad": Storage(name="sshbad", type=StorageType.SSH, config={"host": "root@example"})})
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=SimpleNamespace(run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="denied"))):
                out, code = capture(storage.cmd_test, ["sshbad"])
            self.assertEqual(code, 1)
            self.assertIn("Connection failed: denied", out)

            storage.save_storages({"localbad": Storage(name="localbad", type=StorageType.LOCAL, config={"path": "/missing"})})
            out, code = capture(storage.cmd_test, ["localbad"])
            self.assertEqual(code, 1)
            self.assertIn("Path not found: /missing", out)

            storage.save_storages({"other": Storage(name="other", type=StorageType.GOOGLE_DRIVE, config={})})
            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=False):
                out, code = capture(storage.cmd_test, ["other"])
            self.assertEqual(code, 1)
            self.assertIn("rclone is required", out)

            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                "trainsh.services.transfer_engine.build_rclone_env", return_value={}
            ), patch(
                "trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"
            ), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
                out, code = capture(storage.main, ["check", "other"])
            self.assertIsNone(code)

            out, code = capture(storage.main, ["--help"])
            self.assertEqual(code, 1)
            self.assertIn("Use `train help` or `train --help`.", out)
            out, code = capture(storage.main, ["unknown"])
            self.assertEqual(code, 1)
            self.assertIn("Unknown subcommand", out)


if __name__ == "__main__":
    unittest.main()
