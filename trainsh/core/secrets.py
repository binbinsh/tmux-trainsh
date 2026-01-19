# tmux-trainsh secrets management
# Uses keyring CLI for cross-platform secret storage

import os
import shutil
import subprocess
from typing import List, Optional

from ..constants import KEYRING_SERVICE, SecretKeys


def _keyring_available() -> bool:
    """Check if keyring CLI is available."""
    return shutil.which("keyring") is not None


def _keyring_get(service: str, key: str) -> Optional[str]:
    """Get a secret using keyring CLI."""
    try:
        result = subprocess.run(
            ["keyring", "get", service, key],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def _keyring_set(service: str, key: str, value: str) -> bool:
    """Set a secret using keyring CLI."""
    try:
        result = subprocess.run(
            ["keyring", "set", service, key],
            input=value,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _keyring_delete(service: str, key: str) -> bool:
    """Delete a secret using keyring CLI."""
    try:
        result = subprocess.run(
            ["keyring", "del", service, key],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


class SecretsManager:
    """
    Cross-platform secrets management using system keyring CLI.

    On macOS: Uses Keychain
    On Linux: Uses Secret Service (GNOME Keyring, KWallet, etc.)
    On Windows: Uses Windows Credential Manager

    Falls back to environment variables if keyring is not available.
    """

    def __init__(self, service: str = KEYRING_SERVICE):
        self.service = service
        self._cache: dict[str, str] = {}
        self._keyring_available = _keyring_available()

    def get(self, key: str) -> Optional[str]:
        """
        Get a secret value.

        Checks in order:
        1. Cache
        2. Environment variable
        3. Keyring

        Args:
            key: The secret key name

        Returns:
            The secret value, or None if not found
        """
        # Check cache first
        if key in self._cache:
            return self._cache[key]

        # Check environment variable
        env_value = os.environ.get(key)
        if env_value:
            return env_value

        # Check keyring
        if self._keyring_available:
            value = _keyring_get(self.service, key)
            if value:
                self._cache[key] = value
                return value

        return None

    def set(self, key: str, value: str) -> None:
        """
        Store a secret value.

        Args:
            key: The secret key name
            value: The secret value
        """
        if not self._keyring_available:
            raise RuntimeError(
                "keyring CLI not available. Install with: uv tool install keyring"
            )

        if not _keyring_set(self.service, key, value):
            raise RuntimeError("Failed to store secret")

        self._cache[key] = value

    def delete(self, key: str) -> None:
        """
        Delete a secret.

        Args:
            key: The secret key name
        """
        # Drop from cache
        self._cache.pop(key, None)

        if self._keyring_available:
            _keyring_delete(self.service, key)

    def exists(self, key: str) -> bool:
        """
        Check if a secret exists.

        Args:
            key: The secret key name

        Returns:
            True if the secret exists
        """
        return self.get(key) is not None

    def list_keys(self) -> List[str]:
        """
        List all predefined secret keys and their status.

        Returns:
            List of key names that have values set
        """
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

    def get_vast_api_key(self) -> Optional[str]:
        """Get Vast.ai API key."""
        return self.get(SecretKeys.VAST_API_KEY)

    def set_vast_api_key(self, key: str) -> None:
        """Set Vast.ai API key."""
        self.set(SecretKeys.VAST_API_KEY, key)

    def get_hf_token(self) -> Optional[str]:
        """Get HuggingFace token."""
        return self.get(SecretKeys.HF_TOKEN)

    def set_hf_token(self, token: str) -> None:
        """Set HuggingFace token."""
        self.set(SecretKeys.HF_TOKEN, token)

    def get_github_token(self) -> Optional[str]:
        """Get GitHub token."""
        return self.get(SecretKeys.GITHUB_TOKEN)

    def set_github_token(self, token: str) -> None:
        """Set GitHub token."""
        self.set(SecretKeys.GITHUB_TOKEN, token)

    def clear_cache(self) -> None:
        """Clear the in-memory cache."""
        self._cache.clear()

    @property
    def is_available(self) -> bool:
        """Check if keyring is available."""
        return self._keyring_available


# Global instance
_secrets_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get the global secrets manager instance."""
    global _secrets_manager
    if _secrets_manager is None:
        _secrets_manager = SecretsManager()
    return _secrets_manager
