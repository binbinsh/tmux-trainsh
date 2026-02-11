import yaml
import unittest

from trainsh.commands.host import _host_to_dict
from trainsh.core.models import AuthMethod, Host, HostType


class HostYamlSerializationTests(unittest.TestCase):
    def test_host_to_dict_preserves_env_vars_and_lists(self):
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

        d = _host_to_dict(host)
        # Round-trip through YAML
        rendered = yaml.dump({"hosts": [d]}, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(rendered)
        parsed_host = parsed["hosts"][0]

        self.assertEqual(parsed_host["env_vars"]["connection_candidates"][0], "ssh://backup.example.com:22")
        self.assertEqual(parsed_host["env_vars"]["connection_candidates"][1], "cloudflared://ssh-access.example.com")
        self.assertEqual(
            parsed_host["env_vars"]["proxy_command"],
            "cloudflared access ssh --hostname ssh-access.example.com",
        )
        self.assertEqual(parsed_host["tags"], ["gpu", "prod"])

    def test_host_to_dict_preserves_structured_connection_candidates(self):
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

        d = _host_to_dict(host)
        # Round-trip through YAML
        rendered = yaml.dump({"hosts": [d]}, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(rendered)
        parsed_candidates = parsed["hosts"][0]["env_vars"]["connection_candidates"]

        self.assertEqual(parsed_candidates[0]["type"], "ssh")
        self.assertEqual(parsed_candidates[0]["hostname"], "backup.example.com")
        self.assertEqual(parsed_candidates[0]["port"], 22022)
        self.assertEqual(parsed_candidates[1]["type"], "cloudflared")
        self.assertEqual(parsed_candidates[1]["hostname"], "ssh-access.example.com")


if __name__ == "__main__":
    unittest.main()
