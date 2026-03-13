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
        enc_file = config_dir / "secrets.enc"
        stack.enter_context(patch.object(secrets_mod, "CONFIG_DIR", config_dir))
        stack.enter_context(patch.object(secrets_mod, "CONFIG_FILE", config_file))
        stack.enter_context(patch.object(secrets_mod, "_ENC_FILE", enc_file))
        yield config_dir, config_file, enc_file


class EncryptedFileBackendTests(unittest.TestCase):
    def test_roundtrip_and_wrong_password(self):
        with patched_secret_paths() as (_config_dir, _config_file, enc_file):
            with patch("getpass.getpass", return_value="pw"):
                backend = secrets_mod.EncryptedFileBackend()
                backend.set("API", "secret")
                self.assertEqual(backend.get("API"), "secret")
                self.assertEqual(backend.list_set_keys(), ["API"])
                backend.delete("API")
                self.assertFalse(enc_file.exists())

            with patch("getpass.getpass", return_value="pw"):
                backend = secrets_mod.EncryptedFileBackend()
                backend.set("API", "secret")

            with patch("getpass.getpass", return_value="wrong"):
                backend = secrets_mod.EncryptedFileBackend()
                with self.assertRaises(RuntimeError):
                    backend.get("API")


class KeyringBackendTests(unittest.TestCase):
    def test_keyring_backend_and_enumeration(self):
        fake_store = {}

        class DeleteError(Exception):
            pass

        fake_keyring = MagicMock()
        fake_keyring.errors.PasswordDeleteError = DeleteError
        fake_keyring.get_password.side_effect = lambda service, key: fake_store.get(key)
        fake_keyring.set_password.side_effect = lambda service, key, value: fake_store.__setitem__(key, value)

        def delete_password(service, key):
            if key not in fake_store:
                raise DeleteError()
            fake_store.pop(key)

        fake_keyring.delete_password.side_effect = delete_password

        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            backend = secrets_mod.KeyringBackend()
            backend.set("VAST_API_KEY", "token")
            self.assertEqual(backend.get("VAST_API_KEY"), "token")
            self.assertEqual(backend.list_set_keys(), ["VAST_API_KEY"])
            backend.delete("VAST_API_KEY")
            self.assertIsNone(backend.get("VAST_API_KEY"))
            backend.delete("MISSING")


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
