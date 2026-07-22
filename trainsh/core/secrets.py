# tmux-trainsh secrets management
# Vaultwarden only, through the official Bitwarden CLI (`bw`).

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from ..constants import CONFIG_DIR, CONFIG_FILE, SecretKeys

DEFAULT_VAULTWARDEN_SERVER_URL = "https://vault.train.sh"
CANONICAL_BACKEND_NAME = "vaultwarden"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load config.yaml, returning an empty dict if missing."""
    if not CONFIG_FILE.exists():
        return {}
    import yaml
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def _save_config(cfg: dict) -> None:
    """Write *cfg* back to config.yaml."""
    import yaml
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)


def normalize_secret_key(key: str) -> str:
    """Normalize secret names for matching."""
    return str(key or "").strip().upper()


def parse_secret_bundle_value(value: Optional[str]) -> Optional[Dict[str, str]]:
    """Parse a JSON-encoded secret bundle payload."""
    if not value:
        return None

    text = str(value).strip()
    candidates = [text]
    if len(text) >= 2 and text[0] == text[-1] == '"':
        candidates.append(text[1:-1].replace('""', '"'))

    data = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
        if isinstance(parsed, str):
            try:
                reparsed = json.loads(parsed)
            except Exception:
                continue
            if isinstance(reparsed, dict):
                data = reparsed
                break

    if not isinstance(data, dict):
        return None

    parsed: Dict[str, str] = {}
    for raw_key, raw_value in data.items():
        key = str(raw_key).strip()
        if not key:
            continue
        parsed[key] = "" if raw_value is None else str(raw_value)
    return parsed or None


def dump_secret_bundle_value(payload: Dict[str, str]) -> str:
    """Serialize a secret bundle payload to JSON."""
    clean = {
        str(key): str(value)
        for key, value in payload.items()
        if value is not None and str(value) != ""
    }
    return json.dumps(clean, ensure_ascii=False, sort_keys=True)


def normalize_storage_bundle_payload(
    provider: str,
    payload: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    """Normalize bundle fields to the canonical provider-specific names."""
    if not payload:
        return None

    cleaned = {
        str(key).strip(): "" if value is None else str(value).strip()
        for key, value in payload.items()
        if str(key).strip()
    }

    if provider == "r2":
        normalized: Dict[str, str] = {}
        account_id = cleaned.get("account_id", "")
        access_key_id = cleaned.get("access_key_id", "")
        secret_access_key = cleaned.get("secret_access_key", "")
        endpoint = cleaned.get("endpoint") or cleaned.get("s3_api_endpoint", "")

        if account_id:
            normalized["account_id"] = account_id
        if access_key_id:
            normalized["access_key_id"] = access_key_id
        if secret_access_key:
            normalized["secret_access_key"] = secret_access_key
        if endpoint:
            normalized["endpoint"] = endpoint
        return normalized or None

    if provider == "b2":
        normalized = {}
        application_key_id = cleaned.get("application_key_id", "")
        application_key = cleaned.get("application_key", "")
        endpoint = cleaned.get("endpoint", "")

        if application_key_id:
            normalized["application_key_id"] = application_key_id
        if application_key:
            normalized["application_key"] = application_key
        if endpoint:
            normalized["endpoint"] = endpoint
        return normalized or None

    return cleaned or None


def resolve_secret_bundle_alias(key: str) -> Optional[tuple[str, Optional[str], str]]:
    """Map supported secret aliases onto the composite bundle keys."""
    normalized = normalize_secret_key(key)

    if normalized == SecretKeys.R2_CREDENTIALS:
        return SecretKeys.R2_CREDENTIALS, None, "r2"
    if normalized == SecretKeys.R2_ACCOUNT_ID:
        return SecretKeys.R2_CREDENTIALS, "account_id", "r2"
    if normalized == SecretKeys.R2_ACCESS_KEY_ID:
        return SecretKeys.R2_CREDENTIALS, "access_key_id", "r2"
    if normalized == SecretKeys.R2_SECRET_ACCESS_KEY:
        return SecretKeys.R2_CREDENTIALS, "secret_access_key", "r2"
    if normalized == "R2_ENDPOINT":
        return SecretKeys.R2_CREDENTIALS, "endpoint", "r2"

    if normalized == SecretKeys.B2_CREDENTIALS:
        return SecretKeys.B2_CREDENTIALS, None, "b2"
    if normalized == SecretKeys.B2_APPLICATION_KEY_ID:
        return SecretKeys.B2_CREDENTIALS, "application_key_id", "b2"
    if normalized == SecretKeys.B2_APPLICATION_KEY:
        return SecretKeys.B2_CREDENTIALS, "application_key", "b2"
    if normalized == "B2_ENDPOINT":
        return SecretKeys.B2_CREDENTIALS, "endpoint", "b2"

    if normalized.endswith("_R2_CREDENTIALS"):
        return normalized, None, "r2"
    if normalized.endswith("_B2_CREDENTIALS"):
        return normalized, None, "b2"

    if normalized.endswith("_ACCOUNT_ID"):
        prefix = normalized[: -len("_ACCOUNT_ID")]
        if prefix:
            return f"{prefix}_R2_CREDENTIALS", "account_id", "r2"
    if normalized.endswith("_ACCESS_KEY_ID"):
        prefix = normalized[: -len("_ACCESS_KEY_ID")]
        if prefix:
            return f"{prefix}_R2_CREDENTIALS", "access_key_id", "r2"
    if normalized.endswith("_SECRET_ACCESS_KEY"):
        prefix = normalized[: -len("_SECRET_ACCESS_KEY")]
        if prefix:
            return f"{prefix}_R2_CREDENTIALS", "secret_access_key", "r2"
    if normalized.endswith("_APPLICATION_KEY_ID"):
        prefix = normalized[: -len("_APPLICATION_KEY_ID")]
        if prefix:
            return f"{prefix}_B2_CREDENTIALS", "application_key_id", "b2"
    if normalized.endswith("_APPLICATION_KEY"):
        prefix = normalized[: -len("_APPLICATION_KEY")]
        if prefix:
            return f"{prefix}_B2_CREDENTIALS", "application_key", "b2"

    return None


def bundle_component_alias_groups(composite_key: str, provider: str) -> Dict[str, tuple[str, ...]]:
    """Return canonical and legacy component aliases for a composite bundle key."""
    normalized = normalize_secret_key(composite_key)
    if provider == "r2":
        if normalized == SecretKeys.R2_CREDENTIALS:
            return {
                "account_id": (SecretKeys.R2_ACCOUNT_ID,),
                "access_key_id": (SecretKeys.R2_ACCESS_KEY_ID,),
                "secret_access_key": (SecretKeys.R2_SECRET_ACCESS_KEY,),
                "endpoint": ("R2_ENDPOINT",),
            }
        prefix = normalized[: -len("_R2_CREDENTIALS")]
        return {
            "account_id": (f"{prefix}_ACCOUNT_ID",),
            "access_key_id": (f"{prefix}_ACCESS_KEY_ID",),
            "secret_access_key": (f"{prefix}_SECRET_ACCESS_KEY",),
            "endpoint": (f"{prefix}_ENDPOINT",),
        }

    if normalized == SecretKeys.B2_CREDENTIALS:
        return {
            "application_key_id": (SecretKeys.B2_APPLICATION_KEY_ID,),
            "application_key": (SecretKeys.B2_APPLICATION_KEY,),
            "endpoint": ("B2_ENDPOINT",),
        }
    prefix = normalized[: -len("_B2_CREDENTIALS")]
    return {
        "application_key_id": (f"{prefix}_APPLICATION_KEY_ID",),
        "application_key": (f"{prefix}_APPLICATION_KEY",),
        "endpoint": (f"{prefix}_ENDPOINT",),
    }


def bundle_component_aliases(composite_key: str, provider: str) -> Dict[str, str]:
    """Return component aliases covered by a composite secret bundle."""
    return {
        field: aliases[0]
        for field, aliases in bundle_component_alias_groups(composite_key, provider).items()
    }


def bundle_component_cleanup_aliases(composite_key: str, provider: str) -> List[str]:
    """Return all component aliases that should be cleared for a bundle."""
    aliases: List[str] = []
    for group in bundle_component_alias_groups(composite_key, provider).values():
        for alias in group:
            normalized = normalize_secret_key(alias)
            if normalized not in aliases:
                aliases.append(normalized)
    return aliases


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
# Backend: Bitwarden / Vaultwarden (official bw CLI)
# ---------------------------------------------------------------------------

class BitwardenCLIBackend(SecretsBackend):
    """Store each secret as a Bitwarden password item using the official bw CLI."""

    def __init__(self, server_url: Optional[str] = None, folder_id: Optional[str] = None):
        self._server_url = server_url or os.environ.get("BW_SERVER") or DEFAULT_VAULTWARDEN_SERVER_URL
        self._folder_id = folder_id or os.environ.get("BW_FOLDER_ID")
        self._server_configured = False

    def _session(self) -> Optional[str]:
        return os.environ.get("BW_SESSION")

    def _run_bw(
        self,
        *args: str,
        stdin: Optional[str] = None,
        session: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if not _bw_available():
            raise RuntimeError("Bitwarden CLI 'bw' is not installed or not on PATH.")

        cmd = ["bw", *args]
        if session and self._session():
            cmd.extend(["--session", self._session() or ""])

        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy(),
        )

    def _ensure_server_configured(self) -> None:
        if self._server_configured:
            return
        if self._server_url:
            r = self._run_bw("config", "server", self._server_url, session=False)
            if r.returncode != 0:
                raise RuntimeError(f"Failed to configure Bitwarden server: {r.stderr.strip()}")
        self._server_configured = True

    def _bw(self, *args: str, stdin: Optional[str] = None, session: bool = True) -> subprocess.CompletedProcess[str]:
        self._ensure_server_configured()
        return self._run_bw(*args, stdin=stdin, session=session)

    def _encode(self, payload: dict) -> str:
        r = self._bw("encode", stdin=json.dumps(payload), session=False)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to encode Bitwarden item: {r.stderr.strip()}")
        return r.stdout.strip()

    def _get_item(self, key: str) -> Optional[dict]:
        r = self._bw("get", "item", key)
        if r.returncode != 0:
            return None
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _build_item(self, key: str, value: str) -> dict:
        item = {
            "type": 1,
            "name": key,
            "notes": "Managed by trainsh secrets backend.",
            "favorite": False,
            "login": {
                "uris": [],
                "username": key,
                "password": value,
            },
            "fields": [],
        }
        if self._folder_id:
            item["folderId"] = self._folder_id
        return item

    def get(self, key: str) -> Optional[str]:
        item = self._get_item(key)
        if not item:
            return None
        login = item.get("login")
        if not isinstance(login, dict):
            return None
        value = login.get("password")
        return str(value) if value else None

    def set(self, key: str, value: str) -> None:
        existing = self._get_item(key)
        if existing:
            login = existing.get("login")
            if not isinstance(login, dict):
                login = {}
                existing["login"] = login
            login["username"] = login.get("username") or key
            login["password"] = value
            encoded = self._encode(existing)
            item_id = str(existing.get("id") or key)
            r = self._bw("edit", "item", item_id, encoded)
        else:
            encoded = self._encode(self._build_item(key, value))
            r = self._bw("create", "item", encoded)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to store secret in Bitwarden: {r.stderr.strip()}")

    def delete(self, key: str) -> None:
        item = self._get_item(key)
        item_id = str(item.get("id") if item else key)
        self._bw("delete", "item", item_id)

    def list_set_keys(self) -> List[str]:
        args = ["list", "items"]
        if self._folder_id:
            args.extend(["--folderid", self._folder_id])
        r = self._bw(*args)
        if r.returncode != 0:
            return []
        try:
            items = json.loads(r.stdout)
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []
        return [
            str(item.get("name"))
            for item in items
            if isinstance(item, dict) and item.get("name")
        ]


# ---------------------------------------------------------------------------
# Backend loading / selection
# ---------------------------------------------------------------------------

_BACKEND_NAMES = {
    CANONICAL_BACKEND_NAME: "Vaultwarden (official Bitwarden bw CLI)",
}

_BACKEND_ALIASES = {
    "bitwarden": CANONICAL_BACKEND_NAME,
    "bw": CANONICAL_BACKEND_NAME,
}


def normalize_backend_name(name: Optional[str]) -> str:
    normalized = str(name or "").strip().lower()
    return _BACKEND_ALIASES.get(normalized, normalized)


def _bw_available() -> bool:
    return shutil.which("bw") is not None


def _instantiate_backend(name: str, cfg: dict) -> SecretsBackend:
    normalized = normalize_backend_name(name)
    if normalized == CANONICAL_BACKEND_NAME:
        secrets_cfg = cfg.get("secrets", {})
        return BitwardenCLIBackend(
            server_url=secrets_cfg.get("server_url") or DEFAULT_VAULTWARDEN_SERVER_URL,
            folder_id=secrets_cfg.get("folder_id"),
        )
    raise ValueError(
        f"Unknown secrets backend: {name!r}. Vaultwarden is the only supported secrets backend."
    )


def _load_backend() -> Optional[SecretsBackend]:
    """Load the configured backend from config.yaml, or return None."""
    cfg = _load_config()
    backend_name = cfg.get("secrets", {}).get("backend")
    if not backend_name:
        return None
    normalized = normalize_backend_name(backend_name)
    if normalized != CANONICAL_BACKEND_NAME:
        return None
    return _instantiate_backend(normalized, cfg)


def prompt_backend_selection() -> SecretsBackend:
    """Configure the single supported secrets backend: Vaultwarden."""
    from ..cli_utils import prompt_input

    print("\nNo secrets backend configured.")
    print("TrainShell stores secrets only in Vaultwarden through the official Bitwarden CLI (`bw`).")
    if not _bw_available():
        raise RuntimeError("Bitwarden CLI 'bw' is required for TrainShell secrets.")

    server_url = prompt_input(
        f"Vaultwarden server URL [{DEFAULT_VAULTWARDEN_SERVER_URL}]: ",
        default=DEFAULT_VAULTWARDEN_SERVER_URL,
    )
    folder_id = prompt_input("Vaultwarden folder ID for TrainShell secrets [none]: ")
    return _select_and_save(
        CANONICAL_BACKEND_NAME,
        server_url=server_url or DEFAULT_VAULTWARDEN_SERVER_URL,
        folder_id=folder_id or None,
    )


def _select_and_save(
    name: str,
    vault: Optional[str] = None,
    sa_token: Optional[str] = None,
    server_url: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> SecretsBackend:
    normalized = normalize_backend_name(name)
    if normalized != CANONICAL_BACKEND_NAME:
        raise ValueError("Vaultwarden is the only supported secrets backend.")

    cfg = _load_config()
    cfg.setdefault("secrets", {})
    cfg["secrets"]["backend"] = CANONICAL_BACKEND_NAME
    cfg["secrets"].pop("vault", None)
    cfg["secrets"].pop("sa_token", None)
    if server_url:
        cfg["secrets"]["server_url"] = server_url
    else:
        cfg["secrets"]["server_url"] = DEFAULT_VAULTWARDEN_SERVER_URL
    if folder_id:
        cfg["secrets"]["folder_id"] = folder_id
    else:
        cfg["secrets"].pop("folder_id", None)
    _save_config(cfg)
    return _instantiate_backend(CANONICAL_BACKEND_NAME, cfg)


def set_backend(
    name: str,
    vault: Optional[str] = None,
    sa_token: Optional[str] = None,
    server_url: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> SecretsBackend:
    """Explicitly switch to a named backend."""
    normalized = normalize_backend_name(name)
    if normalized not in _BACKEND_NAMES:
        raise ValueError(f"Unknown backend {name!r}. Choose from: {list(_BACKEND_NAMES)}")
    return _select_and_save(
        normalized,
        server_url=server_url,
        folder_id=folder_id,
    )


def get_configured_backend_name() -> Optional[str]:
    cfg = _load_config()
    backend_name = cfg.get("secrets", {}).get("backend")
    if not backend_name:
        return None
    normalized = normalize_backend_name(backend_name)
    return normalized if normalized in _BACKEND_NAMES else None


# ---------------------------------------------------------------------------
# SecretsManager (main public API)
# ---------------------------------------------------------------------------

class SecretsManager:
    """
    Vaultwarden-backed secrets manager.

    Resolution order for get():
      1. In-memory cache
      2. Vaultwarden through the official Bitwarden CLI (`bw`)
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

    def _get_direct_value(self, key: str) -> Optional[str]:
        normalized = normalize_secret_key(key)
        if normalized in self._cache:
            return self._cache[normalized]

        backend = self._get_backend()
        if backend is None:
            return None
        try:
            value = backend.get(normalized)
        except Exception:
            value = None
        if value:
            self._cache[normalized] = value
            return value
        return None

    def _get_bundle_payload(self, composite_key: str, provider: str) -> Optional[Dict[str, str]]:
        direct_value = self._get_direct_value(composite_key)
        payload = parse_secret_bundle_value(direct_value)
        if payload:
            return normalize_storage_bundle_payload(provider, payload)

        legacy_payload: Dict[str, str] = {}
        for field, aliases in bundle_component_alias_groups(composite_key, provider).items():
            for alias in aliases:
                value = self._get_direct_value(alias)
                if value:
                    legacy_payload[field] = value
                    break
        return normalize_storage_bundle_payload(provider, legacy_payload or None)

    def get(self, key: str) -> Optional[str]:
        normalized = normalize_secret_key(key)
        bundle_alias = resolve_secret_bundle_alias(normalized)
        if bundle_alias is None:
            direct_value = self._get_direct_value(normalized)
            if direct_value:
                return direct_value
            return None

        composite_key, field_name, provider = bundle_alias
        payload = self._get_bundle_payload(composite_key, provider)
        if not payload:
            return None

        if field_name is None:
            value = dump_secret_bundle_value(payload)
        else:
            value = str(payload.get(field_name, "")).strip()
            if not value:
                return None

        self._cache[normalized] = value
        return value

    def set(self, key: str, value: str) -> None:
        backend = self._require_backend()
        normalized = normalize_secret_key(key)
        backend.set(normalized, value)
        self._cache[normalized] = value

    def set_bundle(self, composite_key: str, payload: Dict[str, str]) -> None:
        normalized = normalize_secret_key(composite_key)
        bundle_alias = resolve_secret_bundle_alias(normalized)
        provider = bundle_alias[2] if bundle_alias is not None else ("r2" if normalized.endswith("_R2_CREDENTIALS") else "b2")
        normalized_payload = normalize_storage_bundle_payload(provider, payload) or {}
        serialized = dump_secret_bundle_value(normalized_payload)
        backend = self._require_backend()
        backend.set(normalized, serialized)
        self._cache[normalized] = serialized

        for alias_key in bundle_component_cleanup_aliases(normalized, provider):
            self._cache.pop(alias_key, None)
            if alias_key != normalized:
                try:
                    backend.delete(alias_key)
                except Exception:
                    pass

    def delete(self, key: str) -> None:
        normalized = normalize_secret_key(key)
        bundle_alias = resolve_secret_bundle_alias(normalized)
        target_key = bundle_alias[0] if bundle_alias is not None else normalized

        self._cache.pop(normalized, None)
        self._cache.pop(target_key, None)
        if bundle_alias is not None:
            for alias_key in bundle_component_cleanup_aliases(target_key, bundle_alias[2]):
                self._cache.pop(alias_key, None)

        backend = self._get_backend()
        if backend is not None:
            backend.delete(target_key)
            if bundle_alias is not None:
                for alias_key in bundle_component_cleanup_aliases(target_key, bundle_alias[2]):
                    if alias_key != target_key:
                        try:
                            backend.delete(alias_key)
                        except Exception:
                            pass

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def list_keys(self) -> List[str]:
        predefined = [
            SecretKeys.VAST_API_KEY,
            SecretKeys.RUNPOD_API_KEY,
            SecretKeys.POE_API_KEY,
            SecretKeys.HF_TOKEN,
            SecretKeys.OPENAI_API_KEY,
            SecretKeys.OPENROUTER_API_KEY,
            SecretKeys.ANTHROPIC_API_KEY,
            SecretKeys.GITHUB_TOKEN,
            SecretKeys.GOOGLE_DRIVE_CREDENTIALS,
            SecretKeys.R2_CREDENTIALS,
            SecretKeys.B2_CREDENTIALS,
        ]
        present: set[str] = set()

        present.update(normalize_secret_key(key) for key in self._cache)

        backend = self._get_backend()
        if backend is not None:
            try:
                present.update(
                    normalize_secret_key(key)
                    for key in backend.list_set_keys()
                    if key
                )
            except Exception:
                pass

        candidate_keys = list(predefined)
        candidate_lookup = {normalize_secret_key(key) for key in candidate_keys}
        extra_bundle_keys = {
            bundle_alias[0]
            for key in present
            if (bundle_alias := resolve_secret_bundle_alias(key)) is not None
        }
        for key in sorted(extra_bundle_keys):
            if key not in candidate_lookup:
                candidate_keys.append(key)
                candidate_lookup.add(key)

        available: List[str] = []
        for key in candidate_keys:
            normalized = normalize_secret_key(key)
            bundle_alias = resolve_secret_bundle_alias(normalized)
            if bundle_alias is None:
                if normalized in present or self.get(normalized) is not None:
                    available.append(key)
                continue

            composite_key, _field_name, provider = bundle_alias
            aliases = {normalize_secret_key(composite_key), *bundle_component_cleanup_aliases(composite_key, provider)}
            if present.intersection(aliases) or self.get(composite_key) is not None:
                available.append(key)

        return available

    # Convenience accessors
    def get_vast_api_key(self) -> Optional[str]:
        return self.get(SecretKeys.VAST_API_KEY)

    def set_vast_api_key(self, key: str) -> None:
        self.set(SecretKeys.VAST_API_KEY, key)

    def get_runpod_api_key(self) -> Optional[str]:
        return self.get(SecretKeys.RUNPOD_API_KEY)

    def set_runpod_api_key(self, key: str) -> None:
        self.set(SecretKeys.RUNPOD_API_KEY, key)

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
