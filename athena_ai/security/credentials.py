"""
Credential and Variable Manager for Athena.

Manages:
- SSH credentials (ssh-agent, ~/.ssh/config, key files)
- Database credentials (interactive prompts with getpass)
- User variables with persistence (@host, @config) and secrets (@secret - never persisted)
"""
import getpass
import os
import re
import time
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from athena_ai.utils.logger import logger


class VariableType(Enum):
    """Types of user-defined variables."""
    HOST = "host"      # Host aliases (@proddb → db-prod-001) - persisted
    CONFIG = "config"  # Configuration values (@region, @env) - persisted
    SECRET = "secret"  # Passwords, tokens, API keys - NEVER persisted


class CredentialManager:
    """
    Manages credentials and user variables securely.

    Features:
    - SSH: ssh-agent, ~/.ssh/config, key files
    - DB: Interactive prompts with getpass (never stored in plaintext)
    - Variables: Typed variables with SQLite persistence (except secrets)

    Variable Types:
    - HOST: Alias for hostnames (persisted)
    - CONFIG: General configuration values (persisted)
    - SECRET: Passwords, tokens (in-memory only, never persisted)

    Security:
    - Session credentials TTL: 15 minutes
    - Automatic expiration cleanup on access
    """

    # Storage key for variables in SQLite
    STORAGE_KEY = "user_variables"

    # Session credential TTL (15 minutes)
    CREDENTIAL_TTL = 900  # seconds

    def __init__(self, storage_manager=None):
        """
        Initialize CredentialManager.

        Args:
            storage_manager: Optional StorageManager for persistence.
                            If None, variables are stored in-memory only.
        """
        self.ssh_dir = Path.home() / ".ssh"
        self.ssh_config = self._parse_ssh_config()
        # Session credentials: {cache_key: (username, password, timestamp)}
        self.session_credentials: Dict[str, Tuple[str, str, float]] = {}

        # Variables with types: {key: (value, VariableType)}
        self._variables: Dict[str, Tuple[str, VariableType]] = {}

        # Storage manager for persistence
        self._storage = storage_manager

        # Load persisted variables
        self._load_variables()

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
        """Cache credential with current timestamp."""
        self.session_credentials[cache_key] = (username, password, time.time())

    # =========================================================================
    # SSH Configuration
    # =========================================================================

    def _parse_ssh_config(self) -> dict:
        """Parse ~/.ssh/config for host-specific settings."""
        config_file = self.ssh_dir / "config"
        config = {}

        if not config_file.exists():
            return config

        try:
            current_host = None
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    if line.lower().startswith('host '):
                        current_host = line.split(maxsplit=1)[1]
                        config[current_host] = {}
                    elif current_host and ' ' in line:
                        key, value = line.split(maxsplit=1)
                        config[current_host][key.lower()] = value

        except Exception:
            pass

        return config

    def get_user_for_host(self, host: str) -> str:
        """Get the SSH user for a host from config, or default to current user."""
        if host in self.ssh_config and 'user' in self.ssh_config[host]:
            return self.ssh_config[host]['user']
        return os.getenv('USER', 'root')

    def get_key_for_host(self, host: str) -> Optional[str]:
        """Get the SSH key for a specific host from config."""
        if host in self.ssh_config and 'identityfile' in self.ssh_config[host]:
            key_path = self.ssh_config[host]['identityfile']
            key_path = os.path.expanduser(key_path)
            if os.path.exists(key_path):
                return key_path
        return None

    def get_ssh_keys(self) -> List[str]:
        """Retrieve available SSH private keys from ~/.ssh."""
        keys = []
        if self.ssh_dir.exists():
            for file in self.ssh_dir.iterdir():
                if file.is_file() and not file.name.endswith(".pub") and "known_hosts" not in file.name and "config" not in file.name:
                    if (self.ssh_dir / (file.name + ".pub")).exists() or "id_" in file.name:
                        keys.append(str(file))
        return keys

    def get_default_key(self) -> Optional[str]:
        """Return the default SSH key (id_ed25519, id_rsa, etc.)."""
        defaults = ["id_ed25519", "id_ecdsa", "id_rsa", "id_dsa"]
        for name in defaults:
            key_path = self.ssh_dir / name
            if key_path.exists():
                return str(key_path)

        keys = self.get_ssh_keys()
        if keys:
            return keys[0]
        return None

    def supports_agent(self) -> bool:
        """Check if ssh-agent is available."""
        return 'SSH_AUTH_SOCK' in os.environ

    def get_agent_keys(self) -> List[str]:
        """Get list of keys loaded in ssh-agent."""
        if not self.supports_agent():
            return []

        try:
            import paramiko
            agent = paramiko.Agent()
            keys = agent.get_keys()
            return [f"ssh-agent key {i+1}" for i in range(len(keys))]
        except Exception:
            return []

    def is_agent_available(self) -> bool:
        """Check if ssh-agent is running and has keys loaded."""
        if not self.supports_agent():
            return False

        try:
            import paramiko
            agent = paramiko.Agent()
            return len(agent.get_keys()) > 0
        except Exception:
            return False

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
        Get a variable value.

        Note: Access to SECRET type variables is audit logged for security tracking.
        """
        if key in self._variables:
            value, var_type = self._variables[key]

            # Audit log secret access (security requirement)
            if var_type == VariableType.SECRET:
                logger.info(f"🔐 Secret accessed: {key} (type=SECRET)")

            return value
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
            # Use lambda to avoid backreference interpretation if value contains \1, \2, etc.
            # Note: Use default arg to capture value at definition time (not runtime)
            resolved = re.sub(f'@{re.escape(key)}(?![\\w\\-])', lambda m, v=value: v, resolved)

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
            from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
            repo = get_inventory_repository()

            for var in variables:
                # Try to find host in inventory
                host = repo.get_host_by_name(var)
                if host:
                    # Use hostname only (command-compatible, no parentheses that break shell)
                    replacement = host["hostname"]
                    ip = host.get("ip")
                    # Use lambda to avoid backreference interpretation
                    # Note: Use default arg to capture replacement at definition time
                    text = re.sub(f'@{re.escape(var)}(?![\\w\\-])', lambda m, r=replacement: r, text)
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
            from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
            repo = get_inventory_repository()
            hosts = repo.list_hosts()
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
