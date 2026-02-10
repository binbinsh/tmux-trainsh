# tmux-trainsh secrets management
# Multi-backend: 1Password (op CLI) or encrypted file (Fernet)

import base64
import getpass
import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from ..constants import CONFIG_DIR, CONFIG_FILE, SecretKeys


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load config.toml, returning an empty dict if missing."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:          # Python < 3.11
        try:
            import tomli as tomllib      # type: ignore[no-redef]
        except ImportError:
            return {}
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def _save_config(cfg: dict) -> None:
    """Write *cfg* back to config.toml (minimal TOML writer)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    # Write top-level keys first (non-dict values)
    for k, v in cfg.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    if lines:
        lines.append("")

    # Write sections (dict values)
    for section, values in cfg.items():
        if isinstance(values, dict):
            lines.append(f"[{section}]")
            for k, v in values.items():
                lines.append(f"{k} = {_toml_value(v)}")
            lines.append("")

    CONFIG_FILE.write_text("\n".join(lines))


def _toml_value(v: object) -> str:
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return f'"{v}"'


# ---------------------------------------------------------------------------
# Backend ABC
# ---------------------------------------------------------------------------

class SecretsBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> Optional[str]: ...

    @abstractmethod
    def set(self, key: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def list_set_keys(self) -> List[str]: ...


# ---------------------------------------------------------------------------
# Backend: 1Password (op CLI)
# ---------------------------------------------------------------------------

class OnePasswordBackend(SecretsBackend):
    """Store each secret as its own 1Password item (title=key, password=value)."""

    def __init__(self, vault: Optional[str] = None, sa_token: Optional[str] = None):
        self._vault = vault or os.environ.get("OP_VAULT", "trainsh")
        # Service account token: explicit arg > env var > config
        self._sa_token = sa_token or os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")

    # -- helpers -----------------------------------------------------------

    def _op(self, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess[str]:
        cmd = ["op", *args]
        if self._vault:
            cmd += ["--vault", self._vault]
        env = None
        if self._sa_token:
            env = {**os.environ, "OP_SERVICE_ACCOUNT_TOKEN": self._sa_token}
        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

    def _op_with_recovery(self, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess[str]:
        """Run an op command; on desktop-app failure, try to sign in or set up a service account."""
        r = self._op(*args, stdin=stdin)
        if r.returncode == 0:
            return r
        if "cannot connect to 1Password app" not in r.stderr:
            return r
        # Desktop app unavailable — attempt recovery
        token = _auto_resolve_op_auth(self._vault)
        if token:
            self._sa_token = token
            return self._op(*args, stdin=stdin)
        return r

    def _op_raw(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run an op command without appending --vault."""
        env = None
        if self._sa_token:
            env = {**os.environ, "OP_SERVICE_ACCOUNT_TOKEN": self._sa_token}
        return subprocess.run(
            ["op", *args],
            capture_output=True, text=True, timeout=30, env=env,
        )

    def _ensure_vault(self) -> None:
        """Create the vault if it doesn't exist yet."""
        r = self._op_raw("vault", "get", self._vault, "--format=json")
        if r.returncode == 0:
            return
        if "isn't a vault" not in r.stderr:
            return
        r2 = self._op_raw("vault", "create", self._vault)
        if r2.returncode != 0:
            raise RuntimeError(
                f"Failed to create 1Password vault '{self._vault}': {r2.stderr.strip()}"
            )
        print(f"Created 1Password vault '{self._vault}'.")

    # -- public API --------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        r = self._op_with_recovery(
            "item", "get", key,
            "--fields", "label=password",
            "--reveal",
        )
        if r.returncode != 0:
            return None
        val = r.stdout.strip()
        return val if val else None

    def set(self, key: str, value: str) -> None:
        self._ensure_vault()
        # Check if item already exists
        r = self._op("item", "get", key, "--format=json")
        if r.returncode == 0:
            # Item exists — update password field
            r2 = self._op("item", "edit", key, f"password={value}")
            if r2.returncode != 0:
                raise RuntimeError(
                    f"Failed to update secret in 1Password: {r2.stderr.strip()}"
                )
        else:
            # Create new item with key as title
            r2 = self._op(
                "item", "create",
                "--category=password",
                f"--title={key}",
                f"password={value}",
            )
            if r2.returncode != 0:
                raise RuntimeError(
                    f"Failed to store secret in 1Password: {r2.stderr.strip()}"
                )

    def delete(self, key: str) -> None:
        self._op("item", "delete", key)

    def list_set_keys(self) -> List[str]:
        r = self._op("item", "list", "--format=json")
        if r.returncode != 0:
            return []
        try:
            items = json.loads(r.stdout)
            return [item["title"] for item in items
                    if item.get("title")]
        except (json.JSONDecodeError, KeyError):
            return []


# ---------------------------------------------------------------------------
# Backend: Encrypted file (Fernet)
# ---------------------------------------------------------------------------

_ENC_FILE = CONFIG_DIR / "secrets.enc"
_SALT_LEN = 16
_KDF_ITERATIONS = 480_000


class EncryptedFileBackend(SecretsBackend):
    """Fernet-encrypted JSON file at ~/.config/tmux-trainsh/secrets.enc."""

    def __init__(self) -> None:
        self._fernet: Optional[object] = None   # lazily created
        self._password: Optional[str] = None

    # -- crypto helpers ----------------------------------------------------

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_KDF_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def _get_fernet(self) -> "Fernet":          # type: ignore[name-defined]
        from cryptography.fernet import Fernet

        if self._fernet is not None:
            return self._fernet                  # type: ignore[return-value]

        if _ENC_FILE.exists():
            raw = _ENC_FILE.read_bytes()
            salt = raw[:_SALT_LEN]
        else:
            salt = os.urandom(_SALT_LEN)

        if self._password is None:
            self._password = getpass.getpass("Secrets password: ")

        key = self._derive_key(self._password, salt)
        self._fernet = Fernet(key)

        # If file doesn't exist yet, persist the salt with an empty store
        if not _ENC_FILE.exists():
            self._write_store(salt, {})

        return self._fernet                      # type: ignore[return-value]

    def _read_store(self) -> Dict[str, str]:
        if not _ENC_FILE.exists():
            return {}
        raw = _ENC_FILE.read_bytes()
        salt = raw[:_SALT_LEN]             # noqa: F841 — kept for clarity
        token = raw[_SALT_LEN:]
        fernet = self._get_fernet()
        try:
            plaintext = fernet.decrypt(token)
        except Exception:
            raise RuntimeError(
                "Wrong password or corrupted secrets file. "
                "Delete ~/.config/tmux-trainsh/secrets.enc to reset."
            )
        return json.loads(plaintext)

    def _write_store(self, salt: bytes, store: Dict[str, str]) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        fernet = self._get_fernet()
        token = fernet.encrypt(json.dumps(store).encode())
        _ENC_FILE.write_bytes(salt + token)
        _ENC_FILE.chmod(0o600)

    def _save(self, store: Dict[str, str]) -> None:
        if _ENC_FILE.exists():
            salt = _ENC_FILE.read_bytes()[:_SALT_LEN]
        else:
            salt = os.urandom(_SALT_LEN)
        self._write_store(salt, store)

    # -- public API --------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        store = self._read_store()
        return store.get(key)

    def set(self, key: str, value: str) -> None:
        store = self._read_store()
        store[key] = value
        self._save(store)

    def delete(self, key: str) -> None:
        store = self._read_store()
        store.pop(key, None)
        self._save(store)

    def list_set_keys(self) -> List[str]:
        return list(self._read_store().keys())


# ---------------------------------------------------------------------------
# Backend: System keyring (GNOME Keyring / macOS Keychain / Windows Credential Manager)
# ---------------------------------------------------------------------------

class KeyringBackend(SecretsBackend):
    """Store each secret in the OS keyring (service='trainsh', username=key)."""

    SERVICE = "trainsh"

    def __init__(self) -> None:
        import keyring as _kr
        self._kr = _kr

    def get(self, key: str) -> Optional[str]:
        val = self._kr.get_password(self.SERVICE, key)
        return val if val else None

    def set(self, key: str, value: str) -> None:
        self._kr.set_password(self.SERVICE, key, value)

    def delete(self, key: str) -> None:
        try:
            self._kr.delete_password(self.SERVICE, key)
        except self._kr.errors.PasswordDeleteError:
            pass

    def list_set_keys(self) -> List[str]:
        # keyring API doesn't support enumeration; check predefined keys
        from ..constants import SecretKeys
        predefined = [
            SecretKeys.VAST_API_KEY,
            SecretKeys.HF_TOKEN,
            SecretKeys.OPENAI_API_KEY,
            SecretKeys.ANTHROPIC_API_KEY,
            SecretKeys.GITHUB_TOKEN,
            SecretKeys.GOOGLE_DRIVE_CREDENTIALS,
            SecretKeys.R2_ACCESS_KEY,
            SecretKeys.R2_SECRET_KEY,
            SecretKeys.B2_KEY_ID,
            SecretKeys.B2_APPLICATION_KEY,
            SecretKeys.AWS_ACCESS_KEY_ID,
            SecretKeys.AWS_SECRET_ACCESS_KEY,
        ]
        return [k for k in predefined if self.get(k) is not None]


# ---------------------------------------------------------------------------
# Backend loading / selection
# ---------------------------------------------------------------------------

_BACKEND_NAMES = {
    "1password": "1Password (op CLI)",
    "keyring": "System keyring (GNOME Keyring / macOS Keychain / Windows Credential Manager)",
    "encrypted_file": "Encrypted file (~/.config/tmux-trainsh/secrets.enc)",
}


def _op_available() -> bool:
    return shutil.which("op") is not None


def _keyring_available() -> bool:
    try:
        import keyring
        kr = keyring.get_keyring()
        # Reject the fail backend (no real keyring found)
        return "fail" not in type(kr).__name__.lower()
    except Exception:
        return False


def _op_desktop_connectable() -> bool:
    """Check if `op` can connect to the desktop app."""
    r = subprocess.run(
        ["op", "account", "list", "--format=json"],
        capture_output=True, text=True, timeout=10,
    )
    return r.returncode == 0


def _instantiate_backend(name: str, cfg: dict) -> SecretsBackend:
    if name == "1password":
        secrets_cfg = cfg.get("secrets", {})
        vault = secrets_cfg.get("vault")
        sa_token = secrets_cfg.get("sa_token")
        return OnePasswordBackend(vault=vault, sa_token=sa_token)
    if name == "keyring":
        return KeyringBackend()
    if name == "encrypted_file":
        return EncryptedFileBackend()
    raise ValueError(f"Unknown secrets backend: {name!r}")


def _load_backend() -> Optional[SecretsBackend]:
    """Load the configured backend from config.toml, or return None."""
    cfg = _load_config()
    backend_name = cfg.get("secrets", {}).get("backend")
    if not backend_name:
        return None
    return _instantiate_backend(backend_name, cfg)


def prompt_backend_selection() -> SecretsBackend:
    """Interactively ask the user to choose a secrets backend."""
    from ..cli_utils import prompt_input

    print("\nNo secrets backend configured. Choose one:")
    print("  [1] 1Password (recommended if you use 1Password)")
    print("  [2] System keyring (GNOME Keyring / macOS Keychain / Windows Credential Manager)")
    print("  [3] Encrypted file (~/.config/tmux-trainsh/secrets.enc)")

    choice = prompt_input("> ")
    if choice == "1":
        if not _op_available():
            print("Warning: 'op' CLI not found on PATH. Install it from https://1password.com/downloads/command-line/")
            print("Falling back to encrypted file backend.\n")
            return _select_and_save("encrypted_file")
        vault = prompt_input("1Password vault name [trainsh]: ", default="trainsh")
        sa_token = _resolve_op_auth(vault)
        if sa_token is False:
            return _select_and_save("encrypted_file")
        return _select_and_save("1password", vault=vault, sa_token=sa_token)
    elif choice == "2":
        if not _keyring_available():
            print("Warning: No system keyring found. Install 'keyring' package: pip install keyring")
            print("Falling back to encrypted file backend.\n")
            return _select_and_save("encrypted_file")
        return _select_and_save("keyring")
    elif choice == "3":
        return _select_and_save("encrypted_file")
    else:
        print("Invalid choice, defaulting to encrypted file.\n")
        return _select_and_save("encrypted_file")


def _resolve_op_auth(vault: Optional[str] = None):
    """Determine 1Password auth method: desktop app or service account token.

    Returns:
        str  — service account token (use SA mode)
        None — desktop app connection works (use desktop mode)
        False — user declined, caller should fall back to another backend
    """
    from ..cli_utils import prompt_input

    # Already have a service account token in env — use it directly
    env_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if env_token:
        print("Using OP_SERVICE_ACCOUNT_TOKEN from environment.")
        return env_token

    # Try connecting to the desktop app
    if _op_desktop_connectable():
        return None

    # Desktop app not available — prompt for service account token
    print("\nCannot connect to 1Password desktop app.")
    print("A Service Account token is required (no desktop app needed).")
    print("")
    print("To create one:")
    print("  1. Go to https://my.1password.com/developer-tools/infrastructure-secrets/serviceaccount")
    print(f"  2. Create a service account with read+write access to vault '{vault or 'trainsh'}'")
    print("  3. Copy the token and paste it below")
    print("")
    print("  [1] Enter a Service Account token")
    print("  [2] Fall back to encrypted file backend")
    sa_choice = prompt_input("> ")
    if sa_choice == "1":
        token = prompt_input("Service Account token: ")
        if not token:
            print("No token provided. Falling back to encrypted file backend.\n")
            return False
        # Validate token works
        r = subprocess.run(
            ["op", "vault", "list", "--format=json"],
            capture_output=True, text=True, timeout=15,
            env={**os.environ, "OP_SERVICE_ACCOUNT_TOKEN": token},
        )
        if r.returncode != 0:
            print(f"Token validation failed: {r.stderr.strip()}")
            print("Falling back to encrypted file backend.\n")
            return False
        print("Service account token validated successfully.")
        return token
    return False


def _auto_resolve_op_auth(vault: Optional[str] = None) -> Optional[str]:
    """Non-interactive SA token recovery at op-call time.

    Checks env, then saved config. If a saved token exists, returns it.
    Otherwise falls back to the interactive prompt flow, saving the
    resulting token to config for future use.

    Returns a service account token string, or None on failure.
    """
    # 1. env var
    env_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if env_token:
        return env_token

    # 2. config (may have been saved by a previous session)
    cfg = _load_config()
    saved = cfg.get("secrets", {}).get("sa_token")
    if saved:
        return saved

    # 3. interactive recovery
    print("\n1Password desktop app is not available.")
    result = _resolve_op_auth(vault)
    if result is False or result is None:
        return None
    # Persist the token so subsequent calls don't prompt again
    _save_sa_token(result)
    return result


def _save_sa_token(token: str) -> None:
    """Persist a service account token to config.toml."""
    cfg = _load_config()
    cfg.setdefault("secrets", {})
    cfg["secrets"]["sa_token"] = token
    _save_config(cfg)


def _select_and_save(name: str, vault: Optional[str] = None, sa_token: Optional[str] = None) -> SecretsBackend:
    cfg = _load_config()
    cfg.setdefault("secrets", {})
    cfg["secrets"]["backend"] = name
    if vault:
        cfg["secrets"]["vault"] = vault
    if sa_token:
        cfg["secrets"]["sa_token"] = sa_token
    else:
        cfg["secrets"].pop("sa_token", None)
    _save_config(cfg)
    return _instantiate_backend(name, cfg)


def set_backend(name: str, vault: Optional[str] = None, sa_token: Optional[str] = None) -> SecretsBackend:
    """Explicitly switch to a named backend."""
    if name not in _BACKEND_NAMES:
        raise ValueError(f"Unknown backend {name!r}. Choose from: {list(_BACKEND_NAMES)}")
    return _select_and_save(name, vault=vault, sa_token=sa_token)


def get_configured_backend_name() -> Optional[str]:
    cfg = _load_config()
    return cfg.get("secrets", {}).get("backend")


# ---------------------------------------------------------------------------
# SecretsManager (main public API)
# ---------------------------------------------------------------------------

class SecretsManager:
    """
    Multi-backend secrets manager.

    Resolution order for get():
      1. In-memory cache
      2. Environment variable (os.environ)
      3. Active backend (1Password or encrypted file)
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}
        self._backend: Optional[SecretsBackend] = None
        self._backend_loaded = False

    def _get_backend(self) -> Optional[SecretsBackend]:
        if not self._backend_loaded:
            self._backend = _load_backend()
            self._backend_loaded = True
        return self._backend

    def _require_backend(self) -> SecretsBackend:
        backend = self._get_backend()
        if backend is None:
            backend = prompt_backend_selection()
            self._backend = backend
            self._backend_loaded = True
        return backend

    def get(self, key: str) -> Optional[str]:
        if key in self._cache:
            return self._cache[key]

        env_value = os.environ.get(key)
        if env_value:
            return env_value

        backend = self._get_backend()
        if backend is not None:
            try:
                value = backend.get(key)
            except Exception:
                value = None
            if value:
                self._cache[key] = value
                return value

        return None

    def set(self, key: str, value: str) -> None:
        backend = self._require_backend()
        backend.set(key, value)
        self._cache[key] = value

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)
        backend = self._get_backend()
        if backend is not None:
            backend.delete(key)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def list_keys(self) -> List[str]:
        predefined = [
            SecretKeys.VAST_API_KEY,
            SecretKeys.HF_TOKEN,
            SecretKeys.OPENAI_API_KEY,
            SecretKeys.ANTHROPIC_API_KEY,
            SecretKeys.GITHUB_TOKEN,
            SecretKeys.GOOGLE_DRIVE_CREDENTIALS,
            SecretKeys.R2_ACCESS_KEY,
            SecretKeys.R2_SECRET_KEY,
            SecretKeys.B2_KEY_ID,
            SecretKeys.B2_APPLICATION_KEY,
            SecretKeys.AWS_ACCESS_KEY_ID,
            SecretKeys.AWS_SECRET_ACCESS_KEY,
        ]
        return [key for key in predefined if self.exists(key)]

    # Convenience accessors (kept for backward compat)
    def get_vast_api_key(self) -> Optional[str]:
        return self.get(SecretKeys.VAST_API_KEY)

    def set_vast_api_key(self, key: str) -> None:
        self.set(SecretKeys.VAST_API_KEY, key)

    def get_hf_token(self) -> Optional[str]:
        return self.get(SecretKeys.HF_TOKEN)

    def set_hf_token(self, token: str) -> None:
        self.set(SecretKeys.HF_TOKEN, token)

    def get_github_token(self) -> Optional[str]:
        return self.get(SecretKeys.GITHUB_TOKEN)

    def set_github_token(self, token: str) -> None:
        self.set(SecretKeys.GITHUB_TOKEN, token)

    def clear_cache(self) -> None:
        self._cache.clear()

    @property
    def is_available(self) -> bool:
        return self._get_backend() is not None


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager
