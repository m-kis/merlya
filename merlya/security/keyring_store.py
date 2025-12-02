"""
Keyring-based secure secret storage for Merlya.

Provides persistent, encrypted storage for secrets using the OS keyring:
- macOS: Keychain
- Windows: Credential Vault
- Linux: Secret Service (GNOME Keyring, KWallet)

Storage hierarchy (resolution order):
1. Session cache (in-memory, 15min TTL) - fastest
2. System keyring (persistent, encrypted) - secure
3. Environment variables - fallback

Thread Safety:
    Metadata operations are protected by a threading.Lock to prevent
    race conditions in concurrent access scenarios.
"""
import re
import threading
from typing import Dict, List, Optional

from merlya.utils.logger import logger

# Maximum key length to prevent abuse
MAX_KEY_LENGTH = 256
# Valid key pattern: alphanumeric, dash, underscore, slash (for paths)
KEY_PATTERN = re.compile(r'^[a-zA-Z0-9_\-/]+$')

# Import keyring with fallback
try:
    import keyring
    from keyring.errors import KeyringError, PasswordDeleteError

    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False
    KeyringError = Exception
    PasswordDeleteError = Exception


class KeyringSecretStore:
    """
    Secure secret storage using system keyring.

    Key naming conventions:
    - merlya/<secret-name>           : User secrets
    - merlya/cred/<service>/<host>   : Auto-stored credentials
    - merlya/provider/<name>         : Cloud provider API keys

    Security:
    - Uses OS-native encryption
    - Requires user authentication to access
    - Secrets are isolated per user account

    Fallback behavior:
    - When keyring is unavailable, fails silently to avoid log spam
    - Warning logged only once at startup
    - Operations return graceful failures (False for store/delete, None for retrieve)
    """

    SERVICE_NAME = "merlya"
    # Separator for composite keys
    KEY_SEPARATOR = "/"
    # Metadata key to track stored secret names
    METADATA_KEY = "__merlya_secret_keys__"

    def __init__(self):
        """Initialize the keyring store."""
        self._available = HAS_KEYRING
        self._backend_name: Optional[str] = None
        self._unavailable_warned = False  # Track if we've already warned
        self._metadata_lock = threading.Lock()  # Protect metadata operations

        if self._available:
            try:
                # Test keyring availability
                backend = keyring.get_keyring()
                self._backend_name = backend.__class__.__name__

                # Check if it's a "null" backend that won't actually store anything
                # Common fallback backends that don't persist secrets
                null_backends = [
                    "fail.Keyring",
                    "NullKeyring",
                    "ChainerBackend",  # Only if all chained backends fail
                ]
                if any(nb in self._backend_name for nb in null_backends):
                    logger.warning(
                        f"⚠️ Keyring backend '{self._backend_name}' does not persist secrets. "
                        "Secrets will only be stored in session memory."
                    )
                    self._available = False
                    self._unavailable_warned = True
                else:
                    logger.debug(f"🔐 Keyring backend: {self._backend_name}")
            except Exception as e:
                error_name = type(e).__name__
                logger.warning(
                    f"⚠️ Keyring not available ({error_name}). "
                    "Secrets will only be stored in session memory. "
                    "To enable persistent secret storage, install and configure a keyring backend."
                )
                self._available = False
                self._unavailable_warned = True

    @property
    def is_available(self) -> bool:
        """Check if keyring is available."""
        return self._available

    @property
    def backend_name(self) -> Optional[str]:
        """Get the keyring backend name."""
        return self._backend_name

    def _full_key(self, key: str) -> str:
        """Build full key with service prefix."""
        return f"{self.SERVICE_NAME}{self.KEY_SEPARATOR}{key}"

    def _validate_key(self, key: str) -> None:
        """
        Validate a secret key.

        Args:
            key: The key to validate

        Raises:
            ValueError: If the key is invalid
        """
        if not key:
            raise ValueError("Secret key cannot be empty")
        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(f"Secret key too long (max {MAX_KEY_LENGTH} chars)")
        if '\n' in key or '\r' in key:
            raise ValueError("Secret key cannot contain newlines")
        if not KEY_PATTERN.match(key):
            raise ValueError(
                "Secret key can only contain alphanumeric characters, "
                "dashes, underscores, and forward slashes"
            )

    def store(self, key: str, value: str, require_persistence: bool = False) -> bool:
        """
        Store a secret in the system keyring.

        Args:
            key: Secret name (e.g., "db-password", "cred/mongodb/db-prod-01")
            value: Secret value
            require_persistence: If True, raises RuntimeError when keyring unavailable
                instead of silently returning False. Use this for critical secrets
                that MUST be persisted.

        Returns:
            True if stored successfully, False otherwise

        Raises:
            ValueError: If the key is invalid
            RuntimeError: If require_persistence=True and keyring is unavailable
        """
        if not self._available:
            # Only warn once to avoid log spam
            if not self._unavailable_warned:
                logger.warning("⚠️ Keyring not available, secrets will not be persisted")
                self._unavailable_warned = True
            if require_persistence:
                raise RuntimeError(
                    "Keyring not available but persistent storage was required. "
                    "Install and configure a keyring backend."
                )
            return False

        # Validate key before storing
        self._validate_key(key)

        try:
            full_key = self._full_key(key)
            keyring.set_password(self.SERVICE_NAME, full_key, value)
            # Track the key in metadata
            self._add_key_to_metadata(key)
            logger.info(f"✅ Secret stored in keyring: {key}")
            return True
        except KeyringError as e:
            # Sanitize error message to avoid leaking secret values
            logger.error(f"❌ Failed to store secret '{key}' in keyring: {type(e).__name__}")
            return False
        except Exception as e:
            # Log only the exception type, not the message (may contain secrets)
            logger.error(f"❌ Unexpected error storing secret '{key}': {type(e).__name__}")
            return False

    def retrieve(self, key: str) -> Optional[str]:
        """
        Retrieve a secret from the keyring.

        Args:
            key: Secret name

        Returns:
            Secret value if found, None otherwise

        Raises:
            ValueError: If the key is invalid
        """
        if not self._available:
            # Silently return None when keyring unavailable - no log spam
            return None

        # Validate key before retrieving
        self._validate_key(key)

        try:
            full_key = self._full_key(key)
            value = keyring.get_password(self.SERVICE_NAME, full_key)
            if value:
                logger.debug(f"🔐 Secret retrieved from keyring: {key}")
            return value
        except KeyringError as e:
            # Sanitize error - don't log exception message
            # Only log debug level to avoid spam
            logger.debug(f"🔐 Keyring retrieve failed for '{key}': {type(e).__name__}")
            return None
        except Exception as e:
            logger.debug(f"🔐 Keyring retrieve error for '{key}': {type(e).__name__}")
            return None

    def delete(self, key: str) -> bool:
        """
        Delete a secret from the keyring.

        Args:
            key: Secret name

        Returns:
            True if deleted successfully, False otherwise

        Raises:
            ValueError: If the key is invalid
        """
        if not self._available:
            return False

        # Validate key before deleting
        self._validate_key(key)

        try:
            full_key = self._full_key(key)
            keyring.delete_password(self.SERVICE_NAME, full_key)
            # Remove from metadata
            self._remove_key_from_metadata(key)
            logger.info(f"✅ Secret deleted from keyring: {key}")
            return True
        except PasswordDeleteError:
            logger.debug(f"🔍 Secret not found in keyring: {key}")
            return False
        except KeyringError as e:
            # Sanitize error - don't log exception message
            logger.error(f"❌ Failed to delete secret '{key}': {type(e).__name__}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error deleting secret '{key}': {type(e).__name__}")
            return False

    def list_keys(self) -> List[str]:
        """
        List all stored secret keys (not values).

        Returns:
            List of secret key names
        """
        if not self._available:
            return []

        try:
            # Retrieve metadata containing key list
            metadata = keyring.get_password(self.SERVICE_NAME, self.METADATA_KEY)
            if metadata:
                return metadata.split("\n")
            return []
        except Exception as e:
            logger.warning(f"⚠️ Failed to list keyring keys: {e}")
            return []

    def _add_key_to_metadata(self, key: str) -> None:
        """Add a key to the metadata tracking list (thread-safe)."""
        with self._metadata_lock:
            try:
                keys = self.list_keys()
                if key not in keys:
                    keys.append(key)
                    keyring.set_password(
                        self.SERVICE_NAME, self.METADATA_KEY, "\n".join(keys)
                    )
            except Exception as e:
                logger.debug(f"⚠️ Failed to update metadata: {e}")

    def _remove_key_from_metadata(self, key: str) -> None:
        """Remove a key from the metadata tracking list (thread-safe)."""
        with self._metadata_lock:
            try:
                keys = self.list_keys()
                if key in keys:
                    keys.remove(key)
                    if keys:
                        keyring.set_password(
                            self.SERVICE_NAME, self.METADATA_KEY, "\n".join(keys)
                        )
                    else:
                        # Clean up metadata if empty
                        try:
                            keyring.delete_password(self.SERVICE_NAME, self.METADATA_KEY)
                        except PasswordDeleteError:
                            pass
            except Exception as e:
                logger.debug(f"⚠️ Failed to update metadata: {e}")

    def clear_all(self) -> int:
        """
        Clear all secrets from the keyring.

        Returns:
            Number of secrets deleted
        """
        if not self._available:
            return 0

        keys = self.list_keys()
        deleted = 0
        for key in keys:
            if self.delete(key):
                deleted += 1

        # Clean up metadata
        try:
            keyring.delete_password(self.SERVICE_NAME, self.METADATA_KEY)
        except (PasswordDeleteError, KeyringError):
            pass

        logger.info(f"✅ Cleared {deleted} secrets from keyring")
        return deleted

    def has_secret(self, key: str) -> bool:
        """
        Check if a secret exists in the keyring (without retrieving value).

        Args:
            key: Secret name

        Returns:
            True if secret exists
        """
        return key in self.list_keys()

    # =========================================================================
    # Credential helpers (for auto-stored credentials)
    # =========================================================================

    def store_credential(
        self, service: str, host: str, username: str, password: str
    ) -> bool:
        """
        Store service credentials for a host.

        Args:
            service: Service name (e.g., "mongodb", "mysql")
            host: Hostname
            username: Username
            password: Password

        Returns:
            True if stored successfully
        """
        user_key = f"cred/{service}/{host}/user"
        pass_key = f"cred/{service}/{host}/pass"

        user_ok = self.store(user_key, username)
        pass_ok = self.store(pass_key, password)

        return user_ok and pass_ok

    def retrieve_credential(
        self, service: str, host: str
    ) -> Optional[Dict[str, str]]:
        """
        Retrieve service credentials for a host.

        Args:
            service: Service name
            host: Hostname

        Returns:
            Dict with 'username' and 'password' if found, None otherwise
        """
        user_key = f"cred/{service}/{host}/user"
        pass_key = f"cred/{service}/{host}/pass"

        username = self.retrieve(user_key)
        password = self.retrieve(pass_key)

        if username and password:
            return {"username": username, "password": password}
        return None

    def delete_credential(self, service: str, host: str) -> bool:
        """
        Delete service credentials for a host.

        Args:
            service: Service name
            host: Hostname

        Returns:
            True if deleted successfully
        """
        user_key = f"cred/{service}/{host}/user"
        pass_key = f"cred/{service}/{host}/pass"

        user_ok = self.delete(user_key)
        pass_ok = self.delete(pass_key)

        return user_ok or pass_ok

    def list_credentials(self) -> List[Dict[str, str]]:
        """
        List all stored credentials (service/host pairs only, not values).

        Returns:
            List of dicts with 'service' and 'host' keys
        """
        keys = self.list_keys()
        credentials = []
        seen = set()

        for key in keys:
            if key.startswith("cred/"):
                parts = key.split("/")
                if len(parts) >= 3:
                    service = parts[1]
                    host = parts[2]
                    pair = (service, host)
                    if pair not in seen:
                        seen.add(pair)
                        credentials.append({"service": service, "host": host})

        return credentials


# Singleton instance
_keyring_store: Optional[KeyringSecretStore] = None


def get_keyring_store() -> KeyringSecretStore:
    """Get or create the singleton keyring store instance."""
    global _keyring_store
    if _keyring_store is None:
        _keyring_store = KeyringSecretStore()
    return _keyring_store


def reset_keyring_store() -> None:
    """Reset the singleton instance (for testing)."""
    global _keyring_store
    _keyring_store = None
