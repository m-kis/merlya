"""
SSH Credential Management for Merlya.

Handles SSH key resolution, passphrase management, and ssh-agent integration.
This module is used by both the CredentialManager and SSH executors.

Key Resolution Priority:
1. Host-specific key from inventory metadata (ssh_key_path)
2. Global key (ssh_key_global variable)
3. ~/.ssh/config IdentityFile for host
4. Default keys (id_ed25519, id_rsa, etc.)

Passphrase Management:
- Stored in memory only (VariableType.SECRET)
- Prompted on first use
- Cached per-key for session duration
- Naming convention: ssh-passphrase-<key_filename>

Security:
- Path traversal protection for SSH key paths
- Hostname/IP validation
- File permission validation (0600/0400 for private keys)
- Sanitized logging (no sensitive paths exposed)
"""
import getpass
import os
import re
import stat
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from merlya.utils.logger import logger

if TYPE_CHECKING:
    pass

# Allowed directories for SSH keys (resolved to absolute paths)
_ALLOWED_SSH_KEY_DIRS: Optional[List[Path]] = None

# Valid hostname pattern (RFC 1123 compliant + wildcards for SSH config)
# Supports patterns like: server1, web-prod-01, *.example.com, web-*, *-prod
_HOSTNAME_PATTERN = re.compile(
    r'^(?:'
    r'\*|'  # Single wildcard
    r'[a-zA-Z0-9*](?:[a-zA-Z0-9\-*]{0,61}[a-zA-Z0-9*])?'  # Label with wildcards
    r')'
    r'(?:\.(?:\*|[a-zA-Z0-9*](?:[a-zA-Z0-9\-*]{0,61}[a-zA-Z0-9*])?))*$'
)

# Valid IPv4 pattern
_IPV4_PATTERN = re.compile(
    r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
)

# Valid IPv6 pattern (simplified - covers most common formats)
_IPV6_PATTERN = re.compile(
    r'^(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$|'
    r'^(?:[0-9a-fA-F]{1,4}:){1,7}:$|'
    r'^(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}$|'
    r'^::(?:[0-9a-fA-F]{1,4}:){0,5}[0-9a-fA-F]{1,4}$|'
    r'^[0-9a-fA-F]{1,4}::(?:[0-9a-fA-F]{1,4}:){0,4}[0-9a-fA-F]{1,4}$'
)


def _get_allowed_ssh_dirs() -> List[Path]:
    """Get list of allowed directories for SSH keys (lazy initialization)."""
    global _ALLOWED_SSH_KEY_DIRS
    if _ALLOWED_SSH_KEY_DIRS is None:
        home = Path.home()
        _ALLOWED_SSH_KEY_DIRS = [
            (home / ".ssh").resolve(),
            Path("/etc/ssh").resolve(),
        ]
        # Add any custom SSH dir from environment
        custom_ssh_dir = os.environ.get("MERLYA_SSH_KEY_DIR")
        if custom_ssh_dir:
            custom_path = Path(custom_ssh_dir).resolve()
            if custom_path.exists() and custom_path.is_dir():
                _ALLOWED_SSH_KEY_DIRS.append(custom_path)
    return _ALLOWED_SSH_KEY_DIRS


def validate_ssh_key_path(key_path: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate an SSH key path for security.

    Checks:
    - Path exists and is a file
    - Path is within allowed directories (no path traversal)
    - File permissions are secure (0600 or 0400)

    Args:
        key_path: Path to validate

    Returns:
        Tuple of (is_valid, resolved_path, error_message)
    """
    try:
        # Expand and resolve to absolute path
        path = Path(key_path).expanduser().resolve()

        # Check existence
        if not path.exists():
            return False, None, "Key file does not exist"

        if not path.is_file():
            return False, None, "Path is not a file"

        # Check path traversal - must be within allowed directories
        allowed_dirs = _get_allowed_ssh_dirs()
        is_allowed = any(
            path == allowed_dir or allowed_dir in path.parents
            for allowed_dir in allowed_dirs
        )

        if not is_allowed:
            logger.warning("SSH key path rejected: outside allowed directories")
            return False, None, "Key path outside allowed directories"

        # Check file permissions (should be 0600 or 0400)
        mode = path.stat().st_mode
        file_perms = stat.S_IMODE(mode)

        # Allow 0600 (owner read/write) or 0400 (owner read only)
        secure_perms = [0o600, 0o400]
        if file_perms not in secure_perms:
            logger.warning(
                f"SSH key has insecure permissions: {oct(file_perms)} "
                f"(expected 0600 or 0400)"
            )
            # Warning but don't reject - user may have reasons

        return True, str(path), None

    except PermissionError:
        return False, None, "Permission denied accessing key file"
    except OSError as e:
        return False, None, f"OS error: {e.strerror}"


def validate_hostname(hostname: str) -> bool:
    """
    Validate a hostname or IP address.

    Args:
        hostname: Hostname or IP to validate

    Returns:
        True if valid, False otherwise
    """
    if not hostname or len(hostname) > 253:
        return False

    # Check if it's a valid IPv4
    if _IPV4_PATTERN.match(hostname):
        return True

    # Check if it's a valid IPv6
    if _IPV6_PATTERN.match(hostname):
        return True

    # Check if it's a valid hostname
    if _HOSTNAME_PATTERN.match(hostname):
        return True

    return False


def sanitize_path_for_log(path: str) -> str:
    """
    Sanitize a path for logging (hide sensitive directory structure).

    Args:
        path: Full path

    Returns:
        Sanitized path showing only filename
    """
    try:
        return Path(path).name
    except Exception:
        return "<path>"


def check_key_needs_passphrase(key_path: str, skip_validation: bool = False) -> bool:
    """
    Check if an SSH key requires a passphrase.

    This is the canonical function for passphrase detection.
    Use this instead of duplicating the logic elsewhere.

    Args:
        key_path: Path to the SSH key file
        skip_validation: If True, skip path security validation (use for already-validated paths)

    Returns:
        True if key is encrypted and needs passphrase, False otherwise

    Example:
        # With validation (default - recommended for untrusted input)
        needs_pass = check_key_needs_passphrase("~/.ssh/id_ed25519")

        # Without validation (for paths already validated or from trusted sources)
        needs_pass = check_key_needs_passphrase("/path/to/key", skip_validation=True)
    """
    # Validate path first unless skipped
    if not skip_validation:
        is_valid, resolved_path, error = validate_ssh_key_path(key_path)
        if not is_valid or not resolved_path:
            logger.debug(f"Key path validation failed: {error or 'unknown'}")
            return False
        key_path = resolved_path

    # Use paramiko directly to check encryption status
    try:
        import paramiko

        # Try key types in order of commonality
        # Note: DSSKey may not exist in newer paramiko versions
        key_classes = [
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
        ]
        if hasattr(paramiko, 'DSSKey'):
            key_classes.append(paramiko.DSSKey)

        for key_class in key_classes:
            try:
                key_class.from_private_key_file(key_path, password=None)
                return False  # Loaded without passphrase
            except paramiko.ssh_exception.PasswordRequiredException:
                return True  # Needs passphrase
            except paramiko.ssh_exception.SSHException:
                # Wrong key type, try next
                continue
            except FileNotFoundError:
                logger.debug("Key file not found during passphrase check")
                return False
            except PermissionError:
                logger.debug("Permission denied reading key file")
                return False

        # If no key class worked, assume no passphrase needed
        return False

    except ImportError:
        # Paramiko not available, fall back to file content check
        try:
            with open(key_path, 'r') as f:
                content = f.read(4096)  # Only read first 4KB for header
                if "ENCRYPTED" in content:
                    return True
                if "Proc-Type: 4,ENCRYPTED" in content:
                    return True
            return False
        except (OSError, IOError) as e:
            logger.debug(f"Could not read key file: {type(e).__name__}")
            return False


def validate_passphrase_for_key(key_path: str, passphrase: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a passphrase correctly unlocks an SSH private key.

    This function attempts to load the key with the provided passphrase
    to verify it's correct before storing it.

    Args:
        key_path: Path to the SSH key file
        passphrase: Passphrase to test

    Returns:
        Tuple of (is_valid, error_message)
        - (True, None) if passphrase is correct
        - (False, error_message) if passphrase is wrong or other error

    Example:
        is_valid, error = validate_passphrase_for_key("~/.ssh/id_ed25519", "mypass")
        if is_valid:
            print("Passphrase correct!")
        else:
            print(f"Invalid: {error}")
    """
    # CRITICAL: Validate path security first - prevents access to system keys
    is_path_valid, resolved_path, path_error = validate_ssh_key_path(key_path)
    if not is_path_valid or not resolved_path:
        return False, path_error or "Invalid key path"

    try:
        import paramiko

        # Try key types in order of commonality
        # RSA first (most common in legacy systems), then Ed25519 (modern), ECDSA
        # Note: DSSKey may not exist in newer paramiko versions
        key_classes = [
            paramiko.RSAKey,
            paramiko.Ed25519Key,
            paramiko.ECDSAKey,
        ]
        if hasattr(paramiko, 'DSSKey'):
            key_classes.append(paramiko.DSSKey)

        last_error = None
        for key_class in key_classes:
            try:
                # Try to load key with passphrase
                key_class.from_private_key_file(resolved_path, password=passphrase)
                logger.debug(f"✅ Passphrase validated for key: {Path(key_path).name}")
                return True, None
            except paramiko.ssh_exception.PasswordRequiredException:
                # Key is encrypted but passphrase not provided or empty
                return False, "Key requires a passphrase but none was provided"
            except paramiko.ssh_exception.SSHException as e:
                error_str = str(e).lower()
                # Check for wrong passphrase indicators
                if "incorrect" in error_str or "decrypt" in error_str or "bad" in error_str:
                    return False, "Incorrect passphrase"
                # Wrong key type indicators - try next class
                # "encountered RSA key" means Ed25519Key saw RSA format
                # "not a valid" means generic wrong type
                # "expected OPENSSH" means wrong format for this key class
                if any(x in error_str for x in ["not a valid", "encountered", "expected"]):
                    last_error = str(e)
                    continue
                # Other SSH error - might be passphrase related
                last_error = str(e)
                continue
            except FileNotFoundError:
                return False, "Key file not found"
            except PermissionError:
                return False, "Permission denied reading key file"
            except Exception as e:
                # Catch other errors (e.g., binascii.Error for corrupt keys)
                last_error = f"{type(e).__name__}: {e}"
                continue

        # If we tried all key classes without success
        if last_error:
            return False, f"Could not load key: {last_error}"
        return False, "Unrecognized key format"

    except ImportError:
        return False, "paramiko not installed - cannot validate passphrase"
    except Exception as e:
        logger.debug(f"Passphrase validation error: {type(e).__name__}")
        return False, f"Validation error: {type(e).__name__}"


class SSHCredentialMixin:
    """
    Mixin providing SSH credential management functionality.

    This mixin is designed to be used with CredentialManager and provides:
    - SSH config parsing (~/.ssh/config)
    - Key discovery and resolution
    - Passphrase caching and prompting
    - ssh-agent integration
    """

    # These attributes must be provided by the class using this mixin
    ssh_dir: Path
    ssh_config: Dict[str, Dict[str, str]]
    _variables: Dict[str, Any]
    get_variable: Callable[[str], Optional[str]]
    set_variable: Callable[..., None]

    def _parse_ssh_config(self) -> Dict[str, Dict[str, str]]:
        """Parse ~/.ssh/config for host-specific settings."""
        config_file = self.ssh_dir / "config"
        config: Dict[str, Dict[str, str]] = {}

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
        if not validate_hostname(host):
            logger.debug("Invalid hostname format, skipping SSH config lookup")
            return None

        if host in self.ssh_config and 'identityfile' in self.ssh_config[host]:
            key_path = self.ssh_config[host]['identityfile']
            key_path = os.path.expanduser(key_path)
            # Validate path security
            is_valid, resolved, error = validate_ssh_key_path(key_path)
            if is_valid and resolved:
                return resolved
            elif error:
                logger.debug(f"SSH key validation failed: {error}")
        return None

    def get_ssh_keys(self) -> List[str]:
        """Retrieve available SSH private keys from ~/.ssh."""
        keys = []
        if self.ssh_dir.exists():
            for file in self.ssh_dir.iterdir():
                if file.is_file() and not file.name.endswith(".pub"):
                    if "known_hosts" not in file.name and "config" not in file.name:
                        if (self.ssh_dir / (file.name + ".pub")).exists() or "id_" in file.name:
                            keys.append(str(file))
        return keys

    def get_default_key(self) -> Optional[str]:
        """Return the default SSH key (global setting > id_ed25519 > id_rsa)."""
        # Check global setting first
        global_key = self.get_variable("ssh_key_global")
        if global_key:
            is_valid, resolved, error = validate_ssh_key_path(global_key)
            if is_valid and resolved:
                return resolved
            elif error:
                logger.debug(f"Global key validation failed: {error}")

        defaults = ["id_ed25519", "id_ecdsa", "id_rsa", "id_dsa"]
        for name in defaults:
            key_path = self.ssh_dir / name
            if key_path.exists():
                # Keys in ~/.ssh are implicitly allowed
                return str(key_path.resolve())

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

    def get_passphrase_for_key(
        self,
        key_path: str,
        secret_key: Optional[str] = None,
        prompt_if_missing: bool = True,
    ) -> Optional[str]:
        """
        Get passphrase for an SSH key.

        Priority:
        1. Stored secret (if secret_key provided)
        2. Generic secret based on key filename (ssh-passphrase-<filename>)
        3. Interactive prompt (if prompt_if_missing=True)

        Args:
            key_path: Path to the SSH key file
            secret_key: Optional specific secret variable name
            prompt_if_missing: If True, prompt user for passphrase when not cached

        Returns:
            Passphrase string or None
        """
        from merlya.security.credentials import VariableType

        filename = Path(key_path).name

        # 1. Try specific secret key first
        if secret_key:
            passphrase = self.get_variable(secret_key)
            if passphrase:
                logger.debug("Using cached passphrase from specific secret")
                return passphrase

        # 2. Try generic secret based on filename
        generic_secret = f"ssh-passphrase-{filename}"
        passphrase = self.get_variable(generic_secret)
        if passphrase:
            logger.debug("Using cached passphrase from generic secret")
            return passphrase

        # 3. Try global passphrase if using global key
        global_key = self.get_variable("ssh_key_global")
        if global_key and os.path.expanduser(global_key) == os.path.expanduser(key_path):
            passphrase = self.get_variable("ssh-passphrase-global")
            if passphrase:
                logger.debug("Using cached global passphrase")
                return passphrase

        # 4. Interactive prompt if allowed
        if not prompt_if_missing:
            return None

        try:
            print(f"\n🔐 Passphrase required for SSH key: {filename}")
            passphrase = getpass.getpass("Enter passphrase: ")
            if passphrase:
                # Ask to cache for session
                try:
                    save = input("Cache passphrase for this session? (Y/n): ").strip().lower()
                    if save != "n":
                        self.set_variable(generic_secret, passphrase, VariableType.SECRET)
                        logger.info("Passphrase cached for session")
                        print("✅ Passphrase cached (memory only, expires on exit)")
                except (KeyboardInterrupt, EOFError):
                    pass
                return passphrase
        except (KeyboardInterrupt, EOFError):
            print("\n⚠️ Cancelled")

        return None

    def resolve_ssh_for_host(
        self,
        hostname: str,
        prompt_passphrase: bool = True,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Resolve SSH key and passphrase for a host.

        Resolution priority for key:
        1. Host-specific key from inventory metadata (ssh_key_path)
        2. Global key (ssh_key_global variable)
        3. ~/.ssh/config IdentityFile for host
        4. Default keys (id_ed25519, id_rsa, etc.)

        Resolution priority for passphrase:
        1. Host-specific secret from inventory metadata (ssh_passphrase_secret)
        2. Generic secret based on key filename (ssh-passphrase-<filename>)
        3. Global passphrase if using global key (ssh-passphrase-global)
        4. Interactive prompt (if prompt_passphrase=True and key needs it)

        Args:
            hostname: Target hostname
            prompt_passphrase: If True, prompt for passphrase when needed

        Returns:
            Tuple of (key_path, passphrase, source) where source is one of:
            'host', 'global', 'ssh_config', 'default', or None
        """
        key_path = None
        passphrase = None
        passphrase_secret = None
        source = None

        # Validate hostname first
        if not validate_hostname(hostname):
            logger.warning("Invalid hostname format provided")
            return None, None, None

        # 1. Check host-specific key from inventory metadata
        try:
            from merlya.memory.persistence.inventory_repository import (
                get_inventory_repository,
            )
            repo = get_inventory_repository()
            host = repo.get_host_by_name(hostname)
            if host:
                metadata = host.get("metadata", {}) or {}
                host_key = metadata.get("ssh_key_path")
                if host_key:
                    is_valid, resolved, error = validate_ssh_key_path(host_key)
                    if is_valid and resolved:
                        key_path = resolved
                        passphrase_secret = metadata.get("ssh_passphrase_secret")
                        source = "host"
                        logger.debug(f"Using host-specific key: {sanitize_path_for_log(key_path)}")
                    elif error:
                        logger.debug(f"Host key validation failed: {error}")
        except ImportError:
            logger.debug("Inventory repository not available")
        except Exception as e:
            logger.debug(f"Could not check inventory: {type(e).__name__}")

        # 2. Check global key
        if not key_path:
            global_key = self.get_variable("ssh_key_global")
            if global_key:
                is_valid, resolved, error = validate_ssh_key_path(global_key)
                if is_valid and resolved:
                    key_path = resolved
                    passphrase_secret = "ssh-passphrase-global"
                    source = "global"
                    logger.debug(f"Using global key: {sanitize_path_for_log(key_path)}")
                elif error:
                    logger.debug(f"Global key validation failed: {error}")

        # 3. Check ~/.ssh/config
        if not key_path:
            config_key = self.get_key_for_host(hostname)
            if config_key:
                key_path = config_key
                source = "ssh_config"
                logger.debug(f"Using key from SSH config: {sanitize_path_for_log(key_path)}")

        # 4. Default keys
        if not key_path:
            default_key = self.get_default_key()
            if default_key:
                key_path = default_key
                source = "default"
                logger.debug(f"Using default key: {sanitize_path_for_log(key_path)}")

        # Resolve passphrase if we have a key
        if key_path:
            # Check if key needs passphrase
            if self._key_needs_passphrase(key_path):
                passphrase = self.get_passphrase_for_key(
                    key_path,
                    secret_key=passphrase_secret,
                    prompt_if_missing=prompt_passphrase,
                )
            else:
                logger.debug(f"Key {sanitize_path_for_log(key_path)} does not require passphrase")

        return key_path, passphrase, source

    def _key_needs_passphrase(self, key_path: str) -> bool:
        """
        Check if an SSH key requires a passphrase.

        Uses paramiko for reliable detection, avoiding TOCTOU issues by
        letting paramiko handle file access directly.

        Args:
            key_path: Path to the SSH key file

        Returns:
            True if key is encrypted and needs passphrase
        """
        # Delegate to canonical function with validation enabled
        return check_key_needs_passphrase(key_path, skip_validation=False)
