"""
Credential and Variable Manager for Merlya.

Manages:
- SSH credentials (ssh-agent, ~/.ssh/config, key files)
- Database credentials (interactive prompts with getpass)
- User variables with persistence (@host, @config)
- Secrets with storage hierarchy (session -> keyring -> env)

Storage hierarchy for secrets (resolution order):
1. Session cache (in-memory, 15min TTL) - fastest
2. System keyring (persistent, encrypted) - secure
3. Environment variables (MERLYA_<KEY>) - fallback
"""
import getpass
import os
import re
import time
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple

from merlya.security.ssh_credentials import SSHCredentialMixin
from merlya.utils.logger import logger


class VariableType(Enum):
    """Types of user-defined variables."""
    HOST = "host"      # Host aliases (@proddb → db-prod-001) - persisted
    CONFIG = "config"  # Configuration values (@region, @env) - persisted
    SECRET = "secret"  # Passwords, tokens, API keys - NEVER persisted


class CredentialManager(SSHCredentialMixin):
    """
    Manages credentials and user variables securely (Singleton).

    Features:
    - SSH: ssh-agent, ~/.ssh/config, key files
    - DB: Interactive prompts with getpass (never stored in plaintext)
    - Variables: Typed variables with SQLite persistence (except secrets)
    - Secrets: Storage hierarchy (session -> keyring -> env)

    Variable Types:
    - HOST: Alias for hostnames (persisted in SQLite)
    - CONFIG: General configuration values (persisted in SQLite)
    - SECRET: Passwords, tokens (session or keyring)

    Secret Resolution Order:
    1. Session cache (in-memory, fastest)
    2. System keyring (persistent, encrypted)
    3. Environment variables (MERLYA_<KEY>)

    Security:
    - Session credentials TTL: 15 minutes
    - Automatic expiration cleanup on access
    - Keyring uses OS-native encryption

    Note:
    - This is a Singleton to ensure all components share the same credentials
    - Use reset_instance() in tests to reset state between test cases
    """

    # Singleton instance
    _instance: Optional["CredentialManager"] = None

    # Storage key for variables in SQLite
    STORAGE_KEY = "user_variables"

    # Session credential TTL (15 minutes)
    CREDENTIAL_TTL = 900  # seconds

    def __new__(cls, storage_manager=None):
        """
        Singleton pattern - returns existing instance or creates new one.

        Note: If an instance exists but storage_manager is provided,
        it will update the storage manager (allows late initialization).
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, storage_manager=None):
        """
        Initialize CredentialManager.

        Args:
            storage_manager: Optional StorageManager for persistence.
                            If None, variables are stored in-memory only.

        Note: Only initializes once due to Singleton pattern.
              Subsequent calls with storage_manager will update it via set_storage().
        """
        # Only initialize once
        if getattr(self, '_initialized', False):
            # If storage_manager provided on subsequent call, update it
            if storage_manager is not None and self._storage is None:
                self.set_storage(storage_manager)
            return

        self.ssh_dir = Path.home() / ".ssh"
        self.ssh_config = self._parse_ssh_config()
        # Session credentials: {cache_key: (username, password, timestamp)}
        self.session_credentials: Dict[str, Tuple[str, str, float]] = {}

        # Variables with types: {key: (value, VariableType)}
        self._variables: Dict[str, Tuple[str, VariableType]] = {}

        # Storage manager for persistence
        self._storage = storage_manager

        # Keyring store (lazy-loaded)
        self._keyring_store = None

        # Load persisted variables
        self._load_variables()

        # Mark as initialized
        self._initialized = True

    @classmethod
    def reset_instance(cls) -> None:
        """
        Reset the singleton instance (for testing).

        This allows tests to start with a fresh CredentialManager.
        """
        cls._instance = None

    @classmethod
    def get_instance(cls) -> "CredentialManager":
        """
        Get the singleton instance, creating if needed.

        Returns:
            The shared CredentialManager instance
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_variables(self):
        """Load persisted variables from storage."""
        if not self._storage:
            return

        try:
            stored = self._storage.get_config(self.STORAGE_KEY, default={})
            if stored:
                for key, data in stored.items():
                    # data is [value, type_name]
                    if isinstance(data, list) and len(data) == 2:
                        value, type_name = data
                        try:
                            var_type = VariableType(type_name)
                            # Never load secrets from storage (shouldn't happen, but safety check)
                            if var_type != VariableType.SECRET:
                                self._variables[key] = (value, var_type)
                        except ValueError:
                            # Unknown type, default to CONFIG
                            self._variables[key] = (value, VariableType.CONFIG)
                logger.debug(f"🔑 Loaded {len(self._variables)} variables from storage")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load variables: {e}")

    def _save_variables(self):
        """Save non-secret variables to storage."""
        if not self._storage:
            return

        try:
            # Only save non-secret variables
            to_save = {
                key: [value, var_type.value]
                for key, (value, var_type) in self._variables.items()
                if var_type != VariableType.SECRET
            }
            self._storage.set_config(self.STORAGE_KEY, to_save)
            logger.debug(f"✅ Saved {len(to_save)} variables to storage")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save variables: {e}")

    def set_storage(self, storage_manager):
        """
        Set the storage manager (for late initialization).

        Args:
            storage_manager: StorageManager instance
        """
        self._storage = storage_manager
        self._load_variables()

    @property
    def keyring_store(self):
        """Lazy-load keyring store."""
        if self._keyring_store is None:
            from merlya.security.keyring_store import get_keyring_store
            self._keyring_store = get_keyring_store()
        return self._keyring_store

    # =========================================================================
    # Session Credential Management
    # =========================================================================

    def _is_credential_expired(self, timestamp: float) -> bool:
        """Check if a credential has expired based on TTL."""
        return (time.time() - timestamp) > self.CREDENTIAL_TTL

    def _cleanup_expired_credentials(self):
        """Remove expired credentials from session cache."""
        current_time = time.time()
        expired_keys = [
            key for key, (_, __, timestamp) in self.session_credentials.items()
            if (current_time - timestamp) > self.CREDENTIAL_TTL
        ]
        for key in expired_keys:
            del self.session_credentials[key]
            logger.debug(f"🔒 Expired credential removed: {key}")

    def _get_cached_credential(self, cache_key: str) -> Optional[Tuple[str, str]]:
        """
        Get cached credential if not expired.

        Returns:
            Tuple of (username, password) if valid, None if expired or not found
        """
        if cache_key not in self.session_credentials:
            return None

        username, password, timestamp = self.session_credentials[cache_key]
        if self._is_credential_expired(timestamp):
            del self.session_credentials[cache_key]
            logger.debug(f"🔒 Credential expired: {cache_key}")
            return None

        return (username, password)

    def _cache_credential(self, cache_key: str, username: str, password: str):
        """Cache credential with current timestamp (string key)."""
        self.session_credentials[cache_key] = (username, password, time.time())

    def _cache_credential_tuple(self, cache_key: tuple, username: str, password: str):
        """
        Cache credential with tuple key for collision-safe storage.

        Using tuple keys like (service, target) prevents cache key collision attacks
        where "service@evil" + "target" would collide with "service" + "evil@target".
        """
        self.session_credentials[cache_key] = (username, password, time.time())

    # =========================================================================
    # Database Credentials
    # =========================================================================

    def get_db_credentials(self, host: str, service: str = "mongodb",
                          username: Optional[str] = None,
                          password: Optional[str] = None) -> Tuple[str, str]:
        """
        Get database credentials securely.

        Priority:
        1. Explicit credentials passed as arguments
        2. Environment variables (MONGODB_USER, MONGODB_PASS)
        3. Session cache (already prompted in this session, not expired)
        4. Interactive prompt with getpass (secure input)

        Note: Session credentials expire after 15 minutes (CREDENTIAL_TTL)
        """
        cache_key = f"{service}@{host}"

        # Cleanup expired credentials periodically
        self._cleanup_expired_credentials()

        # Priority 1: Explicit credentials
        if username and password:
            self._cache_credential(cache_key, username, password)
            return (username, password)

        # Priority 2: Session cache (with TTL check)
        cached = self._get_cached_credential(cache_key)
        if cached:
            # Audit log credential access
            logger.info(f"🔐 Database credential accessed: {service}@{host} (from cache)")
            return cached

        # Priority 3: Environment variables
        env_user_key = f"{service.upper()}_USER"
        env_pass_key = f"{service.upper()}_PASS"

        if env_user_key in os.environ and env_pass_key in os.environ:
            username = os.environ[env_user_key]
            password = os.environ[env_pass_key]
            self._cache_credential(cache_key, username, password)
            return (username, password)

        # Priority 4: Interactive prompt
        print(f"\n[Credentials needed for {service} on {host}]")
        username = input(f"{service} username: ")
        password = getpass.getpass(f"{service} password: ")

        self._cache_credential(cache_key, username, password)
        return (username, password)

    def has_db_credentials(self, host: str, service: str = "mongodb") -> bool:
        """Check if credentials are available without prompting (and not expired)."""
        cache_key = f"{service}@{host}"

        # Check if cached credential exists and is not expired
        if self._get_cached_credential(cache_key):
            return True

        env_user_key = f"{service.upper()}_USER"
        env_pass_key = f"{service.upper()}_PASS"

        return env_user_key in os.environ and env_pass_key in os.environ

    def clear_session_credentials(self):
        """Clear cached credentials from session."""
        self.session_credentials.clear()

    # =========================================================================
    # User Variables (@variables)
    # =========================================================================

    def set_variable(self, key: str, value: str, var_type: VariableType = VariableType.CONFIG):
        """
        Set a user variable.

        Args:
            key: Variable name (e.g., "proddb", "mongo-user")
            value: Variable value
            var_type: Type of variable (HOST, CONFIG, SECRET)
        """
        self._variables[key] = (value, var_type)

        # Auto-save if not a secret
        if var_type != VariableType.SECRET:
            self._save_variables()

    def set_host(self, key: str, value: str):
        """Set a host alias variable (persisted)."""
        self.set_variable(key, value, VariableType.HOST)

    def set_config_var(self, key: str, value: str):
        """Set a configuration variable (persisted)."""
        self.set_variable(key, value, VariableType.CONFIG)

    def set_secret(self, key: str, value: str):
        """Set a secret variable (NOT persisted)."""
        self.set_variable(key, value, VariableType.SECRET)

    def set_variable_secure(self, key: str, var_type: VariableType = VariableType.SECRET) -> bool:
        """
        Set a variable securely using getpass (for passwords, API keys, tokens).

        Args:
            key: Variable name
            var_type: Type of variable (default: SECRET)

        Returns:
            True if set successfully, False if cancelled
        """
        try:
            print(f"\n[Secure input for '{key}']")
            value = getpass.getpass(f"{key}: ")
            if value:
                self.set_variable(key, value, var_type)
                return True
            else:
                print("Empty value - not saved")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled")
            return False

    def get_variable(self, key: str) -> Optional[str]:
        """
        Get a variable value with storage hierarchy for secrets.

        Resolution order for secrets:
        1. Session cache (in-memory)
        2. System keyring (persistent)
        3. Environment variable (MERLYA_<KEY>)

        Note: Access to SECRET type variables is audit logged for security tracking.
        """
        # Check session variables first
        if key in self._variables:
            value, var_type = self._variables[key]

            # Audit log secret access (security requirement)
            if var_type == VariableType.SECRET:
                logger.info(f"🔐 Secret accessed: {key} (type=SECRET, source=session)")

            return value

        # For unknown keys, check keyring (might be a persisted secret)
        keyring_value = self.keyring_store.retrieve(key)
        if keyring_value:
            logger.info(f"🔐 Secret accessed: {key} (source=keyring)")
            # Cache in session for faster access
            self._variables[key] = (keyring_value, VariableType.SECRET)
            return keyring_value

        # Check environment variable as fallback
        env_key = f"MERLYA_{key.upper().replace('-', '_')}"
        env_value = os.environ.get(env_key)
        if env_value:
            logger.debug(f"🔐 Variable loaded from env: {env_key}")
            return env_value

        return None

    def get_variable_type(self, key: str) -> Optional[VariableType]:
        """Get a variable's type."""
        if key in self._variables:
            return self._variables[key][1]
        return None

    def delete_variable(self, key: str) -> bool:
        """Delete a variable. Returns True if deleted, False if not found."""
        if key in self._variables:
            del self._variables[key]
            self._save_variables()
            return True
        return False

    def list_variables(self) -> Dict[str, str]:
        """List all variables (values only, for backward compatibility)."""
        return {key: value for key, (value, _) in self._variables.items()}

    def list_variables_typed(self) -> Dict[str, Tuple[str, VariableType]]:
        """List all variables with their types."""
        return self._variables.copy()

    def list_variables_by_type(self, var_type: VariableType) -> Dict[str, str]:
        """List variables of a specific type."""
        return {
            key: value
            for key, (value, vtype) in self._variables.items()
            if vtype == var_type
        }

    def clear_variables(self):
        """Clear all variables."""
        self._variables.clear()
        self._save_variables()

    def clear_secrets(self):
        """Clear only secret variables (keeps HOST and CONFIG)."""
        self._variables = {
            key: (value, vtype)
            for key, (value, vtype) in self._variables.items()
            if vtype != VariableType.SECRET
        }
        # No need to save - secrets weren't persisted anyway

    # =========================================================================
    # Variable Resolution
    # =========================================================================

    def resolve_variables(self, text: str, warn_missing: bool = True, resolve_secrets: bool = True) -> str:
        """
        Resolve @variable references in text.

        Args:
            text: Text containing @variable references
            warn_missing: If True, warn about unresolved variables
            resolve_secrets: If True, resolve secret variables to their values.
                           If False, keep @secret_name for secrets (to prevent leaking to LLM).

        Returns:
            Text with variables replaced by their values

        Example:
            "check mysql on @proddb using @dbuser @dbpass"
            -> "check mysql on db-prod-001 using admin secret123" (resolve_secrets=True)
            -> "check mysql on db-prod-001 using admin @dbpass" (resolve_secrets=False)

        Resolution order:
        1. User-defined variables (from /variables command)
        2. Inventory hosts (from /inventory command)
        """
        resolved = text

        # Track secret variable names to exclude from inventory resolution
        secret_var_names = set()

        # Replace all known user variables first (higher priority)
        for key, (value, var_type) in self._variables.items():
            # Skip secrets if resolve_secrets is False
            if var_type == VariableType.SECRET and not resolve_secrets:
                secret_var_names.add(key)
                continue
            # Use negative lookahead to match variable names that can contain hyphens
            # (consistent with _resolve_inventory_hosts and variable_pattern)
            # Use simple string replacement instead of re.sub with lambda
            pattern = f'@{re.escape(key)}'
            resolved = re.sub(f'{pattern}(?![\\w\\-])', str(value), resolved)

        # Find remaining unresolved variables
        variable_pattern = r'@([\w\-]+)'
        remaining = re.findall(variable_pattern, resolved)

        # Try to resolve from inventory (but exclude secret variable names)
        if remaining:
            # Filter out secret variable names to prevent inventory from resolving them
            remaining_for_inventory = [v for v in remaining if v not in secret_var_names]
            if remaining_for_inventory:
                resolved = self._resolve_inventory_hosts(resolved, remaining_for_inventory)

        # Check for still unresolved variables (exclude intentionally unresolved secrets)
        if warn_missing:
            still_unresolved = re.findall(variable_pattern, resolved)
            # Filter out secret variables that were intentionally left unresolved
            still_unresolved = [v for v in still_unresolved if v not in secret_var_names]
            for var in still_unresolved:
                logger.warning(
                    f"⚠️ Variable @{var} referenced but not defined. "
                    f"Use '/variables set {var} <value>' or '/inventory add' to define it."
                )

        return resolved

    def _resolve_inventory_hosts(self, text: str, variables: list) -> str:
        """
        Resolve @hostname references from inventory.

        Args:
            text: Text with @variable references
            variables: List of unresolved variable names

        Returns:
            Text with inventory hostnames resolved
        """
        try:
            from merlya.memory.persistence.inventory_repository import get_inventory_repository
            repo = get_inventory_repository()

            for var in variables:
                # Try to find host in inventory
                host = repo.get_host_by_name(var)
                if host:
                    # Use hostname only (command-compatible, no parentheses that break shell)
                    replacement = str(host["hostname"])
                    ip = host.get("ip")
                    # Use simple string replacement
                    pattern = f'@{re.escape(var)}'
                    text = re.sub(f'{pattern}(?![\\w\\-])', replacement, text)
                    if ip:
                        logger.debug(f"✅ Resolved @{var} to inventory host: {replacement} (IP: {ip})")
                    else:
                        logger.debug(f"✅ Resolved @{var} to inventory host: {replacement}")

        except ImportError:
            logger.debug("🔍 Inventory repository not available for host resolution")
        except Exception as e:
            logger.debug(f"⚠️ Failed to resolve inventory hosts: {e}")

        return text

    def get_inventory_hosts(self) -> list:
        """
        Get list of hostnames from inventory for auto-completion.

        Returns:
            List of hostname strings
        """
        try:
            from merlya.memory.persistence.inventory_repository import get_inventory_repository
            repo = get_inventory_repository()
            hosts = repo.get_all_hosts()
            return [h["hostname"] for h in hosts]
        except Exception:
            return []

    def has_variables(self, text: str) -> bool:
        """Check if text contains @variable references."""
        return bool(re.search(r'@[\w\-]+', text))

    # =========================================================================
    # Credential Extraction from Prompts
    # =========================================================================

    @staticmethod
    def extract_credentials_from_prompt(prompt: str) -> Optional[Tuple[str, str]]:
        """
        Extract credentials from user prompt if provided in plain text.

        Supports patterns:
        - "user admin password secret123"
        - "username admin passwd secret"
        - "with credentials admin/secret123"
        - "using admin:secret123"
        - "-u admin -p secret"

        Returns:
            (username, password) tuple if found, None otherwise
        """
        patterns = [
            # "user <username> password <password>"
            r'(?:user|username)\s+(\S+)\s+(?:password|passwd|pass|pwd)\s+(\S+)',
            # "credentials username/password" or "credentials username:password"
            r'(?:credentials?|creds?)\s+(\S+)[/:](\S+)',
            # "credential(s) username password"
            r'(?:credentials?|creds?)\s+(\S+)\s+(\S+)',
            # "using username:password"
            r'using\s+(\S+):(\S+)',
            # "-u username -p password"
            r'-u\s+(\S+)\s+-p\s+(\S+)',
            # "--username username --password password"
            r'--username\s+(\S+)\s+--password\s+(\S+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                return (match.group(1), match.group(2))

        return None


def get_credential_manager() -> CredentialManager:
    """
    Get the shared CredentialManager singleton instance.

    This is the recommended way to access credentials from any module.
    Ensures all components share the same in-memory secrets cache.

    Returns:
        The shared CredentialManager instance

    Example:
        from merlya.security.credentials import get_credential_manager

        creds = get_credential_manager()
        passphrase = creds.get_variable("ssh-passphrase-id_ed25519")
    """
    return CredentialManager.get_instance()
