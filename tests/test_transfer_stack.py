import tempfile
import unittest
import subprocess
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.executor_transfer import TransferHelper
from trainsh.core.models import (
    AuthMethod,
    Host,
    HostType,
    Storage,
    StorageType,
    TransferEndpoint,
)
from trainsh.services.sftp_browser import FileEntry, RemoteFileBrowser
from trainsh.services.transfer_engine import (
    TransferEngine,
    TransferPlan,
    TransferProgress,
    analyze_transfer,
    build_rclone_env,
    check_rclone_available,
    check_rsync_available,
    get_rclone_remote_name,
    rsync_with_progress,
    _parse_rsync_progress,
)


class TransferEngineHelpersTests(unittest.TestCase):
    def _host(self, **overrides):
        data = {
            "name": "gpu",
            "type": HostType.SSH,
            "hostname": "gpu.example.com",
            "port": 2222,
            "username": "root",
            "auth_method": AuthMethod.KEY,
            "ssh_key_path": "~/.ssh/id_rsa",
            "jump_host": "jump-box",
            "env_vars": {"tunnel_type": "cloudflared", "cloudflared_hostname": "cf.example.com"},
        }
        data.update(overrides)
        return Host(**data)

    def _storage(self, name="artifacts", type_=StorageType.R2, **config):
        return Storage(name=name, type=type_, config=config)

    def test_build_rclone_env_and_remote_name(self):
        secrets = MagicMock()
        secrets.get.side_effect = lambda key: {
            "ARTIFACTS_ACCESS_KEY_ID": "AKIA",
            "ARTIFACTS_SECRET_ACCESS_KEY": "SECRET",
            "B2_APPLICATION_KEY_ID": "b2id",
            "B2_APPLICATION_KEY": "b2key",
            "GOOGLE_DRIVE_CREDENTIALS": '{"token":"abc"}',
        }.get(key)

        with patch("trainsh.services.transfer_engine.get_secrets_manager", return_value=secrets):
            env = build_rclone_env(self._storage(account_id="acct"))
            self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_ACCESS_KEY_ID"], "AKIA")
            self.assertIn("acct.r2.cloudflarestorage.com", env["RCLONE_CONFIG_ARTIFACTS_ENDPOINT"])

            env = build_rclone_env(self._storage(type_=StorageType.S3, region="us-east-1", endpoint="https://s3.local"))
            self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_REGION"], "us-east-1")

            env = build_rclone_env(self._storage(type_=StorageType.B2))
            self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_ACCOUNT"], "b2id")

            env = build_rclone_env(
                self._storage(
                    type_=StorageType.GOOGLE_DRIVE,
                    client_id="cid",
                    client_secret="sec",
                    root_folder_id="root",
                    remote_name="drive",
                )
            )
            self.assertEqual(env["RCLONE_CONFIG_DRIVE_CLIENT_ID"], "cid")
            self.assertIn("TOKEN", "".join(env.keys()))

            env = build_rclone_env(self._storage(type_=StorageType.GOOGLE_DRIVE, remote_name="drive"))
            self.assertTrue(env["RCLONE_CONFIG_DRIVE_TYPE"], "drive")

            env = build_rclone_env(self._storage(type_=StorageType.GCS, project_id="pid", service_account_json="{}"))
            self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_PROJECT_NUMBER"], "pid")

            env = build_rclone_env(self._storage(type_=StorageType.SSH, host="ssh.example.com", user="root", port=22))
            self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_HOST"], "ssh.example.com")

            env = build_rclone_env(self._storage(type_=StorageType.SMB, host="smb", user="u", password="p", domain="d"))
            self.assertEqual(env["RCLONE_CONFIG_ARTIFACTS_DOMAIN"], "d")

            env = build_rclone_env(
                self._storage(
                    name="sshbox",
                    type_=StorageType.SSH,
                    host="root@ssh.example.com",
                    key_path="~/.ssh/id_ed25519",
                )
            )
            self.assertEqual(env["RCLONE_CONFIG_SSHBOX_HOST"], "ssh.example.com")
            self.assertEqual(env["RCLONE_CONFIG_SSHBOX_USER"], "root")
            self.assertIn("KEY_FILE", "".join(env.keys()))

            env = build_rclone_env(
                self._storage(
                    name="smbbox",
                    type_=StorageType.SMB,
                    server="smb.example.com",
                    username="alice",
                )
            )
            self.assertEqual(env["RCLONE_CONFIG_SMBBOX_HOST"], "smb.example.com")
            self.assertEqual(env["RCLONE_CONFIG_SMBBOX_USER"], "alice")

        gdrive = self._storage(type_=StorageType.GOOGLE_DRIVE, remote_name="drive")
        self.assertEqual(get_rclone_remote_name(gdrive), "drive")
        self.assertEqual(get_rclone_remote_name(self._storage(name="my-bucket")), "my-bucket")

    def test_transfer_engine_core_paths(self):
        engine = TransferEngine()
        src = TransferEndpoint(type="local", path="./src")
        dst = TransferEndpoint(type="local", path="./dst")
        with patch.object(engine, "rsync", return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=12)) as rsync:
            result = engine.transfer(src, dst)
        self.assertTrue(result.success)
        rsync.assert_called_once()

        cloud = self._storage(type_=StorageType.R2, bucket="bucket")
        src = TransferEndpoint(type="storage", path="/in", storage_id="artifacts")
        dst = TransferEndpoint(type="local", path="./out")
        with patch.object(engine, "rclone", return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=7)) as rclone:
            result = engine.transfer(src, dst, storages={"artifacts": cloud})
        self.assertTrue(result.success)
        rclone.assert_called_once()

        ssh_storage = self._storage(type_=StorageType.SSH, host="ssh.example.com", user="root", port=22)
        host_src = TransferEndpoint(type="storage", path="/in", storage_id="sshbox")
        host_dst = TransferEndpoint(type="host", path="/out", host_id="gpu")
        with patch.object(engine, "_transfer_host_to_host", return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=5)) as h2h:
            result = engine.transfer(host_src, host_dst, hosts={"gpu": self._host()}, storages={"sshbox": ssh_storage})
        self.assertTrue(result.success)
        h2h.assert_called_once()

        host_src = TransferEndpoint(type="host", path="/workspace/out", host_id="gpu")
        cloud_dst = TransferEndpoint(type="storage", path="/logs", storage_id="artifacts")
        with patch.object(
            engine,
            "rsync",
            return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=6),
        ) as rsync, patch.object(
            engine,
            "rclone",
            return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=7),
        ) as rclone:
            result = engine.transfer(host_src, cloud_dst, hosts={"gpu": self._host()}, storages={"artifacts": cloud})
        self.assertTrue(result.success)
        rsync.assert_called_once()
        rclone.assert_called_once()

        with patch.object(
            engine,
            "_rsync_remote_to_remote",
            return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=1),
        ) as remote, patch.object(engine, "_check_host_connectivity", return_value=True):
            result = engine._transfer_host_to_host(
                TransferEndpoint(type="host", path="/src", host_id="a"),
                TransferEndpoint(type="host", path="/dst", host_id="b"),
                self._host(hostname="src.example.com", username="alice", env_vars={}),
                self._host(hostname="dst.example.com", username="bob", env_vars={}),
                dry_run=True,
            )
        self.assertTrue(result.success)
        self.assertTrue(remote.call_args.args[-1])

        self.assertEqual(engine._select_transfer_tool(src, dst, {"artifacts": cloud}), "rclone")
        self.assertEqual(engine._select_transfer_tool(host_src, dst, {"sshbox": ssh_storage}), "rsync")
        self.assertEqual(engine._resolve_proxy_command(self._host(env_vars={"proxy_command": "proxy"})), "proxy")
        self.assertIn("cloudflared access ssh", engine._resolve_proxy_command(self._host()))
        self.assertIsNone(engine._resolve_proxy_command(self._host(env_vars={})))

        with patch("os.path.exists", return_value=True):
            ssh_args = engine._build_ssh_args(self._host())
        self.assertIn("ProxyCommand=cloudflared access ssh --hostname cf.example.com", " ".join(ssh_args))
        self.assertIn("root@gpu.example.com", ssh_args)
        self.assertNotIn("-J", ssh_args)
        with patch("os.path.exists", return_value=True):
            ssh_args = engine._build_ssh_args(self._host(env_vars={"tunnel_type": ""}))
        self.assertIn("-J", ssh_args)
        self.assertEqual(engine._build_scp_spec(self._host(username="root"), "/tmp/out"), "root@gpu.example.com:/tmp/out")
        with patch(
            "trainsh.services.host_resolver.prepare_vast_host",
            return_value=self._host(name="vast", hostname="vast.example.com", port=2200, env_vars={}),
        ):
            self.assertEqual(
                engine._build_scp_spec(Host(name="vast", type=HostType.VASTAI, vast_instance_id="123", username="root"), "/tmp/out"),
                "root@vast.example.com:/tmp/out",
            )

        resolved = engine._resolve_endpoint(
            TransferEndpoint(type="storage", path="/logs", storage_id="artifacts"),
            {},
            {"artifacts": cloud},
            for_rclone=True,
        )
        self.assertEqual(resolved, "artifacts:/logs")
        resolved = engine._resolve_endpoint_for_rclone(
            TransferEndpoint(type="storage", path="/logs", storage_id="artifacts"),
            {},
            {"artifacts": cloud},
        )
        self.assertEqual(resolved, "artifacts:bucket/logs")

        local_storage = self._storage(name="cache", type_=StorageType.LOCAL, path="/tmp/cache")
        with patch.object(
            engine,
            "rsync",
            return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=4),
        ) as rsync:
            result = engine.transfer(
                TransferEndpoint(type="storage", path="/logs", storage_id="cache"),
                TransferEndpoint(type="local", path="./out"),
                storages={"cache": local_storage},
            )
        self.assertTrue(result.success)
        self.assertEqual(rsync.call_args.kwargs["source"], "/tmp/cache/logs")

        cli_ssh_storage = self._storage(
            name="sshbox",
            type_=StorageType.SSH,
            host="root@ssh.example.com",
            path="/srv/data",
            key_path="~/.ssh/id_ed25519",
        )
        with patch.object(
            engine,
            "rsync",
            return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=4),
        ) as rsync:
            result = engine.transfer(
                TransferEndpoint(type="storage", path="/logs", storage_id="sshbox"),
                TransferEndpoint(type="local", path="./out"),
                storages={"sshbox": cli_ssh_storage},
            )
        self.assertTrue(result.success)
        self.assertEqual(rsync.call_args.kwargs["source"], "/srv/data/logs")
        self.assertEqual(rsync.call_args.kwargs["host"].hostname, "ssh.example.com")
        self.assertEqual(rsync.call_args.kwargs["host"].username, "root")

    def test_remote_transfer_strategies_and_progress_helpers(self):
        engine = TransferEngine()
        src_host = self._host(hostname="src.example.com", username="alice", port=22, env_vars={})
        dst_host = self._host(hostname="dst.example.com", username="bob", port=2200, env_vars={})
        src = TransferEndpoint(type="host", path="/src", host_id="src")
        dst = TransferEndpoint(type="host", path="/dst/", host_id="dst")

        with patch.object(engine, "_check_host_connectivity", return_value=True), patch.object(
            engine, "_rsync_remote_to_remote", return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=1)
        ) as remote:
            result = engine._transfer_host_to_host(src, dst, src_host, dst_host)
        self.assertTrue(result.success)
        remote.assert_called_once()

        with patch.object(engine, "_check_host_connectivity", return_value=False), patch.object(
            engine, "_scp_three_way", return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=1)
        ) as relay:
            result = engine._transfer_host_to_host(src, dst, src_host, dst_host)
        self.assertTrue(result.success)
        relay.assert_called_once()

        result = engine._scp_three_way(src, dst, src_host, dst_host, dry_run=True)
        self.assertFalse(result.success)
        self.assertIn("Dry run is not supported", result.message)

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok\n")):
            self.assertTrue(engine._check_host_connectivity(src_host, dst_host))
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            self.assertFalse(engine._check_host_connectivity(src_host, dst_host))

        process = MagicMock()
        process.stdout = iter(["sent 1,024 bytes\n"])
        process.returncode = 0
        with patch("subprocess.Popen", return_value=process):
            result = engine._rsync_remote_to_remote(src, dst, src_host, dst_host)
        self.assertTrue(result.success)
        self.assertEqual(result.bytes_transferred, 1024)

        process = MagicMock()
        process.communicate.return_value = ("", "")
        process.returncode = 0
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)), patch("subprocess.Popen", return_value=process):
            result = engine._scp_three_way(src, dst, src_host, dst_host)
        self.assertTrue(result.success)

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)), patch(
            "subprocess.Popen", side_effect=Exception("boom")
        ):
            result = engine._scp_three_way(src, dst, src_host, dst_host)
        self.assertFalse(result.success)

        self.assertEqual(repr(TransferPlan("rsync", "direct")), "TransferPlan(method=rsync, via=direct)")
        cloud = self._storage(type_=StorageType.R2, bucket="bucket")
        plan = analyze_transfer(src, TransferEndpoint(type="storage", path="/dst", storage_id="artifacts"), storages={"artifacts": cloud})
        self.assertEqual(plan.method, "rclone")
        plan = analyze_transfer(src, dst)
        self.assertEqual(plan.method, "rsync")

        progress = _parse_rsync_progress("  1,024  12%    1.23MB/s    0:01:23")
        self.assertIsInstance(progress, TransferProgress)
        self.assertIsNone(_parse_rsync_progress("nonsense"))

        callback = MagicMock()
        process = MagicMock()
        process.stdout.readline.side_effect = ["  1,024  12%    1.23MB/s    0:01:23\n", "sent 2,048 bytes\n", ""]
        process.wait.return_value = 0
        with patch("subprocess.Popen", return_value=process):
            result = rsync_with_progress("./src", "./dst", progress_callback=callback)
        self.assertTrue(result.success)
        callback.assert_called()

        with patch("subprocess.Popen", side_effect=Exception("boom")):
            result = rsync_with_progress("./src", "./dst")
        self.assertFalse(result.success)

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
            self.assertTrue(check_rsync_available())
            self.assertTrue(check_rclone_available())
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            self.assertFalse(check_rsync_available())
            self.assertFalse(check_rclone_available())

    def test_rsync_and_rclone_process_branches(self):
        engine = TransferEngine()
        host = self._host(env_vars={})

        process = MagicMock()
        process.stdout = iter(["sent 2,048 bytes\n"])
        process.returncode = 0
        with patch("os.path.exists", return_value=True), patch("subprocess.Popen", return_value=process):
            result = engine.rsync("./src", "/dst", host=host, upload=True, delete=True, exclude=["*.tmp"], use_gitignore=True, dry_run=True)
        self.assertTrue(result.success)
        self.assertEqual(result.bytes_transferred, 2048)

        with patch("subprocess.Popen", side_effect=Exception("boom")):
            result = engine.rsync("./src", "./dst")
        self.assertFalse(result.success)

        process = MagicMock()
        process.stdout = iter(["Transferred: 1.5 MiB\n"])
        process.returncode = 0
        with patch("subprocess.Popen", return_value=process):
            result = engine.rclone("src", "dst", src_storage=self._storage())
        self.assertTrue(result.success)
        self.assertGreater(result.bytes_transferred, 1024 * 1024)

        with patch("subprocess.Popen", side_effect=FileNotFoundError()):
            result = engine.rclone("src", "dst")
        self.assertFalse(result.success)
        self.assertIn("rclone not found", result.message)

        process = MagicMock()
        process.stdout = iter(["Transferred: 2 GiB\n", "Transferred: bad MiB\n"])
        process.returncode = 1
        with patch("subprocess.Popen", return_value=process):
            result = engine.rclone("src", "dst", dry_run=True, delete=True, operation="sync", dst_storage=self._storage())
        self.assertFalse(result.success)
        self.assertGreater(result.bytes_transferred, 1024 * 1024 * 1024)

        with patch("subprocess.Popen", side_effect=RuntimeError("boom")):
            result = engine.rclone("src", "dst")
        self.assertFalse(result.success)
        self.assertEqual(result.message, "boom")

    def test_transfer_engine_more_branch_paths(self):
        engine = TransferEngine()
        host = self._host(env_vars={})
        cloud = self._storage(type_=StorageType.R2, bucket="bucket")
        ssh_storage = self._storage(name="sshbox", type_=StorageType.SSH, host="ssh.example.com", user="root", port=2200)

        process = MagicMock()
        process.stdout = iter(["sent 512 bytes\n"])
        process.returncode = 0
        with patch("os.path.exists", return_value=False), patch("subprocess.Popen", return_value=process):
            result = engine.rsync("/remote/src", "./dst", host=host, upload=False, compress=False)
        self.assertTrue(result.success)
        self.assertEqual(result.bytes_transferred, 512)

        src = TransferEndpoint(type="local", path="./src")
        dst = TransferEndpoint(type="storage", path="/out", storage_id="sshbox")
        with patch.object(engine, "rsync", return_value=SimpleNamespace(success=True, exit_code=0, message="ok", bytes_transferred=1)) as mocked_rsync:
            result = engine.transfer(src, dst, storages={"sshbox": ssh_storage})
        self.assertTrue(result.success)
        mocked_rsync.assert_called_once()

        self.assertEqual(engine._select_transfer_tool(src, dst, {"sshbox": ssh_storage}), "rsync")
        self.assertEqual(engine._storage_to_host(ssh_storage).port, 2200)

        process = MagicMock()
        process.stdout = iter(["error line\n"])
        process.returncode = 1
        src_ep = TransferEndpoint(type="host", path="/src", host_id="src")
        dst_ep = TransferEndpoint(type="host", path="/dst", host_id="dst")
        src_host = self._host(hostname="src.example.com", username="alice", port=22, env_vars={})
        dst_host = self._host(hostname="dst.example.com", username="bob", port=2222, env_vars={})
        with patch("subprocess.Popen", return_value=process):
            result = engine._rsync_remote_to_remote(src_ep, dst_ep, src_host, dst_host, delete=True, exclude=["*.tmp"])
        self.assertFalse(result.success)
        self.assertIn("error line", result.message)

        with patch("subprocess.Popen", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            result = engine._rsync_remote_to_remote(src_ep, dst_ep, src_host, dst_host)
        self.assertFalse(result.success)
        self.assertIn("timed out", result.message)

        with patch("subprocess.Popen", side_effect=RuntimeError("boom")):
            result = engine._rsync_remote_to_remote(src_ep, dst_ep, src_host, dst_host)
        self.assertFalse(result.success)
        self.assertEqual(result.message, "boom")

        process = MagicMock()
        process.communicate.return_value = ("bad", "")
        process.returncode = 2
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1)), patch("subprocess.Popen", return_value=process):
            result = engine._scp_three_way(src_ep, TransferEndpoint(type="host", path="/dst", host_id="dst"), src_host, dst_host)
        self.assertFalse(result.success)
        self.assertIn("Pipe transfer failed", result.message)

        self.assertIsNone(engine._resolve_proxy_command(self._host(env_vars={"tunnel_type": "cloudflared", "cloudflared_hostname": ""})))
        self.assertEqual(engine._resolve_endpoint(TransferEndpoint(type="local", path="~/x"), {}, {}), os.path.expanduser("~/x"))
        self.assertEqual(engine._resolve_endpoint(TransferEndpoint(type="host", path="/x", host_id="gpu"), {}, {}), "/x")
        self.assertEqual(engine._resolve_endpoint(TransferEndpoint(type="storage", path="/x", storage_id="missing"), {}, {}, for_rclone=True), "/x")
        self.assertEqual(engine._resolve_endpoint_for_rclone(TransferEndpoint(type="storage", path="/x", storage_id="missing"), {}, {}), "/x")
        self.assertEqual(engine._resolve_endpoint_for_rclone(TransferEndpoint(type="host", path="/x", host_id="gpu"), {}, {}), "/x")


class SftpBrowserAndTransferHelperTests(unittest.TestCase):
    def test_file_entry_and_browser_helpers(self):
        entry = FileEntry(name="demo.py", path="/tmp/demo.py", is_dir=False, size=1536)
        self.assertEqual(entry.display_size, "1.5 KB")
        self.assertEqual(entry.display_size, "1.5 KB")
        self.assertEqual(entry.size, 1536)
        self.assertEqual(entry.icon, "🐍")
        self.assertEqual(FileEntry(name="dir", path="/tmp/dir", is_dir=True).display_size, "<DIR>")

        ssh = MagicMock()

        def run_ok(cmd):
            if cmd == "echo $HOME":
                return SimpleNamespace(success=True, stdout="/home/demo\n")
            if cmd.startswith("ls -la"):
                return SimpleNamespace(
                    success=True,
                    stdout="total 4\ndrwxr-xr-x 2 root root 4096 2026-03-12 10:00 logs\n-rw-r--r-- 1 root root 12 2026-03-12 10:01 train.txt\n",
                )
            if cmd.startswith("head -n"):
                return SimpleNamespace(success=True, stdout="echo\n")
            if cmd.startswith("test -e"):
                return SimpleNamespace(success=True, stdout="yes\n")
            if cmd.startswith("df -B1"):
                return SimpleNamespace(success=True, stdout="fs 10 4 6 /\n")
            raise AssertionError(f"unexpected command: {cmd}")

        ssh.run.side_effect = run_ok
        browser = RemoteFileBrowser(ssh)
        entries = browser.list_directory("~")
        self.assertEqual(entries[0].name, "logs")
        self.assertEqual(entries[1].name, "train.txt")
        navigated = browser.navigate("/tmp")
        self.assertEqual(navigated, browser.cache["/tmp"])
        browser.current_path = "/tmp/subdir"
        up = browser.go_up()
        self.assertEqual(up, browser.cache["/tmp"])
        self.assertTrue(browser.read_file_head("/tmp/train.txt").strip())
        self.assertTrue(browser.path_exists("/tmp/train.txt"))
        self.assertEqual(browser.get_disk_usage("/"), {"total": 10, "used": 4, "available": 6})

        ssh.run.side_effect = [
            SimpleNamespace(success=False, stdout=""),
            SimpleNamespace(success=False, stdout=""),
            SimpleNamespace(success=True, stdout="bad"),
            SimpleNamespace(success=False, stdout=""),
        ]
        self.assertEqual(browser.list_directory("/missing"), [])
        self.assertEqual(browser.get_home_directory(), "~")
        self.assertFalse(browser.path_exists("/missing"))
        self.assertIsNone(browser.get_disk_usage("/missing"))

        ssh.run.side_effect = [SimpleNamespace(success=True, stdout="regular file|12|1710230400|root|root|-rw-r--r--")]
        info = browser.get_file_info("/tmp/train.txt")
        self.assertEqual(info.name, "train.txt")
        self.assertEqual(info.owner, "root")

        ssh.run.side_effect = [SimpleNamespace(success=False, stdout=""), SimpleNamespace(success=True, stdout="bad|parts")]
        self.assertIsNone(browser.get_file_info("/missing"))
        self.assertIsNone(browser.get_file_info("/bad"))

    def test_transfer_helper_branches(self):
        executor = SimpleNamespace(
            recipe=SimpleNamespace(hosts={"gpu": "ssh://gpu", "cloud": "vast:123"}, storages={"artifacts": "r2:bucket", "direct": {"type": "local", "config": {"path": "/tmp/out"}}}),
            _interpolate=lambda value: value.replace("$RUN", "demo"),
            logger=MagicMock(),
        )
        helper = TransferHelper(executor, resolve_vast_host=lambda inst: f"root@vast-{inst}", host_from_ssh_spec=lambda spec: Host(name=spec, type=HostType.SSH, hostname=spec))

        step = SimpleNamespace(source="./src", dest="./dst", delete="true", operation="copy", exclude="*.tmp,*.log")
        with patch.object(helper, "transfer", return_value=(True, "done")) as transfer_call:
            ok, msg = helper.exec_transfer(step)
        self.assertTrue(ok)
        self.assertEqual(msg, "done")
        transfer_call.assert_called_once()

        ok, msg = helper.transfer("", "./dst")
        self.assertFalse(ok)
        self.assertIn("requires both source", msg)

        ok, msg = helper.transfer("./src", "./dst", operation="move")
        self.assertFalse(ok)
        self.assertIn("Unsupported transfer operation", msg)

        fake_result = SimpleNamespace(success=True, message="ok", bytes_transferred=42)
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=MagicMock(transfer=MagicMock(return_value=fake_result))):
            ok, msg = helper.transfer("./src", "./dst", operation="sync")
        self.assertTrue(ok)
        self.assertIn("42 bytes", msg)

        fake_result = SimpleNamespace(success=False, message="boom", bytes_transferred=0)
        with patch("trainsh.services.transfer_engine.TransferEngine", return_value=MagicMock(transfer=MagicMock(return_value=fake_result))):
            ok, msg = helper.transfer("./src", "./dst")
        self.assertFalse(ok)
        self.assertEqual(msg, "boom")

        with patch("trainsh.commands.host.load_hosts", return_value={"shared": self._host()}):
            endpoint = helper.parse_endpoint("@artifacts:/logs")
            self.assertEqual(endpoint.type, "storage")
            endpoint = helper.parse_endpoint("@gpu:/logs")
            self.assertEqual(endpoint.type, "host")
            endpoint = helper.parse_endpoint("@shared:/logs")
            self.assertEqual(endpoint.host_id, "shared")
            endpoint = helper.parse_endpoint("host:gpu:/logs")
            self.assertEqual(endpoint.host_id, "gpu")
            endpoint = helper.parse_endpoint("storage:artifacts:/logs")
            self.assertEqual(endpoint.storage_id, "artifacts")
            endpoint = helper.parse_endpoint("~/logs")
            self.assertEqual(endpoint.type, "local")

        with patch("trainsh.commands.host.load_hosts", return_value={"shared": self._host()}):
            hosts = helper.build_transfer_hosts()
            self.assertIn("gpu", hosts)
            self.assertIn("vast:123", hosts)

        with patch("trainsh.commands.storage.load_storages", return_value={"global": self._storage(name="global", type_=StorageType.S3)}):
            storages = helper.build_transfer_storages()
            self.assertIn("artifacts", storages)
            self.assertIn("direct", storages)

    def _host(self):
        return Host(name="shared", type=HostType.SSH, hostname="shared.example.com")

    def _storage(self, name="artifacts", type_=StorageType.R2):
        return Storage(name=name, type=type_, config={"bucket": "bucket"})


if __name__ == "__main__":
    unittest.main()
