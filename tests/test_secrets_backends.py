import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import trainsh.core.secrets as secrets_mod


class SecretsBackendMoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self.tmp.name) / ".config" / "tmux-trainsh"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.yaml"
        self.enc_file = self.config_dir / "secrets.enc"
        self.patches = [
            patch.object(secrets_mod, "CONFIG_DIR", self.config_dir),
            patch.object(secrets_mod, "CONFIG_FILE", self.config_file),
            patch.object(secrets_mod, "_ENC_FILE", self.enc_file),
        ]
        for p in self.patches:
            p.start()
        secrets_mod._secrets_manager = None

    def tearDown(self):
        secrets_mod._secrets_manager = None
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_encrypted_file_backend_roundtrip_and_error_paths(self):
        with patch("getpass.getpass", return_value="password"):
            backend = secrets_mod.EncryptedFileBackend()
            self.assertEqual(backend.list_set_keys(), [])
            backend.set("A", "1")
            backend.set("B", "2")
            self.assertEqual(backend.get("A"), "1")
            self.assertCountEqual(backend.list_set_keys(), ["A", "B"])
            fernet = backend._get_fernet()
            self.assertIs(backend._get_fernet(), fernet)
            backend.delete("A")
            self.assertIsNone(backend.get("A"))
            backend.delete("B")
            self.assertFalse(self.enc_file.exists())

        with patch("getpass.getpass", return_value="password"):
            backend = secrets_mod.EncryptedFileBackend()
            backend.set("A", "1")
        with patch("getpass.getpass", return_value="wrong"):
            backend = secrets_mod.EncryptedFileBackend()
            with self.assertRaises(RuntimeError):
                backend.get("A")

    def test_keyring_backend_and_availability_helpers(self):
        class PasswordDeleteError(Exception):
            pass

        store = {}

        class GoodKeyring:
            pass

        fake_keyring = types.SimpleNamespace(
            get_password=lambda service, key: store.get(key),
            set_password=lambda service, key, value: store.__setitem__(key, value),
            delete_password=lambda service, key: store.pop(key) if key in store else (_ for _ in ()).throw(PasswordDeleteError()),
            errors=types.SimpleNamespace(PasswordDeleteError=PasswordDeleteError),
            get_keyring=lambda: GoodKeyring(),
        )

        with patch.dict(sys.modules, {"keyring": fake_keyring}):
            backend = secrets_mod.KeyringBackend()
            backend.set("A", "1")
            self.assertEqual(backend.get("A"), "1")
            backend.delete("A")
            self.assertIsNone(backend.get("A"))
            backend.delete("A")
            self.assertIsInstance(backend.list_set_keys(), list)
            self.assertTrue(secrets_mod._keyring_available())

        class FailKeyring:
            pass

        bad_keyring = types.SimpleNamespace(get_keyring=lambda: FailKeyring())
        with patch.dict(sys.modules, {"keyring": bad_keyring}):
            self.assertFalse(secrets_mod._keyring_available())
        with patch.dict(sys.modules, {}, clear=True):
            self.assertFalse(secrets_mod._keyring_available())

        with patch("shutil.which", return_value="/usr/bin/op"):
            self.assertTrue(secrets_mod._op_available())
        with patch("shutil.which", return_value=None):
            self.assertFalse(secrets_mod._op_available())

    def test_secrets_manager_convenience_and_backend_prompt(self):
        mgr = secrets_mod.SecretsManager()
        backend = types.SimpleNamespace(
            get=lambda key: {"VAST_API_KEY": "vast", "HF_TOKEN": "hf", "GITHUB_TOKEN": "gh"}.get(key),
            set=lambda key, value: None,
            delete=lambda key: None,
        )
        with patch.object(mgr, "_get_backend", return_value=backend):
            self.assertTrue(mgr.exists("VAST_API_KEY"))
            self.assertEqual(mgr.get_vast_api_key(), "vast")
            self.assertEqual(mgr.get_hf_token(), "hf")
            self.assertEqual(mgr.get_github_token(), "gh")
            self.assertTrue(mgr.is_available)
            keys = mgr.list_keys()
            self.assertIn("VAST_API_KEY", keys)

        with patch.object(mgr, "_require_backend", return_value=backend):
            mgr.set_vast_api_key("x")
            mgr.set_hf_token("y")
            mgr.set_github_token("z")
        mgr._cache["A"] = "1"
        mgr.clear_cache()
        self.assertEqual(mgr._cache, {})

        mgr = secrets_mod.SecretsManager()
        with patch.object(mgr, "_get_backend", return_value=None), patch(
            "trainsh.core.secrets.prompt_backend_selection", return_value=backend
        ):
            required = mgr._require_backend()
        self.assertIs(required, backend)

        secrets_mod._secrets_manager = None
        first = secrets_mod.get_secrets_manager()
        second = secrets_mod.get_secrets_manager()
        self.assertIs(first, second)


if __name__ == "__main__":
    unittest.main()
