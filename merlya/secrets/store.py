"""
Merlya Secrets - Secret store implementation.

Uses keyring for secure storage (macOS Keychain, Windows Credential Manager,
Linux Secret Service) with in-memory fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# Service name for keyring
SERVICE_NAME = "merlya"


@dataclass
class SecretStore:
    """
    Secure secret storage.

    Uses system keyring if available, otherwise falls back to in-memory storage.
    """

    _keyring_available: bool = field(default=False, init=False)
    _memory_store: dict[str, str] = field(default_factory=dict, init=False)
    _secret_names: set[str] = field(default_factory=set, init=False)

    _instance: "SecretStore | None" = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Check keyring availability."""
        self._keyring_available = self._check_keyring()
        if not self._keyring_available:
            logger.warning("⚠️ Keyring unavailable - using in-memory storage (secrets lost on exit)")

    def _check_keyring(self) -> bool:
        """Check if keyring is available and working."""
        try:
            import keyring

            # Test write/read/delete
            test_key = "__merlya_test__"
            test_value = "test_value"

            keyring.set_password(SERVICE_NAME, test_key, test_value)
            result = keyring.get_password(SERVICE_NAME, test_key)
            keyring.delete_password(SERVICE_NAME, test_key)

            return result == test_value

        except ImportError:
            logger.debug("keyring module not installed")
            return False
        except Exception as e:
            logger.debug(f"Keyring test failed: {e}")
            return False

    @property
    def is_secure(self) -> bool:
        """Check if using secure storage (keyring)."""
        return self._keyring_available

    def set(self, name: str, value: str) -> None:
        """
        Store a secret.

        Args:
            name: Secret name.
            value: Secret value.
        """
        if self._keyring_available:
            import keyring

            keyring.set_password(SERVICE_NAME, name, value)
        else:
            self._memory_store[name] = value

        self._secret_names.add(name)
        logger.debug(f"🔒 Secret '{name}' stored")

    def get(self, name: str) -> str | None:
        """
        Retrieve a secret.

        Args:
            name: Secret name.

        Returns:
            Secret value or None if not found.
        """
        if self._keyring_available:
            import keyring

            return keyring.get_password(SERVICE_NAME, name)
        else:
            return self._memory_store.get(name)

    def remove(self, name: str) -> bool:
        """
        Remove a secret.

        Args:
            name: Secret name.

        Returns:
            True if secret was removed, False if not found.
        """
        try:
            if self._keyring_available:
                import keyring

                keyring.delete_password(SERVICE_NAME, name)
            else:
                self._memory_store.pop(name, None)

            self._secret_names.discard(name)
            logger.debug(f"🔒 Secret '{name}' removed")
            return True

        except Exception as e:
            logger.debug(f"Failed to remove secret '{name}': {e}")
            return False

    def has(self, name: str) -> bool:
        """
        Check if a secret exists.

        Args:
            name: Secret name.

        Returns:
            True if secret exists.
        """
        return self.get(name) is not None

    def list_names(self) -> list[str]:
        """
        List all secret names.

        Note: Only returns names of secrets set in this session or
        previously tracked. Keyring doesn't provide enumeration.

        Returns:
            List of secret names.
        """
        return sorted(self._secret_names)

    @classmethod
    def get_instance(cls) -> "SecretStore":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        cls._instance = None


# Convenience functions
def get_secret_store() -> SecretStore:
    """Get secret store singleton."""
    return SecretStore.get_instance()


def set_secret(name: str, value: str) -> None:
    """Store a secret."""
    get_secret_store().set(name, value)


def get_secret(name: str) -> str | None:
    """Get a secret."""
    return get_secret_store().get(name)


def remove_secret(name: str) -> bool:
    """Remove a secret."""
    return get_secret_store().remove(name)


def has_secret(name: str) -> bool:
    """Check if secret exists."""
    return get_secret_store().has(name)


def list_secrets() -> list[str]:
    """List secret names."""
    return get_secret_store().list_names()
