import unittest
import subprocess
from unittest.mock import patch

from trainsh.core.executor_utils import _host_from_ssh_spec
from trainsh.core.models import AuthMethod, Host, HostType
from trainsh.services.ssh import SSHClient
from trainsh.services.transfer_engine import TransferEngine


class SSHConnectionOptionsTests(unittest.TestCase):
    def test_ssh_client_uses_proxy_command_from_host_env(self):
        host = Host(
            name="target",
            type=HostType.SSH,
            hostname="172.16.0.88",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={"proxy_command": "wstunnel client -L stdio://%h:%p wss://example/ws"},
        )

        client = SSHClient.from_host(host)
        args = client._build_ssh_args("echo connected")

        self.assertIn("-o", args)
        self.assertIn("ProxyCommand=wstunnel client -L stdio://%h:%p wss://example/ws", args)
        self.assertNotIn("-J", args)

    def test_ssh_client_prefers_proxy_command_over_jump_host(self):
        client = SSHClient(
            hostname="172.16.0.88",
            port=22,
            username="root",
            jump_host="root@bastion.example.com",
            proxy_command="cloudflared access ssh --hostname ssh-access.example.com",
        )

        args = client._build_ssh_args("echo connected")

        self.assertIn("ProxyCommand=cloudflared access ssh --hostname ssh-access.example.com", args)
        self.assertNotIn("-J", args)

    def test_ssh_client_builds_proxy_command_from_cloudflared_env(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="172.16.0.88",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={
                "tunnel_type": "cloudflared",
                "cloudflared_hostname": "ssh-access.example.com",
                "cloudflared_bin": "/opt/homebrew/bin/cloudflared",
            },
        )

        client = SSHClient.from_host(host)
        args = client._build_ssh_args("echo connected")

        self.assertIn(
            "ProxyCommand=/opt/homebrew/bin/cloudflared access ssh --hostname ssh-access.example.com",
            args,
        )
        self.assertNotIn("-J", args)

    def test_ssh_client_manual_proxy_command_overrides_cloudflared_env(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="172.16.0.88",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={
                "tunnel_type": "cloudflared",
                "cloudflared_hostname": "ssh-access.example.com",
                "proxy_command": "wstunnel client -L stdio://%h:%p wss://example/ws",
            },
        )

        client = SSHClient.from_host(host)
        args = client._build_ssh_args("echo connected")

        self.assertIn("ProxyCommand=wstunnel client -L stdio://%h:%p wss://example/ws", args)
        self.assertNotIn("ssh-access.example.com", " ".join(args))

    def test_ssh_client_uses_jump_host_when_proxy_command_missing(self):
        client = SSHClient(
            hostname="172.16.0.88",
            port=22,
            username="root",
            jump_host="root@bastion.example.com",
        )

        args = client._build_ssh_args("echo connected")

        self.assertIn("-J", args)
        self.assertIn("root@bastion.example.com", args)

    def test_parse_proxy_command_from_ssh_spec(self):
        spec = "root@172.16.0.88 -o ProxyCommand='wstunnel client -L stdio://%h:%p wss://example/ws'"
        host = _host_from_ssh_spec(spec)
        self.assertEqual(host.env_vars.get("proxy_command"), "wstunnel client -L stdio://%h:%p wss://example/ws")

    def test_transfer_engine_builds_proxy_command_from_cloudflared_env(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="172.16.0.88",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={"tunnel_type": "cloudflared", "cloudflared_hostname": "ssh-access.example.com"},
        )

        engine = TransferEngine()
        args = engine._build_ssh_args(host)

        self.assertIn("ProxyCommand=cloudflared access ssh --hostname ssh-access.example.com", args)

    def test_ssh_client_parses_connection_candidates(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="primary.example.com",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={
                "connection_candidates": [
                    "ssh://backup.example.com:22",
                    "cloudflared://ssh-access.example.com",
                ],
            },
        )

        client = SSHClient.from_host(host)
        self.assertEqual(len(client.connection_targets), 3)
        self.assertEqual(client.connection_targets[1].hostname, "backup.example.com")
        self.assertEqual(client.connection_targets[1].port, 22)
        self.assertEqual(
            client.connection_targets[2].proxy_command,
            "cloudflared access ssh --hostname ssh-access.example.com",
        )

    def test_ssh_client_parses_structured_connection_candidates(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="primary.example.com",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={
                "connection_candidates": [
                    {"type": "ssh", "hostname": "backup.example.com", "port": 22022},
                    {
                        "type": "cloudflared",
                        "hostname": "ssh-access.example.com",
                        "cloudflared_bin": "/opt/homebrew/bin/cloudflared",
                    },
                ],
            },
        )

        client = SSHClient.from_host(host)
        self.assertEqual(len(client.connection_targets), 3)
        self.assertEqual(client.connection_targets[1].hostname, "backup.example.com")
        self.assertEqual(client.connection_targets[1].port, 22022)
        self.assertEqual(
            client.connection_targets[2].proxy_command,
            "/opt/homebrew/bin/cloudflared access ssh --hostname ssh-access.example.com",
        )

    def test_ssh_client_run_fallbacks_on_connection_failure(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="primary.example.com",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={
                "connection_candidates": [
                    "ssh://backup.example.com:22",
                    "cloudflared://ssh-access.example.com",
                ],
            },
        )
        client = SSHClient.from_host(host)

        first = subprocess.CompletedProcess(args=["ssh"], returncode=255, stdout="", stderr="network down")
        second = subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout="connected\n", stderr="")

        with patch("trainsh.services.ssh.subprocess.run", side_effect=[first, second]) as mocked_run:
            result = client.run("echo connected")

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(mocked_run.call_count, 2)
        first_args = mocked_run.call_args_list[0][0][0]
        second_args = mocked_run.call_args_list[1][0][0]
        self.assertIn("root@primary.example.com", first_args)
        self.assertIn("root@backup.example.com", second_args)

    def test_ssh_client_interactive_fallbacks_on_connection_failure(self):
        host = Host(
            name="case",
            type=HostType.SSH,
            hostname="primary.example.com",
            port=22,
            username="root",
            auth_method=AuthMethod.KEY,
            env_vars={
                "connection_candidates": [
                    "ssh://backup.example.com:22",
                    "cloudflared://ssh-access.example.com",
                ],
            },
        )
        client = SSHClient.from_host(host)

        first = subprocess.CompletedProcess(args=["ssh"], returncode=255, stdout="", stderr="network down")
        second = subprocess.CompletedProcess(args=["ssh"], returncode=255, stdout="", stderr="timeout")
        third = subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout="", stderr="")

        with patch("trainsh.services.ssh.subprocess.run", side_effect=[first, second, third]) as mocked_run:
            code = client.connect_interactive()

        self.assertEqual(code, 0)
        self.assertEqual(mocked_run.call_count, 3)
        third_args = mocked_run.call_args_list[2][0][0]
        third_opts = " ".join(third_args)
        self.assertIn("ProxyCommand=cloudflared access ssh --hostname ssh-access.example.com", third_opts)


if __name__ == "__main__":
    unittest.main()
