"""Tests for trainsh.core.secrets — backend selection, config persistence,
OnePasswordBackend service-account wiring, and SecretsManager resolution."""

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# We need to redirect CONFIG_DIR / CONFIG_FILE to a temp dir before
# importing the module, so patch at the constants level.
_tmp = tempfile.TemporaryDirectory()
_TMP_DIR = Path(_tmp.name) / ".config" / "tmux-trainsh"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_TMP_CONFIG = _TMP_DIR / "config.toml"


def _clean_config():
    """Reset the temp config file between tests."""
    if _TMP_CONFIG.exists():
        _TMP_CONFIG.unlink()


# Patch constants before importing secrets module
with (
    patch("trainsh.constants.CONFIG_DIR", _TMP_DIR),
    patch("trainsh.constants.CONFIG_FILE", _TMP_CONFIG),
):
    import trainsh.core.secrets as secrets_mod
    from trainsh.core.secrets import (
        OnePasswordBackend,
        SecretsManager,
        _instantiate_backend,
        _load_config,
        _save_config,
        _select_and_save,
    )

# Keep constants patched for all tests
_patches = [
    patch.object(secrets_mod, "CONFIG_DIR", _TMP_DIR),
    patch.object(secrets_mod, "CONFIG_FILE", _TMP_CONFIG),
]
for p in _patches:
    p.start()


class TestConfigRoundTrip(unittest.TestCase):
    """_save_config / _load_config preserve secrets section."""

    def setUp(self):
        _clean_config()

    def test_save_and_load_backend_only(self):
        cfg = {"secrets": {"backend": "encrypted_file"}}
        _save_config(cfg)
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "encrypted_file")

    def test_save_and_load_with_sa_token(self):
        cfg = {
            "secrets": {
                "backend": "1password",
                "vault": "myVault",
                "sa_token": "ops_TESTTOKEN123",
            }
        }
        _save_config(cfg)
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "1password")
        self.assertEqual(loaded["secrets"]["vault"], "myVault")
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_TESTTOKEN123")


class TestSelectAndSave(unittest.TestCase):
    """_select_and_save persists backend, vault, and sa_token."""

    def setUp(self):
        _clean_config()

    def test_saves_1password_with_sa_token(self):
        _select_and_save("1password", vault="trainsh", sa_token="ops_ABC")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "1password")
        self.assertEqual(loaded["secrets"]["vault"], "trainsh")
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_ABC")

    def test_saves_1password_without_sa_token_clears_old(self):
        # First save with token
        _select_and_save("1password", vault="v", sa_token="ops_OLD")
        # Then save without — sa_token must be removed
        _select_and_save("1password", vault="v", sa_token=None)
        loaded = _load_config()
        self.assertNotIn("sa_token", loaded["secrets"])

    def test_saves_encrypted_file(self):
        _select_and_save("encrypted_file")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "encrypted_file")
        self.assertNotIn("sa_token", loaded["secrets"])


class TestInstantiateBackend(unittest.TestCase):
    """_instantiate_backend passes sa_token from config to OnePasswordBackend."""

    def test_1password_with_sa_token(self):
        cfg = {"secrets": {"vault": "myV", "sa_token": "ops_XYZ"}}
        backend = _instantiate_backend("1password", cfg)
        self.assertIsInstance(backend, OnePasswordBackend)
        self.assertEqual(backend._sa_token, "ops_XYZ")
        self.assertEqual(backend._vault, "myV")

    def test_1password_without_sa_token(self):
        cfg = {"secrets": {"vault": "Private"}}
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            backend = _instantiate_backend("1password", cfg)
        self.assertIsNone(backend._sa_token)

    def test_1password_sa_token_from_env(self):
        cfg = {"secrets": {"vault": "Private"}}
        with patch.dict(os.environ, {"OP_SERVICE_ACCOUNT_TOKEN": "ops_ENV"}):
            backend = _instantiate_backend("1password", cfg)
        self.assertEqual(backend._sa_token, "ops_ENV")

    def test_config_sa_token_takes_precedence_when_set(self):
        """Explicit config sa_token is used when both config and env exist."""
        cfg = {"secrets": {"vault": "v", "sa_token": "ops_CFG"}}
        with patch.dict(os.environ, {"OP_SERVICE_ACCOUNT_TOKEN": "ops_ENV"}):
            backend = _instantiate_backend("1password", cfg)
        # "ops_CFG" or "ops_ENV" — the `or` in __init__ picks first truthy
        self.assertEqual(backend._sa_token, "ops_CFG")

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError):
            _instantiate_backend("unknown", {})


class TestOnePasswordBackendOpCall(unittest.TestCase):
    """_op() passes OP_SERVICE_ACCOUNT_TOKEN in env when sa_token is set."""

    @patch("trainsh.core.secrets.subprocess.run")
    def test_op_with_sa_token_passes_env(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        backend = OnePasswordBackend(vault="v", sa_token="ops_TOK")
        backend._op("item", "list")
        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        self.assertIsNotNone(env)
        self.assertEqual(env["OP_SERVICE_ACCOUNT_TOKEN"], "ops_TOK")

    @patch("trainsh.core.secrets.subprocess.run")
    def test_op_without_sa_token_no_env(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            backend = OnePasswordBackend(vault="v", sa_token=None)
        backend._op("item", "list")
        call_kwargs = mock_run.call_args
        env_arg = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")
        self.assertIsNone(env_arg)

    @patch("trainsh.core.secrets.subprocess.run")
    def test_op_includes_vault(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        backend = OnePasswordBackend(vault="myVault", sa_token=None)
        backend._op("item", "get", "test")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--vault", cmd)
        idx = cmd.index("--vault")
        self.assertEqual(cmd[idx + 1], "myVault")


class TestResolveOpAuth(unittest.TestCase):
    """_resolve_op_auth returns token / None / False correctly."""

    def test_returns_env_token(self):
        with patch.dict(os.environ, {"OP_SERVICE_ACCOUNT_TOKEN": "ops_E"}):
            result = secrets_mod._resolve_op_auth("v")
        self.assertEqual(result, "ops_E")

    @patch.object(secrets_mod, "_op_desktop_connectable", return_value=True)
    def test_returns_none_when_desktop_works(self, _mock):
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._resolve_op_auth("v")
        self.assertIsNone(result)

    @patch.object(secrets_mod, "_op_desktop_connectable", return_value=False)
    @patch("trainsh.cli_utils.prompt_input", return_value="3")
    def test_returns_false_when_user_declines(self, _inp, _desk):
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._resolve_op_auth("v")
        self.assertIs(result, False)

    @patch("trainsh.core.secrets.subprocess.run")
    @patch.object(secrets_mod, "_op_desktop_connectable", return_value=False)
    @patch("trainsh.cli_utils.prompt_input", side_effect=["2", "ops_MANUAL"])
    def test_returns_token_when_user_provides_valid(self, _inp, _desk, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._resolve_op_auth("v")
        self.assertEqual(result, "ops_MANUAL")

    @patch("trainsh.core.secrets.subprocess.run")
    @patch.object(secrets_mod, "_op_desktop_connectable", return_value=False)
    @patch("trainsh.cli_utils.prompt_input", side_effect=["2", "ops_BAD"])
    def test_returns_false_when_token_invalid(self, _inp, _desk, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="invalid token"
        )
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._resolve_op_auth("v")
        self.assertIs(result, False)

    @patch.object(secrets_mod, "_op_signin_and_create_sa", return_value="ops_CREATED")
    @patch.object(secrets_mod, "_op_desktop_connectable", return_value=False)
    @patch("trainsh.cli_utils.prompt_input", return_value="1")
    def test_option1_delegates_to_signin_and_create_sa(self, _inp, _desk, mock_sa):
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._resolve_op_auth("v")
        self.assertEqual(result, "ops_CREATED")
        mock_sa.assert_called_once_with("v")

    @patch.object(secrets_mod, "_op_signin_and_create_sa", return_value=None)
    @patch.object(secrets_mod, "_op_desktop_connectable", return_value=False)
    @patch("trainsh.cli_utils.prompt_input", return_value="1")
    def test_option1_fallback_when_signin_fails(self, _inp, _desk, mock_sa):
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._resolve_op_auth("v")
        self.assertIs(result, False)


class TestPromptBackendSelection(unittest.TestCase):
    """prompt_backend_selection wires _resolve_op_auth result into config."""

    def setUp(self):
        _clean_config()

    @patch.object(secrets_mod, "_op_available", return_value=True)
    @patch.object(secrets_mod, "_resolve_op_auth", return_value="ops_SA")
    @patch("trainsh.cli_utils.prompt_input", side_effect=["1", "trainsh"])
    def test_1password_sa_token_saved_to_config(self, _inp, _resolve, _avail):
        backend = secrets_mod.prompt_backend_selection()
        self.assertIsInstance(backend, OnePasswordBackend)
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "1password")
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_SA")
        self.assertEqual(loaded["secrets"]["vault"], "trainsh")

    @patch.object(secrets_mod, "_op_available", return_value=True)
    @patch.object(secrets_mod, "_resolve_op_auth", return_value=None)
    @patch("trainsh.cli_utils.prompt_input", side_effect=["1", "Private"])
    def test_1password_desktop_mode_no_sa_token(self, _inp, _resolve, _avail):
        backend = secrets_mod.prompt_backend_selection()
        self.assertIsInstance(backend, OnePasswordBackend)
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "1password")
        self.assertNotIn("sa_token", loaded["secrets"])

    @patch.object(secrets_mod, "_op_available", return_value=True)
    @patch.object(secrets_mod, "_resolve_op_auth", return_value=False)
    @patch("trainsh.cli_utils.prompt_input", side_effect=["1", "Private"])
    def test_1password_fallback_to_encrypted(self, _inp, _resolve, _avail):
        backend = secrets_mod.prompt_backend_selection()
        # Should have fallen back to encrypted_file
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "encrypted_file")

    @patch("trainsh.cli_utils.prompt_input", return_value="2")
    def test_encrypted_file_selection(self, _inp):
        backend = secrets_mod.prompt_backend_selection()
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "encrypted_file")


class TestSecretsManagerResolution(unittest.TestCase):
    """SecretsManager.get() resolution: cache > env > backend."""

    def test_cache_takes_priority(self):
        mgr = SecretsManager()
        mgr._cache["KEY"] = "cached"
        with patch.dict(os.environ, {"KEY": "env_val"}):
            self.assertEqual(mgr.get("KEY"), "cached")

    def test_env_var_fallback(self):
        mgr = SecretsManager()
        mgr._backend_loaded = True  # skip loading backend
        with patch.dict(os.environ, {"MY_KEY": "from_env"}):
            self.assertEqual(mgr.get("MY_KEY"), "from_env")

    def test_returns_none_when_nothing_found(self):
        mgr = SecretsManager()
        mgr._backend_loaded = True
        env = {k: v for k, v in os.environ.items() if k != "NONEXISTENT_KEY"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(mgr.get("NONEXISTENT_KEY"))


class TestLoadBackendFromConfig(unittest.TestCase):
    """_load_backend reads sa_token from config and passes to backend."""

    def setUp(self):
        _clean_config()

    def test_loads_1password_with_sa_token(self):
        cfg = {
            "secrets": {
                "backend": "1password",
                "vault": "trainsh",
                "sa_token": "ops_PERSISTED",
            }
        }
        _save_config(cfg)
        backend = secrets_mod._load_backend()
        self.assertIsInstance(backend, OnePasswordBackend)
        self.assertEqual(backend._sa_token, "ops_PERSISTED")
        self.assertEqual(backend._vault, "trainsh")

    def test_returns_none_when_no_backend(self):
        self.assertIsNone(secrets_mod._load_backend())


class TestSetBackend(unittest.TestCase):
    """set_backend() validates name and delegates to _select_and_save."""

    def setUp(self):
        _clean_config()

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError):
            secrets_mod.set_backend("nosuch")

    def test_set_backend_with_sa_token(self):
        secrets_mod.set_backend("1password", vault="v", sa_token="ops_SET")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["backend"], "1password")
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_SET")


class TestSaveSaToken(unittest.TestCase):
    """_save_sa_token persists token to config.toml."""

    def setUp(self):
        _clean_config()

    def test_saves_token_to_existing_config(self):
        _save_config({"secrets": {"backend": "1password", "vault": "v"}})
        secrets_mod._save_sa_token("ops_SAVED")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_SAVED")
        # Existing keys preserved
        self.assertEqual(loaded["secrets"]["backend"], "1password")

    def test_saves_token_to_empty_config(self):
        secrets_mod._save_sa_token("ops_NEW")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_NEW")


class TestAutoResolveOpAuth(unittest.TestCase):
    """_auto_resolve_op_auth recovers SA token at op-call time."""

    def setUp(self):
        _clean_config()

    def test_returns_env_token(self):
        with patch.dict(os.environ, {"OP_SERVICE_ACCOUNT_TOKEN": "ops_ENV"}):
            result = secrets_mod._auto_resolve_op_auth("v")
        self.assertEqual(result, "ops_ENV")

    def test_returns_saved_config_token(self):
        _save_config({"secrets": {"backend": "1password", "sa_token": "ops_CFG"}})
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._auto_resolve_op_auth("v")
        self.assertEqual(result, "ops_CFG")

    @patch.object(secrets_mod, "_resolve_op_auth", return_value="ops_INTERACTIVE")
    def test_interactive_fallback_saves_token(self, _resolve):
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._auto_resolve_op_auth("v")
        self.assertEqual(result, "ops_INTERACTIVE")
        loaded = _load_config()
        self.assertEqual(loaded["secrets"]["sa_token"], "ops_INTERACTIVE")

    @patch.object(secrets_mod, "_resolve_op_auth", return_value=False)
    def test_returns_none_when_interactive_declines(self, _resolve):
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            result = secrets_mod._auto_resolve_op_auth("v")
        self.assertIsNone(result)


class TestOpWithRecovery(unittest.TestCase):
    """_op_with_recovery retries with SA token on desktop-app failure."""

    @patch("trainsh.core.secrets.subprocess.run")
    def test_success_no_recovery(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            backend = OnePasswordBackend(vault="v", sa_token=None)
        r = backend._op_with_recovery("item", "list")
        self.assertEqual(r.returncode, 0)
        # Only one call — no recovery needed
        self.assertEqual(mock_run.call_count, 1)

    @patch.object(secrets_mod, "_auto_resolve_op_auth", return_value="ops_REC")
    @patch("trainsh.core.secrets.subprocess.run")
    def test_recovery_on_desktop_failure(self, mock_run, _auto):
        fail = MagicMock(returncode=1, stdout="",
                         stderr="cannot connect to 1Password app")
        success = MagicMock(returncode=0, stdout="ok", stderr="")
        mock_run.side_effect = [fail, success]
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            backend = OnePasswordBackend(vault="v", sa_token=None)
        r = backend._op_with_recovery("item", "list")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(backend._sa_token, "ops_REC")

    @patch("trainsh.core.secrets.subprocess.run")
    def test_non_desktop_error_not_recovered(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="item not found"
        )
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            backend = OnePasswordBackend(vault="v", sa_token=None)
        r = backend._op_with_recovery("item", "get", "missing")
        self.assertEqual(r.returncode, 1)
        # Only one call — not a desktop-app error, no recovery attempted
        self.assertEqual(mock_run.call_count, 1)

    @patch.object(secrets_mod, "_auto_resolve_op_auth", return_value=None)
    @patch("trainsh.core.secrets.subprocess.run")
    def test_recovery_fails_returns_original(self, mock_run, _auto):
        fail = MagicMock(returncode=1, stdout="",
                         stderr="cannot connect to 1Password app")
        mock_run.return_value = fail
        env = {k: v for k, v in os.environ.items()
               if k != "OP_SERVICE_ACCOUNT_TOKEN"}
        with patch.dict(os.environ, env, clear=True):
            backend = OnePasswordBackend(vault="v", sa_token=None)
        r = backend._op_with_recovery("item", "list")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot connect", r.stderr)


if __name__ == "__main__":
    unittest.main()
