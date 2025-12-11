"""
Merlya Secrets - Secret store implementation.

Uses keyring for secure storage (macOS Keychain, Windows Credential Manager,
Linux Secret Service) with in-memory fallback.

Secret names are persisted in ~/.merlya/secrets.json since keyring doesn't
provide enumeration.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from loguru import logger

# Service name for keyring
SERVICE_NAME = "merlya"

# File to persist secret names (keyring doesn't provide enumeration)
SECRETS_INDEX_FILE = Path.home() / ".merlya" / "secrets.json"


@dataclass
class SecretStore:
    """
    Secure secret storage.

    Uses system keyring if available, otherwise falls back to in-memory storage.
    Secret names are persisted in a separate index file since keyring doesn't
    provide enumeration.

    Thread-safe singleton pattern with atomic file writes.
    """

    # Class-level singleton with thread safety
    _instance: ClassVar[SecretStore | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    # Instance fields
    _keyring_available: bool = field(default=False, init=False)
    _memory_store: dict[str, str] = field(default_factory=dict, init=False)
    _secret_names: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        """Check keyring availability and load persisted secret names."""
        available, reason = self._check_keyring()
        self._keyring_available = available
        if not self._keyring_available:
            reason_suffix = f" ({reason})" if reason else ""
            logger.warning(
                "⚠️ Keyring unavailable - using in-memory storage (secrets lost on exit){}",
                reason_suffix,
            )

        # Load persisted secret names
        self._load_secret_names()

    def _check_keyring(self) -> tuple[bool, str | None]:
        """Check if keyring is available and working."""
        try:
            import keyring

            # Test write/read/delete
            test_key = "__merlya_test__"
            test_value = "test_value"

            keyring.set_password(SERVICE_NAME, test_key, test_value)
            result = keyring.get_password(SERVICE_NAME, test_key)
            keyring.delete_password(SERVICE_NAME, test_key)

            return result == test_value, None

        except ImportError:
            logger.debug("keyring module not installed")
            return False, "keyring module not installed"
        except Exception as e:
            logger.debug(f"Keyring test failed: {e}")
            return False, str(e)

    def _load_secret_names(self) -> None:
        """Load persisted secret names from index file."""
        if not SECRETS_INDEX_FILE.exists():
            return

        try:
            with SECRETS_INDEX_FILE.open(encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self._secret_names = set(data)
                    logger.debug(f"Loaded {len(self._secret_names)} secret names from index")
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Failed to load secret names index: {e}")

    def _save_secret_names(self) -> None:
        """Persist secret names to index file (atomic write)."""
        try:
            SECRETS_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first, then atomic rename
            fd, temp_path = tempfile.mkstemp(
                dir=SECRETS_INDEX_FILE.parent,
                prefix=".secrets_",
                suffix=".json.tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(sorted(self._secret_names), f, indent=2)
                # Atomic rename (POSIX guarantees atomicity)
                Path(temp_path).replace(SECRETS_INDEX_FILE)
                logger.debug(f"Saved {len(self._secret_names)} secret names to index")
            except Exception:
                # Clean up temp file on failure
                Path(temp_path).unlink(missing_ok=True)
                raise
        except OSError as e:
            logger.warning(f"Failed to save secret names index: {e}")

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
        self._save_secret_names()
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
            self._save_secret_names()
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

    def list_keys(self) -> list[str]:
        """Alias for list_names() for API compatibility."""
        return self.list_names()

    def delete(self, name: str) -> bool:
        """Alias for remove() for API compatibility."""
        return self.remove(name)

    @classmethod
    def get_instance(cls) -> SecretStore:
        """Get singleton instance (thread-safe)."""
        # Double-checked locking pattern
        if cls._instance is None:
            with cls._lock:
                # Check again after acquiring lock
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        with cls._lock:
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
