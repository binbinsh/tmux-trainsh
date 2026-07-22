import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import trainsh.core.secrets as secrets_mod


@contextmanager
def patched_secret_paths():
    with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
        config_dir = Path(tmpdir) / ".config" / "tmux-trainsh"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.yaml"
        stack.enter_context(patch.object(secrets_mod, "CONFIG_DIR", config_dir))
        stack.enter_context(patch.object(secrets_mod, "CONFIG_FILE", config_file))
        yield config_dir, config_file


class VaultwardenOnlyBackendTests(unittest.TestCase):
    def test_removed_backend_config_is_not_loaded(self):
        with patched_secret_paths() as (_config_dir, config_file):
            config_file.write_text("secrets:\n  backend: keyring\n", encoding="utf-8")
            self.assertIsNone(secrets_mod._load_backend())

    def test_legacy_alias_config_loads_vaultwarden(self):
        with patched_secret_paths() as (_config_dir, config_file):
            config_file.write_text("secrets:\n  backend: bitwarden\n", encoding="utf-8")
            backend = secrets_mod._load_backend()
            self.assertIsInstance(backend, secrets_mod.BitwardenCLIBackend)
            self.assertEqual(backend._server_url, secrets_mod.DEFAULT_VAULTWARDEN_SERVER_URL)


class SecretsManagerConvenienceTests(unittest.TestCase):
    def test_require_backend_set_delete_and_convenience_methods(self):
        backend = MagicMock()
        backend.get.side_effect = lambda key: {"VAST_API_KEY": "vast", "HF_TOKEN": "hf", "GITHUB_TOKEN": "gh"}.get(key)
        manager = secrets_mod.SecretsManager()

        with patch.object(secrets_mod, "_load_backend", return_value=None), patch.object(
            secrets_mod, "prompt_backend_selection", return_value=backend
        ):
            manager.set_vast_api_key("new-vast")
        backend.set.assert_called_once_with("VAST_API_KEY", "new-vast")
        self.assertEqual(manager.get_vast_api_key(), "new-vast")

        manager.clear_cache()
        with patch.object(secrets_mod, "_load_backend", return_value=backend):
            self.assertEqual(manager.get_hf_token(), "hf")
            self.assertEqual(manager.get_github_token(), "gh")
            self.assertTrue(manager.exists("HF_TOKEN"))
            self.assertIn("HF_TOKEN", manager.list_keys())
            self.assertTrue(manager.is_available)

        manager.delete("HF_TOKEN")
        backend.delete.assert_called_with("HF_TOKEN")


if __name__ == "__main__":
    unittest.main()
