import getpass
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class CredentialManager:
    """
    Manages credentials securely:
    - SSH: ssh-agent, ~/.ssh/config, key files
    - DB: Interactive prompts with getpass (never stored in plaintext)
    """

    def __init__(self):
        self.ssh_dir = Path.home() / ".ssh"
        self.ssh_config = self._parse_ssh_config()
        self.session_credentials: Dict[str, Tuple[str, str]] = {}  # In-memory only for session
        self.credential_variables: Dict[str, str] = {}  # User-defined credential variables (@mongo-user, etc.)

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
            # If parsing fails, just return empty config
            pass

        return config

    def get_user_for_host(self, host: str) -> str:
        """Get the SSH user for a host from config, or default to current user."""
        # Check SSH config
        if host in self.ssh_config and 'user' in self.ssh_config[host]:
            return self.ssh_config[host]['user']

        # Default to current system user
        return os.getenv('USER', 'root')

    def get_key_for_host(self, host: str) -> Optional[str]:
        """Get the SSH key for a specific host from config."""
        if host in self.ssh_config and 'identityfile' in self.ssh_config[host]:
            key_path = self.ssh_config[host]['identityfile']
            # Expand ~ if present
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
                    # Basic check: if it has a corresponding .pub or looks like a key
                    if (self.ssh_dir / (file.name + ".pub")).exists() or "id_" in file.name:
                        keys.append(str(file))
        return keys

    def get_default_key(self) -> Optional[str]:
        """Return the default SSH key (id_ed25519, id_rsa, etc.)."""
        # Order of preference (modern to legacy)
        defaults = ["id_ed25519", "id_ecdsa", "id_rsa", "id_dsa"]
        for name in defaults:
            key_path = self.ssh_dir / name
            if key_path.exists():
                return str(key_path)

        # If no default, return first available key
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

    # Database credential management
    def get_db_credentials(self, host: str, service: str = "mongodb",
                          username: Optional[str] = None,
                          password: Optional[str] = None) -> Tuple[str, str]:
        """
        Get database credentials securely.

        Priority:
        1. Explicit credentials passed as arguments (from user prompt)
        2. Environment variables (MONGODB_USER, MONGODB_PASS)
        3. Session cache (already prompted in this session)
        4. Interactive prompt with getpass (secure input)

        Args:
            host: Target host (for display/caching)
            service: Service name (mongodb, mysql, etc.)
            username: Optional explicit username (extracted from user prompt)
            password: Optional explicit password (extracted from user prompt)

        Returns:
            (username, password) tuple
        """
        cache_key = f"{service}@{host}"

        # Priority 1: Explicit credentials from user prompt
        if username and password:
            # Cache for session
            self.session_credentials[cache_key] = (username, password)
            return (username, password)

        # Priority 2: Session cache
        if cache_key in self.session_credentials:
            return self.session_credentials[cache_key]

        # Priority 3: Environment variables
        env_user_key = f"{service.upper()}_USER"
        env_pass_key = f"{service.upper()}_PASS"

        if env_user_key in os.environ and env_pass_key in os.environ:
            username = os.environ[env_user_key]
            password = os.environ[env_pass_key]
            # Cache for session
            self.session_credentials[cache_key] = (username, password)
            return (username, password)

        # Priority 4: Interactive prompt (secure)
        print(f"\n[Credentials needed for {service} on {host}]")
        username = input(f"{service} username: ")
        password = getpass.getpass(f"{service} password: ")

        # Cache for session only (not persisted)
        self.session_credentials[cache_key] = (username, password)

        return (username, password)

    def clear_session_credentials(self):
        """Clear cached credentials from session."""
        self.session_credentials.clear()

    # Credential variables management (@mongo-user, @mongo-pass, etc.)
    def set_variable(self, key: str, value: str):
        """
        Set a credential variable.

        Args:
            key: Variable name (e.g., "mongo-user", "db-pass")
            value: Variable value
        """
        self.credential_variables[key] = value

    def set_variable_secure(self, key: str) -> bool:
        """
        Set a credential variable securely using getpass (for passwords, API keys, tokens, SSH keys).

        Args:
            key: Variable name (e.g., "mongo-pass", "api-key", "ssh-key")

        Returns:
            True if set successfully, False if cancelled
        """
        try:
            print(f"\n[Secure input for '{key}']")
            value = getpass.getpass(f"{key}: ")
            if value:
                self.credential_variables[key] = value
                return True
            else:
                print("Empty value - not saved")
                return False
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled")
            return False

    def get_variable(self, key: str) -> Optional[str]:
        """Get a credential variable value."""
        return self.credential_variables.get(key)

    def delete_variable(self, key: str) -> bool:
        """Delete a credential variable. Returns True if deleted, False if not found."""
        if key in self.credential_variables:
            del self.credential_variables[key]
            return True
        return False

    def list_variables(self) -> Dict[str, str]:
        """List all credential variables."""
        return self.credential_variables.copy()

    def clear_variables(self):
        """Clear all credential variables."""
        self.credential_variables.clear()

    def has_db_credentials(self, host: str, service: str = "mongodb") -> bool:
        """Check if credentials are available without prompting."""
        cache_key = f"{service}@{host}"

        # Check session cache
        if cache_key in self.session_credentials:
            return True

        # Check environment variables
        env_user_key = f"{service.upper()}_USER"
        env_pass_key = f"{service.upper()}_PASS"

        return env_user_key in os.environ and env_pass_key in os.environ

    def resolve_variables(self, text: str, warn_missing: bool = True) -> str:
        """
        Resolve @variable references in text.

        Args:
            text: Text containing @variable references
            warn_missing: If True, warn about unresolved variables

        Returns:
            Text with variables replaced by their values

        Example:
            "using @mongo-user @mongo-pass" -> "using admin secret123"
        """
        resolved = text

        # Find all @variable references in the text
        variable_pattern = r'@([\w\-]+)'
        re.findall(variable_pattern, text)

        # Track which variables were not found

        for key, value in self.credential_variables.items():
            # Replace @key with value
            resolved = re.sub(f'@{re.escape(key)}\\b', value, resolved)

        # Check for unresolved variables (still have @ prefix after resolution)
        still_unresolved = re.findall(variable_pattern, resolved)
        if still_unresolved and warn_missing:
            from athena_ai.utils.logger import logger
            for var in still_unresolved:
                logger.warning(f"Variable @{var} referenced but not defined. Use '/credentials set {var} <value>' or '/credentials set-secret {var}' to define it.")

        return resolved

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

        Args:
            prompt: User's original prompt

        Returns:
            (username, password) tuple if found, None otherwise
        """
        # Pattern 1: "user <username> password <password>"
        pattern1 = r'(?:user|username)\s+(\S+)\s+(?:password|passwd|pass|pwd)\s+(\S+)'
        match = re.search(pattern1, prompt, re.IGNORECASE)
        if match:
            return (match.group(1), match.group(2))

        # Pattern 2: "credentials username/password" or "credentials username:password"
        pattern2 = r'(?:credentials?|creds?)\s+(\S+)[/:](\S+)'
        match = re.search(pattern2, prompt, re.IGNORECASE)
        if match:
            return (match.group(1), match.group(2))

        # Pattern 2b: "credential(s) username password" (space-separated)
        pattern2b = r'(?:credentials?|creds?)\s+(\S+)\s+(\S+)'
        match = re.search(pattern2b, prompt, re.IGNORECASE)
        if match:
            return (match.group(1), match.group(2))

        # Pattern 3: "using username:password"
        pattern3 = r'using\s+(\S+):(\S+)'
        match = re.search(pattern3, prompt, re.IGNORECASE)
        if match:
            return (match.group(1), match.group(2))

        # Pattern 4: "-u username -p password" (CLI style)
        pattern4 = r'-u\s+(\S+)\s+-p\s+(\S+)'
        match = re.search(pattern4, prompt)
        if match:
            return (match.group(1), match.group(2))

        # Pattern 5: "--username username --password password"
        pattern5 = r'--username\s+(\S+)\s+--password\s+(\S+)'
        match = re.search(pattern5, prompt)
        if match:
            return (match.group(1), match.group(2))

        return None
