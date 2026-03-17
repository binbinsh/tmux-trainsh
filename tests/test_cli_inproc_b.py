import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.commands import colab, host, storage, transfer, vast
from trainsh.core.models import AuthMethod, Host, HostType, Storage, StorageType


@contextmanager
def patched_config_files():
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        config_dir = Path(tmpdir) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        stack.enter_context(patch("trainsh.constants.CONFIG_DIR", config_dir))
        stack.enter_context(patch("trainsh.constants.HOSTS_FILE", config_dir / "hosts.yaml"))
        stack.enter_context(patch("trainsh.constants.STORAGES_FILE", config_dir / "storages.yaml"))
        stack.enter_context(patch("trainsh.services.vast_api.get_vast_client", side_effect=RuntimeError("disabled in tests")))
        stack.enter_context(patch.object(colab, "CONFIG_DIR", config_dir))
        stack.enter_context(patch.object(colab, "COLAB_FILE", config_dir / "colab.yaml"))
        yield config_dir


def capture_output(func, *args, **kwargs):
    stream = StringIO()
    with redirect_stdout(stream):
        func(*args, **kwargs)
    return stream.getvalue()


class HostCommandTests(unittest.TestCase):
    def _ssh_host(self, name="gpu-box"):
        return Host(
            name=name,
            type=HostType.SSH,
            hostname="gpu.example.com",
            port=2222,
            username="root",
            auth_method=AuthMethod.KEY,
            ssh_key_path="~/.ssh/id_rsa",
            jump_host="bastion",
            env_vars={
                "tunnel_type": "cloudflared",
                "cloudflared_hostname": "ssh.example.com",
                "cloudflared_bin": "/usr/local/bin/cloudflared",
                "proxy_command": "proxy-cmd",
                "connection_candidates": [
                    {"type": "ssh", "hostname": "gpu-alt", "port": 2200},
                    {"type": "cloudflared", "hostname": "cf.example.com"},
                ],
            },
        )

    def _colab_host(self, name="colab-box"):
        return Host(
            name=name,
            type=HostType.COLAB,
            hostname="colab.example.com",
            port=22,
            username="root",
            env_vars={"tunnel_type": "cloudflared", "cloudflared_hostname": "cf.colab"},
        )

    def test_host_load_save_list_show_remove_and_main(self):
        with patched_config_files():
            hosts = {
                "gpu-box": self._ssh_host(),
                "colab-box": self._colab_host(),
            }
            host.save_hosts(hosts)
            loaded = host.load_hosts()
            self.assertEqual(set(loaded), {"gpu-box", "colab-box"})

            text = capture_output(host.cmd_list, [])
            self.assertIn("Configured hosts:", text)
            self.assertIn("gpu-box", text)
            self.assertIn("Colab/cloudflared", text)

            text = capture_output(host.cmd_show, ["gpu-box"])
            self.assertIn("Host: gpu-box", text)
            self.assertIn("Connection candidates:", text)
            self.assertIn("Cloudflared Hostname: ssh.example.com", text)

            with self.assertRaises(SystemExit):
                host.cmd_show(["missing"])

            with patch("trainsh.commands.host.prompt_input", return_value="y"):
                text = capture_output(host.cmd_rm, ["colab-box"])
            self.assertIn("Host removed: colab-box", text)
            self.assertNotIn("colab-box", host.load_hosts())

            with patch("trainsh.commands.host.prompt_input", return_value="n"):
                text = capture_output(host.cmd_rm, ["gpu-box"])
            self.assertIn("Cancelled.", text)

            text = capture_output(host.main, ["--help"])
            self.assertIn("train host", text)
            with self.assertRaises(SystemExit):
                host.main(["unknown"])

    def test_host_ssh_check_browse_and_edit_paths(self):
        with patched_config_files():
            host.save_hosts({"gpu-box": self._ssh_host(), "colab-box": self._colab_host()})

            with patch("trainsh.commands.host.os.system") as system_mock:
                host.cmd_ssh(["colab-box"])
            system_mock.assert_called_once()
            self.assertIn("cloudflared access ssh --hostname cf.colab", system_mock.call_args.args[0])

            ssh_client = MagicMock()
            ssh_client.connect_interactive.return_value = 0
            ssh_client.test_connection.return_value = True
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh_client):
                text = capture_output(host.cmd_test, ["gpu-box"])
                self.assertIn("Connection successful!", text)
                text = capture_output(host.cmd_ssh, ["gpu-box"])
                self.assertIn("Connecting to gpu-box", text)

            ssh_client.test_connection.return_value = False
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh_client):
                with self.assertRaises(SystemExit):
                    host.cmd_test(["gpu-box"])

            browser = MagicMock()
            browser.navigate.return_value = []
            ssh_client.test_connection.return_value = True
            with patch("trainsh.services.ssh.SSHClient.from_host", return_value=ssh_client), patch(
                "trainsh.services.sftp_browser.RemoteFileBrowser",
                return_value=browser,
            ), patch("builtins.input", side_effect=["q"]):
                text = capture_output(host.cmd_browse, ["gpu-box"])
            self.assertIn("File Browser: gpu-box", text)

            vast_host = Host(name="vast-box", type=HostType.VASTAI, hostname="vast", username="root", vast_instance_id="7")
            host.save_hosts({"vast-box": vast_host})
            client = MagicMock()
            text = ""
            with patch("trainsh.commands.host.prompt_input", return_value="vast label"), patch(
                "trainsh.services.vast_api.get_vast_client", return_value=client
            ):
                text = capture_output(host.cmd_edit, ["vast-box"])
            self.assertIn("Updated Vast.ai label: vast label", text)
            client.label_instance.assert_called_once_with(7, "vast label")


class StorageCommandTests(unittest.TestCase):
    def _storages(self):
        return {
            "artifacts": Storage(
                name="artifacts",
                type=StorageType.LOCAL,
                config={"path": "/tmp/out"},
                is_default=True,
            ),
            "cloud": Storage(
                name="cloud",
                type=StorageType.R2,
                config={"bucket": "bucket", "account_id": "acct"},
            ),
        }

    def test_storage_load_save_list_show_remove_and_main(self):
        with patched_config_files():
            storage.save_storages(self._storages())
            loaded = storage.load_storages()
            self.assertEqual(set(loaded), {"artifacts", "cloud"})

            text = capture_output(storage.cmd_list, [])
            self.assertIn("Configured storage backends:", text)
            self.assertIn("artifacts", text)
            self.assertIn("(default)", text)

            text = capture_output(storage.cmd_show, ["artifacts"])
            self.assertIn("Storage: artifacts", text)
            self.assertIn("Config:", text)

            with self.assertRaises(SystemExit):
                storage.cmd_show(["missing"])

            with patch("trainsh.commands.storage.prompt_input", return_value="y"):
                text = capture_output(storage.cmd_rm, ["cloud"])
            self.assertIn("Storage removed: cloud", text)

            with patch("trainsh.commands.storage.prompt_input", return_value="n"):
                text = capture_output(storage.cmd_rm, ["artifacts"])
            self.assertIn("Cancelled.", text)

            text = capture_output(storage.main, ["help"])
            self.assertIn("train storage", text)
            with self.assertRaises(SystemExit):
                storage.main(["unknown"])

    def test_storage_check_branches(self):
        with patched_config_files():
            storages = self._storages()
            storages["sshbox"] = Storage(
                name="sshbox",
                type=StorageType.SSH,
                config={"host": "root@example"},
            )
            storage.save_storages(storages)

            with patch("os.path.isdir", return_value=True):
                text = capture_output(storage.cmd_test, ["artifacts"])
            self.assertIn("Connection successful!", text)

            with patch("os.path.isdir", return_value=False):
                with self.assertRaises(SystemExit):
                    storage.cmd_test(["artifacts"])

            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=False):
                with self.assertRaises(SystemExit):
                    storage.cmd_test(["cloud"])

            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                "trainsh.services.transfer_engine.build_rclone_env",
                return_value={"RCLONE_CONFIG_CLOUD_TYPE": "s3"},
            ), patch(
                "trainsh.services.transfer_engine.get_rclone_remote_name",
                return_value="cloudremote",
            ), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="dir1\n", stderr="")):
                text = capture_output(storage.cmd_test, ["cloud"])
            self.assertIn("Using rclone remote: cloudremote:bucket", text)

            with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n", stderr="")):
                text = capture_output(storage.cmd_test, ["sshbox"])
            self.assertIn("Connection successful!", text)

            storages["other"] = Storage(
                name="other",
                type=StorageType.SMB,
                config={"server": "smb.example.com", "share": "teamshare", "username": "alice"},
            )
            storage.save_storages(storages)
            with patch("trainsh.services.transfer_engine.check_rclone_available", return_value=True), patch(
                "trainsh.services.transfer_engine.build_rclone_env",
                return_value={"RCLONE_CONFIG_OTHER_TYPE": "smb"},
            ), patch(
                "trainsh.services.transfer_engine.get_rclone_remote_name",
                return_value="otherremote",
            ), patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="share\n", stderr="")):
                text = capture_output(storage.cmd_test, ["other"])
            self.assertIn("Using rclone remote: otherremote:teamshare", text)


class TransferColabVastCommandTests(unittest.TestCase):
    def _write_colab(self, config_dir: Path):
        colab._save_colab_data(
            {
                "connections": [
                    {
                        "name": "demo",
                        "tunnel_type": "cloudflared",
                        "config": {"hostname": "cf.example.com"},
                        "password": "pw",
                    },
                    {
                        "name": "ngrok-demo",
                        "tunnel_type": "ngrok",
                        "config": {"hostname": "tcp.ngrok.io", "port": 2222},
                        "password": "pw",
                    },
                ]
            }
        )

    def test_transfer_parse_and_main_paths(self):
        self.assertEqual(transfer.parse_endpoint("@gpu:/tmp/out"), ("host", "/tmp/out", "gpu"))
        self.assertEqual(transfer.parse_endpoint("host:gpu:/tmp/out"), ("host", "/tmp/out", "gpu"))
        self.assertEqual(transfer.parse_endpoint("storage:artifacts:/tmp/out"), ("storage", "/tmp/out", "artifacts"))
        self.assertEqual(transfer.parse_endpoint("./data"), ("local", "./data", None))

        text = capture_output(transfer.main, ["--help"])
        self.assertIn("train transfer", text)
        with self.assertRaises(SystemExit):
            transfer.main(["--bad"])
        with self.assertRaises(SystemExit):
            transfer.main(["src-only"])
        with self.assertRaises(SystemExit):
            transfer.main(["a", "b", "c"])

        fake_result = SimpleNamespace(success=True, message="ok", bytes_transferred=123)
        engine = MagicMock()
        engine.rsync.return_value = fake_result
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=engine):
            text = capture_output(transfer.main, ["./src", "./dst", "--delete", "--exclude", "*.tmp", "--dry-run"])
        self.assertIn("(dry run", text)
        engine.rsync.assert_called_once()

        cloud_storage = Storage(name="artifacts", type=StorageType.R2, config={"bucket": "bucket"})
        engine = MagicMock()
        engine.rclone.return_value = fake_result
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=engine), patch(
            "trainsh.commands.storage.load_storages",
            return_value={"artifacts": cloud_storage},
        ), patch("trainsh.services.transfer_engine.get_rclone_remote_name", return_value="remote"), patch(
            "trainsh.services.transfer_engine.build_rclone_env",
            return_value={},
        ):
            text = capture_output(transfer.main, ["./src", "storage:artifacts:/logs"])
        self.assertIn("Source: ./src", text)
        self.assertIn("Destination: remote:bucket/logs", text)
        engine.rclone.assert_called_once()

        engine = MagicMock()
        engine.transfer.return_value = fake_result
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=engine):
            text = capture_output(transfer.main, ["@gpu:/in", "./out"])
        self.assertIn("Note: For host transfers", text)

        engine = MagicMock()
        engine.transfer.return_value = fake_result
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=engine), patch(
            "trainsh.commands.storage.load_storages",
            return_value={"artifacts": cloud_storage},
        ), patch("trainsh.commands.host.load_hosts", return_value={"gpu": Host(name="gpu", type=HostType.SSH, hostname="gpu.example.com", username="root")}):
            text = capture_output(transfer.main, ["@gpu:/in", "storage:artifacts:/logs"])
        self.assertIn("relay through a local temp directory", text)
        engine.transfer.assert_called_once()

        engine = MagicMock()
        engine.transfer.return_value = SimpleNamespace(success=False, message="Dry run is not supported for relayed host-to-cloud transfers.", bytes_transferred=0)
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=engine), patch(
            "trainsh.commands.storage.load_storages",
            return_value={"artifacts": cloud_storage},
        ), patch("trainsh.commands.host.load_hosts", return_value={"gpu": Host(name="gpu", type=HostType.SSH, hostname="gpu.example.com", username="root")}):
            with self.assertRaises(SystemExit):
                transfer.main(["@gpu:/in", "storage:artifacts:/logs", "--dry-run"])

        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=engine), patch(
            "trainsh.commands.storage.load_storages",
            return_value={},
        ):
            with self.assertRaises(SystemExit):
                transfer.main(["storage:missing:/in", "./out"])

    def test_colab_and_vast_commands(self):
        with patched_config_files() as config_dir:
            text = capture_output(colab.main, ["--help"])
            self.assertIn("train colab", text)
            with self.assertRaises(SystemExit):
                colab.main(["unknown"])

            text = capture_output(colab.cmd_list, [])
            self.assertIn("No Colab connections configured.", text)

            with patch("trainsh.commands.colab.prompt_input", side_effect=["demo", "1", "cf.example.com", "pw"]):
                text = capture_output(colab.cmd_connect, [])
            self.assertIn("Added Colab connection: demo", text)
            self._write_colab(config_dir)

            text = capture_output(colab.cmd_list, [])
            self.assertIn("Colab connections:", text)
            self.assertIn("demo", text)

            with patch("os.system") as system_mock:
                colab.cmd_ssh(["demo"])
            self.assertIn("cloudflared access ssh", system_mock.call_args.args[0])

            with patch("os.system") as system_mock:
                text = capture_output(colab.cmd_run, ["python", "-V"])
            self.assertIn("Running on Colab: python -V", text)
            system_mock.assert_called_once()

            with patch("os.system"):
                with self.assertRaises(SystemExit):
                    colab.cmd_ssh(["missing"])

            with self.assertRaises(SystemExit):
                colab.cmd_run([])

        text = capture_output(vast.main, ["help"])
        self.assertIn("train vast", text)
        with self.assertRaises(SystemExit):
            vast.main(["unknown"])

        client = MagicMock()
        running = SimpleNamespace(id=123, actual_status="running", ssh_host="ssh.host", public_ipaddr="1.1.1.1", ssh_port=2222)
        stopped = SimpleNamespace(id=124, actual_status="stopped", ssh_host=None, public_ipaddr=None, ssh_port=None)

        with patch("trainsh.services.vast_api.get_vast_client", return_value=client):
            with patch("trainsh.utils.vast_formatter.print_instance_table") as table_mock:
                vast.cmd_list([])
            table_mock.assert_called_once()

            client.get_instance.return_value = None
            with self.assertRaises(SystemExit):
                vast.cmd_show(["123"])

            client.get_instance.return_value = running
            with patch("trainsh.utils.vast_formatter.print_instance_detail") as detail_mock:
                vast.cmd_show(["123"])
            detail_mock.assert_called_once()

            client.get_instance.return_value = stopped
            with self.assertRaises(SystemExit):
                vast.cmd_ssh(["124"])

            client.get_instance.return_value = running
            with patch("trainsh.commands.vast.os.system") as system_mock:
                text = capture_output(vast.cmd_ssh, ["123"])
            self.assertIn("Connecting to ssh.host:2222", text)
            system_mock.assert_called_once()

            text = capture_output(vast.cmd_start, ["123"])
            self.assertIn("Instance started.", text)
            text = capture_output(vast.cmd_stop, ["123"])
            self.assertIn("Instance stopped.", text)
            text = capture_output(vast.cmd_reboot, ["123"])
            self.assertIn("Instance rebooting.", text)

            with patch("trainsh.commands.vast.prompt_input", return_value="n"):
                text = capture_output(vast.cmd_rm, ["123"])
            self.assertIn("Cancelled.", text)
            with patch("trainsh.commands.vast.prompt_input", return_value="y"):
                text = capture_output(vast.cmd_rm, ["123"])
            self.assertIn("Instance removed.", text)

            client.search_offers.return_value = []
            with patch(
                "trainsh.utils.vast_formatter.get_currency_settings",
                return_value=SimpleNamespace(display_currency="USD"),
            ):
                text = capture_output(vast.cmd_search, [])
            self.assertIn("No offers found.", text)

            offer = SimpleNamespace(id=1, gpu_name="A100", num_gpus=1, dph_total=1.25, gpu_ram=81920)
            client.search_offers.return_value = [offer]
            currency = SimpleNamespace(display_currency="CNY", rates=SimpleNamespace(convert=lambda *args: 9.0))
            with patch("trainsh.utils.vast_formatter.get_currency_settings", return_value=currency), patch(
                "trainsh.services.pricing.format_currency",
                return_value="CNY 9.00",
            ):
                text = capture_output(vast.cmd_search, [])
            self.assertIn("CNY/hr", text)
            self.assertIn("A100", text)

            client.list_ssh_keys.return_value = []
            text = capture_output(vast.cmd_keys, [])
            self.assertIn("No SSH keys registered.", text)
            client.list_ssh_keys.return_value = [{"ssh_key": "ssh-rsa " + "x" * 80}]
            text = capture_output(vast.cmd_keys, [])
            self.assertIn("Registered SSH keys:", text)

            with tempfile.TemporaryDirectory() as tmpdir:
                key_path = Path(tmpdir) / "id_rsa.pub"
                key_path.write_text("ssh-rsa AAAATEST", encoding="utf-8")
                text = capture_output(vast.cmd_attach_key, [str(key_path)])
            self.assertIn("SSH key attached successfully.", text)

            with self.assertRaises(SystemExit):
                vast.cmd_attach_key(["/missing/key.pub"])

            client.search_offers.side_effect = RuntimeError("missing VAST_API_KEY")
            text = capture_output(vast.main, ["search"])
            self.assertIn("Make sure VAST_API_KEY is set", text)


if __name__ == "__main__":
    unittest.main()
