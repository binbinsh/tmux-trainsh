"""Vaultwarden-only secrets backend tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trainsh.constants import SecretKeys

TMUX_TRAINSH_SOURCE_DIR = Path(__file__).resolve().parents[1] / "trainsh"

_tmp = tempfile.TemporaryDirectory()
_TMP_DIR = Path(_tmp.name) / ".config" / "tmux-trainsh"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_TMP_CONFIG = _TMP_DIR / "config.yaml"

with (
    patch("trainsh.constants.CONFIG_DIR", _TMP_DIR),
    patch("trainsh.constants.CONFIG_FILE", _TMP_CONFIG),
):
    import trainsh.core.secrets as secrets_mod
    from trainsh.core.secrets import (
        BitwardenCLIBackend,
        DEFAULT_VAULTWARDEN_SERVER_URL,
        SecretsManager,
        _instantiate_backend,
        _load_config,
        _save_config,
        _select_and_save,
    )

_patches = [
    patch.object(secrets_mod, "CONFIG_DIR", _TMP_DIR),
    patch.object(secrets_mod, "CONFIG_FILE", _TMP_CONFIG),
]
for _patch in _patches:
    _patch.start()


def _clean_config():
    if _TMP_CONFIG.exists():
        _TMP_CONFIG.unlink()


class VaultwardenConfigTests(unittest.TestCase):
    def setUp(self):
        _clean_config()

    def test_save_and_load_backend_only(self):
        _save_config({"secrets": {"backend": "vaultwarden"}})
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "vaultwarden")

    def test_select_and_save_vaultwarden(self):
        _select_and_save(
            "vaultwarden",
            server_url="https://vault.train.sh",
            folder_id="folder-123",
        )
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "vaultwarden")
        self.assertEqual(loaded["secrets"]["server_url"], "https://vault.train.sh")
        self.assertEqual(loaded["secrets"]["folder_id"], "folder-123")
        self.assertNotIn("vault", loaded["secrets"])
        self.assertNotIn("sa_token", loaded["secrets"])

    def test_bitwarden_alias_is_migrated_to_vaultwarden(self):
        _select_and_save("bitwarden")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "vaultwarden")
        self.assertEqual(loaded["secrets"]["server_url"], DEFAULT_VAULTWARDEN_SERVER_URL)

    def test_removed_backends_are_rejected(self):
        for backend_name in ("1password", "keyring", "encrypted_file"):
            with self.subTest(backend_name=backend_name):
                with self.assertRaises(ValueError):
                    _select_and_save(backend_name)

    def test_instantiate_vaultwarden(self):
        backend = _instantiate_backend(
            "vaultwarden",
            {"secrets": {"server_url": "https://vault.train.sh", "folder_id": "folder-123"}},
        )
        self.assertIsInstance(backend, BitwardenCLIBackend)
        self.assertEqual(backend._server_url, "https://vault.train.sh")
        self.assertEqual(backend._folder_id, "folder-123")

    def test_instantiate_accepts_bitwarden_alias(self):
        backend = _instantiate_backend("bitwarden", {"secrets": {}})
        self.assertIsInstance(backend, BitwardenCLIBackend)
        self.assertEqual(backend._server_url, DEFAULT_VAULTWARDEN_SERVER_URL)

    def test_load_backend_rejects_removed_backend(self):
        _save_config({"secrets": {"backend": "encrypted_file"}})
        self.assertIsNone(secrets_mod._load_backend())

    def test_get_configured_backend_name_normalizes_aliases(self):
        self.assertIsNone(secrets_mod.get_configured_backend_name())
        _save_config({"secrets": {"backend": "bitwarden"}})
        self.assertEqual(secrets_mod.get_configured_backend_name(), "vaultwarden")
        _save_config({"secrets": {"backend": "1password"}})
        self.assertIsNone(secrets_mod.get_configured_backend_name())

    def test_set_backend_accepts_only_vaultwarden(self):
        secrets_mod.set_backend("vaultwarden", server_url="https://vault.train.sh")
        self.assertEqual(_load_config()["secrets"]["backend"], "vaultwarden")
        secrets_mod.set_backend("bw")
        self.assertEqual(_load_config()["secrets"]["backend"], "vaultwarden")
        with self.assertRaises(ValueError):
            secrets_mod.set_backend("keyring")

    def test_production_sources_keep_vaultwarden_as_only_secret_backend(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in TMUX_TRAINSH_SOURCE_DIR.rglob("*.py")
            if "__pycache__" not in path.parts
        )

        self.assertNotIn("KEYRING_SERVICE", combined)
        self.assertNotIn("import keyring", combined)
        self.assertNotIn("encrypted_file", combined)
        self.assertNotIn("1password", combined.lower())
        self.assertIn('CANONICAL_BACKEND_NAME = "vaultwarden"', combined)
        self.assertIn('DEFAULT_VAULTWARDEN_SERVER_URL = "https://vault.train.sh"', combined)


class PromptBackendSelectionTests(unittest.TestCase):
    def setUp(self):
        _clean_config()

    @patch.object(secrets_mod, "_bw_available", return_value=True)
    @patch("trainsh.cli_utils.prompt_input", side_effect=["", "folder-123"])
    def test_prompt_configures_vaultwarden(self, _prompt, _available):
        backend = secrets_mod.prompt_backend_selection()
        self.assertIsInstance(backend, BitwardenCLIBackend)
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "vaultwarden")
        self.assertEqual(loaded["secrets"]["server_url"], DEFAULT_VAULTWARDEN_SERVER_URL)
        self.assertEqual(loaded["secrets"]["folder_id"], "folder-123")

    @patch.object(secrets_mod, "_bw_available", return_value=False)
    def test_missing_bw_does_not_fallback(self, _available):
        with self.assertRaises(RuntimeError):
            secrets_mod.prompt_backend_selection()


class BitwardenCLIBackendTests(unittest.TestCase):
    def test_uses_official_bw_cli(self):
        calls = []

        def completed(returncode=0, stdout="", stderr=""):
            return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

        def run_side_effect(cmd, input=None, capture_output=None, text=None, timeout=None, env=None):
            calls.append((cmd, input, env))
            if cmd[:3] == ["bw", "config", "server"]:
                return completed()
            if cmd[:4] == ["bw", "get", "item", "API_KEY"]:
                return completed(stdout=json.dumps({
                    "id": "item-1",
                    "name": "API_KEY",
                    "login": {"username": "API_KEY", "password": "secret"},
                }))
            if cmd[:2] == ["bw", "encode"]:
                return completed(stdout="encoded-payload\n")
            if cmd[:4] == ["bw", "edit", "item", "item-1"]:
                return completed()
            if cmd[:3] == ["bw", "list", "items"]:
                return completed(stdout=json.dumps([
                    {"name": "API_KEY"},
                    {"name": "OTHER_KEY"},
                ]))
            return completed(returncode=1, stderr="not found")

        with patch("shutil.which", return_value="/usr/bin/bw"), patch(
            "trainsh.core.secrets.subprocess.run", side_effect=run_side_effect
        ), patch.dict("os.environ", {"BW_SESSION": "session-123"}):
            backend = BitwardenCLIBackend(
                server_url="https://vault.train.sh",
                folder_id="folder-123",
            )
            self.assertEqual(backend.get("API_KEY"), "secret")
            backend.set("API_KEY", "rotated")
            self.assertEqual(backend.list_set_keys(), ["API_KEY", "OTHER_KEY"])

        self.assertTrue(any(cmd == ["bw", "config", "server", "https://vault.train.sh"] for cmd, _input, _env in calls))
        edit_calls = [cmd for cmd, _input, _env in calls if cmd[:4] == ["bw", "edit", "item", "item-1"]]
        self.assertEqual(edit_calls, [["bw", "edit", "item", "item-1", "encoded-payload", "--session", "session-123"]])


class SecretsManagerResolutionTests(unittest.TestCase):
    def test_cache_ignores_env_uses_backend_and_singleton_paths(self):
        manager = SecretsManager()
        manager._cache["KEY"] = "cached"
        with patch.dict(os.environ, {"KEY": "env"}):
            self.assertEqual(manager.get("KEY"), "cached")

        manager = SecretsManager()
        manager._backend_loaded = True
        with patch.dict(os.environ, {"MY_KEY": "from-env"}):
            self.assertIsNone(manager.get("MY_KEY"))

        backend = MagicMock()
        backend.get.return_value = "from-backend"
        manager = SecretsManager()
        manager._backend = backend
        manager._backend_loaded = True
        self.assertEqual(manager.get("BACKEND_KEY"), "from-backend")

        secrets_mod._secrets_manager = None
        first = secrets_mod.get_secrets_manager()
        second = secrets_mod.get_secrets_manager()
        self.assertIs(first, second)

    def test_bundle_aliases_resolve_and_clear_components(self):
        manager = SecretsManager()
        backend = MagicMock()
        backend.get.side_effect = lambda key: (
            '"{""account_id"": ""abc123"", ""access_key_id"": ""r2-ak"", ""secret_access_key"": ""r2-sk""}"'
            if key == "R2_CREDENTIALS"
            else None
        )
        manager._backend = backend
        manager._backend_loaded = True

        self.assertEqual(manager.get("R2_ACCOUNT_ID"), "abc123")
        self.assertEqual(manager.get("R2_ACCESS_KEY_ID"), "r2-ak")
        self.assertEqual(manager.get("R2_SECRET_ACCESS_KEY"), "r2-sk")

        manager.set_bundle("R2_CREDENTIALS", {
            "account_id": "abc123",
            "access_key_id": "new-ak",
            "secret_access_key": "new-sk",
        })
        backend.set.assert_called_once()
        backend.delete.assert_any_call("R2_ACCOUNT_ID")
        backend.delete.assert_any_call("R2_ACCESS_KEY_ID")
        backend.delete.assert_any_call("R2_SECRET_ACCESS_KEY")

    def test_list_keys_uses_backend_enumeration(self):
        manager = SecretsManager()
        backend = MagicMock()
        backend.list_set_keys.return_value = [SecretKeys.R2_CREDENTIALS, SecretKeys.HF_TOKEN]
        manager._backend = backend
        manager._backend_loaded = True

        keys = set(manager.list_keys())
        self.assertIn(SecretKeys.R2_CREDENTIALS, keys)
        self.assertIn(SecretKeys.HF_TOKEN, keys)


if __name__ == "__main__":
    unittest.main()
