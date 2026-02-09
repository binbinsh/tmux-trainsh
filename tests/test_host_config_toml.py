import tomllib
import unittest

from trainsh.commands.host import _host_to_toml
from trainsh.core.models import AuthMethod, Host, HostType


class HostTomlSerializationTests(unittest.TestCase):
    def test_host_to_toml_preserves_env_vars_and_lists(self):
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
                "proxy_command": "cloudflared access ssh --hostname ssh-access.example.com",
            },
            tags=["gpu", "prod"],
        )

        rendered = _host_to_toml(host)
        parsed = tomllib.loads(rendered)
        parsed_host = parsed["hosts"][0]

        self.assertEqual(parsed_host["env_vars"]["connection_candidates"][0], "ssh://backup.example.com:22")
        self.assertEqual(parsed_host["env_vars"]["connection_candidates"][1], "cloudflared://ssh-access.example.com")
        self.assertEqual(
            parsed_host["env_vars"]["proxy_command"],
            "cloudflared access ssh --hostname ssh-access.example.com",
        )
        self.assertEqual(parsed_host["tags"], ["gpu", "prod"])

    def test_host_to_toml_preserves_structured_connection_candidates(self):
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
                    {"type": "cloudflared", "hostname": "ssh-access.example.com"},
                ],
            },
        )

        rendered = _host_to_toml(host)
        parsed = tomllib.loads(rendered)
        parsed_candidates = parsed["hosts"][0]["env_vars"]["connection_candidates"]

        self.assertEqual(parsed_candidates[0]["type"], "ssh")
        self.assertEqual(parsed_candidates[0]["hostname"], "backup.example.com")
        self.assertEqual(parsed_candidates[0]["port"], 22022)
        self.assertEqual(parsed_candidates[1]["type"], "cloudflared")
        self.assertEqual(parsed_candidates[1]["hostname"], "ssh-access.example.com")


if __name__ == "__main__":
    unittest.main()
