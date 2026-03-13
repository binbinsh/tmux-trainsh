import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.core.models import AuthMethod, Host, HostType
from trainsh.services.ssh import SSHClient, SSHConnectionTarget, SSHResult, get_system_info_script
from trainsh.utils.notifier import (
    Notifier,
    NotificationPayload,
    normalize_channels,
    normalize_level,
    parse_bool,
)


class NotifierTests(unittest.TestCase):
    def test_parse_bool_and_normalizers(self):
        self.assertTrue(parse_bool(True))
        self.assertTrue(parse_bool(1))
        self.assertTrue(parse_bool("yes"))
        self.assertFalse(parse_bool("off"))
        with self.assertRaises(ValueError):
            parse_bool("maybe")

        self.assertEqual(normalize_level("warn"), "warning")
        self.assertEqual(normalize_level("SUCCESS"), "success")
        with self.assertRaises(ValueError):
            normalize_level("bad")

        self.assertEqual(normalize_channels(None, ["log"]), ["log"])
        self.assertEqual(normalize_channels("log,system,log", []), ["log", "system"])
        self.assertEqual(normalize_channels(["command", "command", "webhook"], []), ["command", "webhook"])
        with self.assertRaises(ValueError):
            normalize_channels(123, [])
        with self.assertRaises(ValueError):
            normalize_channels("bad", [])

    def test_notify_and_channel_helpers(self):
        messages = []
        notifier = Notifier(log_callback=messages.append, app_name="train")

        ok, summary = notifier.notify(
            title="Done",
            message="Finished",
            level="info",
            channels=["log"],
            timeout_secs=0,
        )
        self.assertTrue(ok)
        self.assertIn("via log", summary)
        self.assertTrue(messages)

        ok, summary = notifier.notify(
            title="Done",
            message="",
            level="info",
            channels=[],
        )
        self.assertFalse(ok)
        self.assertIn("No notification channels", summary)

        with patch.object(notifier, "_send_log", return_value=(True, "ok")), patch.object(
            notifier, "_send_system", return_value=(False, "system down")
        ):
            ok, summary = notifier.notify(
                title="Done",
                message="Finished",
                level="info",
                channels=["log", "system"],
                fail_on_error=False,
            )
        self.assertTrue(ok)
        self.assertIn("failed: system", summary)
        self.assertTrue(any("ignored failures" in msg for msg in messages))

        with patch.object(notifier, "_send_log", return_value=(True, "ok")), patch.object(
            notifier, "_send_system", return_value=(False, "system down")
        ):
            ok, summary = notifier.notify(
                title="Done",
                message="Finished",
                level="info",
                channels=["log", "system"],
                fail_on_error=True,
            )
        self.assertFalse(ok)

        payload = NotificationPayload("app", 'a"b', 'c\\d', "info", "ts")
        self.assertIn('\\"', notifier._escape_osascript(payload.title))

    def test_system_webhook_command_and_run_cmd(self):
        logs = []
        notifier = Notifier(log_callback=logs.append, app_name="train")
        payload = NotificationPayload("app", "Title", "Body", "info", "ts")

        with patch("sys.platform", "linux"):
            ok, detail = notifier._send_system(payload, 5)
        self.assertFalse(ok)
        self.assertIn("Unsupported", detail)

        with patch("sys.platform", "darwin"), patch.object(notifier, "_run_cmd", return_value=(True, "ok")) as mocked:
            ok, detail = notifier._send_system(payload, 5)
        self.assertTrue(ok)
        mocked.assert_called_once()

        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=response):
            ok, detail = notifier._send_webhook(payload, "https://example.test", 5)
        self.assertTrue(ok)
        self.assertIn("HTTP 204", detail)

        response.status = 500
        with patch("urllib.request.urlopen", return_value=response):
            ok, detail = notifier._send_webhook(payload, "https://example.test", 5)
        self.assertFalse(ok)

        ok, detail = notifier._send_webhook(payload, None, 5)
        self.assertFalse(ok)
        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            ok, detail = notifier._send_webhook(payload, "https://example.test", 5)
        self.assertFalse(ok)
        self.assertIn("boom", detail)

        ok, detail = notifier._send_command(payload, None, 5)
        self.assertFalse(ok)
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            ok, detail = notifier._send_command(payload, "echo ok", 5)
        self.assertTrue(ok)
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="bad")):
            ok, detail = notifier._send_command(payload, "echo bad", 5)
        self.assertFalse(ok)
        self.assertIn("bad", detail)
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            ok, detail = notifier._send_command(payload, "echo bad", 5)
        self.assertFalse(ok)

        with patch("subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
            self.assertEqual(notifier._run_cmd(["echo"], 5), (True, "ok"))
        with patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="nope")):
            ok, detail = notifier._run_cmd(["echo"], 5)
        self.assertFalse(ok)
        self.assertIn("nope", detail)
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            ok, detail = notifier._run_cmd(["echo"], 5)
        self.assertFalse(ok)


class SSHTests(unittest.TestCase):
    def make_host(self, **overrides):
        data = {
            "name": "gpu",
            "type": HostType.SSH,
            "hostname": "gpu.example.com",
            "port": 2222,
            "username": "root",
            "auth_method": AuthMethod.KEY,
            "ssh_key_path": "~/.ssh/id_rsa",
            "jump_host": "jump.example.com",
            "env_vars": {
                "tunnel_type": "cloudflared",
                "cloudflared_hostname": "cf.example.com",
                "proxy_command": "",
                "connection_candidates": [
                    {"type": "ssh", "hostname": "gpu-alt", "port": 2200, "proxy_command": "proxy-cmd"},
                    {"type": "cloudflared", "hostname": "cf-alt.example.com"},
                    "ssh://gpu-third:2201",
                    "cloudflared://cf-token.example.com",
                ],
            },
        }
        data.update(overrides)
        return Host(**data)

    def test_candidate_parsing_and_arg_building(self):
        host = self.make_host()
        client = SSHClient.from_host(host)
        self.assertEqual(client.proxy_command, "cloudflared access ssh --hostname cf.example.com")
        self.assertGreaterEqual(len(client.connection_targets), 4)

        self.assertIsNone(SSHClient._build_cloudflared_proxy_command({}, "host"))
        self.assertIn("cloudflared access ssh", SSHClient._build_cloudflared_proxy_command({"tunnel_type": "cloudflared", "cloudflared_hostname": "cf.example.com"}, "host"))
        self.assertIsNone(SSHClient._parse_connection_candidate_token("", host, host.env_vars))
        self.assertIsNone(SSHClient._parse_connection_candidate_dict({"type": "ssh"}, host, host.env_vars))

        target = SSHConnectionTarget(hostname="gpu-alt", port=2200, proxy_command="proxy-cmd", source="candidate")
        args = client._build_ssh_args("echo hi", target=target)
        self.assertIn("-p", args)
        self.assertIn("ProxyCommand=proxy-cmd", " ".join(args))
        self.assertTrue(args[-2].startswith("root@"))

        no_proxy = SSHClient(
            hostname="gpu.example.com",
            port=22,
            username="root",
            jump_host="jump.example.com",
            connection_targets=[SSHConnectionTarget(hostname="gpu.example.com", port=22, jump_host="jump.example.com")],
        )
        args = no_proxy._build_ssh_args("echo hi")
        self.assertIn("-J", args)

        upload_args = no_proxy._build_scp_upload_args("./in", "/out", True, no_proxy.connection_targets[0])
        self.assertIn("-r", upload_args)
        download_args = no_proxy._build_scp_download_args("/out", "./in", False, no_proxy.connection_targets[0])
        self.assertNotIn("-r", download_args)

    def test_run_connect_upload_download_and_helpers(self):
        client = SSHClient(
            hostname="gpu.example.com",
            port=22,
            username="root",
            connection_targets=[
                SSHConnectionTarget(hostname="bad.example.com", port=22, source="bad"),
                SSHConnectionTarget(hostname="gpu.example.com", port=22, source="good"),
            ],
        )
        self.assertTrue(SSHResult(0, "ok", "").success)

        side_effects = [
            SimpleNamespace(returncode=255, stdout="", stderr="bad"),
            SimpleNamespace(returncode=0, stdout="ok", stderr=""),
        ]
        with patch("subprocess.run", side_effect=side_effects):
            result = client.run("echo hi", timeout=5)
        self.assertTrue(result.success)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 1)):
            result = client.run("echo hi", timeout=1)
        self.assertEqual(result.exit_code, -1)

        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            result = client.run("echo hi", timeout=1)
        self.assertIn("boom", result.stderr)

        with patch.object(client, "run", return_value=SSHResult(0, "connected\n", "")):
            self.assertTrue(client.test_connection())
        self.assertIn("ssh", client.get_ssh_command())

        with patch("subprocess.run", side_effect=[SimpleNamespace(returncode=255), SimpleNamespace(returncode=0)]):
            self.assertEqual(client.connect_interactive(), 0)

        with patch("subprocess.run", side_effect=[SimpleNamespace(returncode=255, stdout="", stderr="bad"), SimpleNamespace(returncode=0, stdout="ok", stderr="")]):
            result = client.upload_file("./in", "/out", recursive=True)
        self.assertTrue(result.success)

        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            result = client.upload_file("./in", "/out")
        self.assertFalse(result.success)

        with patch("subprocess.run", side_effect=[SimpleNamespace(returncode=255, stdout="", stderr="bad"), SimpleNamespace(returncode=0, stdout="ok", stderr="")]):
            result = client.download_file("/out", "./in")
        self.assertTrue(result.success)

        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            result = client.download_file("/out", "./in")
        self.assertFalse(result.success)

        script = get_system_info_script()
        self.assertIn("SYSTEM INFO", script)
        self.assertIn("GPU INFO", script)


if __name__ == "__main__":
    unittest.main()
