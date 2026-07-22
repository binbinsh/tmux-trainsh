import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import trainsh.core.secrets as secrets_mod


class VaultwardenBackendMoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tmp.name) / ".config" / "tmux-trainsh"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.yaml"
        self.patches = [
            patch.object(secrets_mod, "CONFIG_DIR", self.config_dir),
            patch.object(secrets_mod, "CONFIG_FILE", self.config_file),
        ]
        for p in self.patches:
            p.start()
        secrets_mod._secrets_manager = None

    def tearDown(self):
        secrets_mod._secrets_manager = None
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_bw_availability_helper(self):
        with patch("shutil.which", return_value="/usr/bin/bw"):
            self.assertTrue(secrets_mod._bw_available())
        with patch("shutil.which", return_value=None):
            self.assertFalse(secrets_mod._bw_available())

    def test_backend_creates_new_item_when_missing(self):
        calls = []

        def completed(returncode=0, stdout="", stderr=""):
            return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        def run_side_effect(cmd, input=None, capture_output=None, text=None, timeout=None, env=None):
            calls.append((cmd, input, env))
            if cmd[:3] == ["bw", "config", "server"]:
                return completed()
            if cmd[:4] == ["bw", "get", "item", "NEW_KEY"]:
                return completed(returncode=1, stderr="not found")
            if cmd[:2] == ["bw", "encode"]:
                payload = json.loads(input)
                self.assertEqual(payload["name"], "NEW_KEY")
                self.assertEqual(payload["login"]["password"], "secret")
                return completed(stdout="encoded-payload\n")
            if cmd[:3] == ["bw", "create", "item"]:
                return completed()
            return completed(returncode=1, stderr="unexpected")

        with patch("shutil.which", return_value="/usr/bin/bw"), patch(
            "trainsh.core.secrets.subprocess.run", side_effect=run_side_effect
        ), patch.dict("os.environ", {"BW_SESSION": "session-123"}):
            backend = secrets_mod.BitwardenCLIBackend()
            backend.set("NEW_KEY", "secret")

        self.assertIn(
            (["bw", "create", "item", "encoded-payload", "--session", "session-123"], None, {"BW_SESSION": "session-123"}),
            [(cmd, input_value, {"BW_SESSION": env.get("BW_SESSION")}) for cmd, input_value, env in calls],
        )

    def test_secrets_manager_prompts_for_vaultwarden_on_write(self):
        manager = secrets_mod.SecretsManager()
        backend = types.SimpleNamespace(
            get=lambda key: None,
            set=lambda key, value: None,
            delete=lambda key: None,
            list_set_keys=lambda: [],
        )
        with patch.object(manager, "_get_backend", return_value=None), patch(
            "trainsh.core.secrets.prompt_backend_selection", return_value=backend
        ):
            required = manager._require_backend()
        self.assertIs(required, backend)


if __name__ == "__main__":
    unittest.main()
