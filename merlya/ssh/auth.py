"""
SSH Authentication Manager.

Provides intelligent SSH authentication handling:
- Agent detection and key management
- Automatic key loading with passphrase support
- Password authentication fallback
- MFA/2FA support via keyboard-interactive
"""

from __future__ import annotations

import asyncio
import os
import signal
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from loguru import logger

if TYPE_CHECKING:
    from merlya.secrets.store import SecretStore
    from merlya.ui.console import ConsoleUI


@dataclass
class AgentKeyInfo:
    """Information about a key in the SSH agent."""

    fingerprint: str
    key_type: str  # rsa, ed25519, ecdsa, etc.
    comment: str  # Usually the file path or email
    bits: int = 0


@dataclass
class SSHEnvironment:
    """Current SSH environment state."""

    agent_available: bool
    agent_socket: str | None
    agent_keys: list[AgentKeyInfo] = field(default_factory=list)
    managed_agent_pid: int | None = None


@dataclass
class SSHAuthOptions:
    """Authentication options for asyncssh.connect()."""

    preferred_auth: str = "publickey,keyboard-interactive"
    client_keys: list[Any] | None = None
    password: str | None = None
    agent_path: str | None = None
    passphrase: str | None = None  # For direct key loading


async def detect_ssh_environment() -> SSHEnvironment:
    """Detect the current SSH environment state."""
    agent_sock = os.environ.get("SSH_AUTH_SOCK")

    if not agent_sock:
        logger.debug("No SSH_AUTH_SOCK environment variable")
        return SSHEnvironment(agent_available=False, agent_socket=None)

    sock_path = Path(agent_sock)
    if not sock_path.exists():
        logger.debug(f"SSH agent socket does not exist: {agent_sock}")
        return SSHEnvironment(agent_available=False, agent_socket=None)

    # List keys in the agent
    keys = await _list_agent_keys()

    return SSHEnvironment(
        agent_available=True,
        agent_socket=agent_sock,
        agent_keys=keys,
    )


async def _list_agent_keys() -> list[AgentKeyInfo]:
    """List keys currently loaded in the SSH agent."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh-add",
            "-l",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            # Return code 1 means "no identities" which is not an error
            if b"no identities" in stderr.lower() or proc.returncode == 1:
                logger.debug("No keys in SSH agent")
                return []
            logger.warning(f"ssh-add -l failed: {stderr.decode()}")
            return []

        keys = []
        for line in stdout.decode().strip().split("\n"):
            if not line:
                continue
            # Format: "4096 SHA256:xxx comment (RSA)"
            parts = line.split()
            if len(parts) >= 4:
                key_type = parts[-1].strip("()").lower()
                keys.append(
                    AgentKeyInfo(
                        bits=int(parts[0]) if parts[0].isdigit() else 0,
                        fingerprint=parts[1],
                        comment=" ".join(parts[2:-1]),
                        key_type=key_type,
                    )
                )

        logger.debug(f"Found {len(keys)} keys in SSH agent")
        return keys

    except FileNotFoundError:
        logger.warning("ssh-add command not found")
        return []
    except Exception as e:
        logger.warning(f"Failed to list agent keys: {e}")
        return []


def key_in_agent(key_path: str | Path, agent_keys: list[AgentKeyInfo]) -> bool:
    """Check if a key is already loaded in the agent."""
    key_path = Path(key_path).expanduser()
    key_name = key_path.name
    key_str = str(key_path)

    for key in agent_keys:
        # Check if the key comment contains the path or filename
        if key_name in key.comment or key_str in key.comment:
            return True

    return False


class ManagedSSHAgent:
    """SSH agent managed by Merlya."""

    _instance: ClassVar[ManagedSSHAgent | None] = None
    _lock: ClassVar[asyncio.Lock]

    def __init__(self) -> None:
        self.agent_pid: int | None = None
        self.agent_sock: str | None = None
        self._original_sock: str | None = None
        self._original_pid: str | None = None

    @classmethod
    async def get_instance(cls) -> ManagedSSHAgent:
        """Get singleton instance."""
        if not hasattr(cls, "_lock"):
            cls._lock = asyncio.Lock()

        async with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    async def ensure_agent_running(self) -> bool:
        """Ensure an SSH agent is available, starting one if needed."""
        env = await detect_ssh_environment()

        if env.agent_available:
            logger.debug("Using existing SSH agent")
            self.agent_sock = env.agent_socket
            return True

        logger.info("No SSH agent found, starting managed agent...")
        return await self._start_agent()

    async def _start_agent(self) -> bool:
        """Start a new SSH agent."""
        try:
            # Save original environment
            self._original_sock = os.environ.get("SSH_AUTH_SOCK")
            self._original_pid = os.environ.get("SSH_AGENT_PID")

            proc = await asyncio.create_subprocess_exec(
                "ssh-agent",
                "-s",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Failed to start SSH agent: {stderr.decode()}")
                return False

            # Parse output: SSH_AUTH_SOCK=/tmp/...; export SSH_AUTH_SOCK;
            output = stdout.decode()
            for part in output.replace("\n", ";").split(";"):
                part = part.strip()
                if part.startswith("SSH_AUTH_SOCK="):
                    self.agent_sock = part.split("=", 1)[1]
                    os.environ["SSH_AUTH_SOCK"] = self.agent_sock
                elif part.startswith("SSH_AGENT_PID="):
                    self.agent_pid = int(part.split("=", 1)[1])
                    os.environ["SSH_AGENT_PID"] = str(self.agent_pid)

            logger.info(f"Started SSH agent (PID: {self.agent_pid}, socket: {self.agent_sock})")
            return True

        except FileNotFoundError:
            logger.error("ssh-agent command not found")
            return False
        except Exception as e:
            logger.error(f"Failed to start SSH agent: {e}")
            return False

    async def add_key(self, key_path: str, passphrase: str | None = None) -> bool:
        """Add a key to the SSH agent."""
        key_path_expanded = str(Path(key_path).expanduser())

        if not Path(key_path_expanded).exists():
            logger.error(f"Key file not found: {key_path_expanded}")
            return False

        if passphrase:
            return await self._add_key_with_passphrase(key_path_expanded, passphrase)
        else:
            return await self._add_key_direct(key_path_expanded)

    async def _add_key_direct(self, key_path: str) -> bool:
        """Add an unencrypted key to the agent."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "ssh-add",
                key_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                stderr_text = stderr.decode().lower()
                if "passphrase" in stderr_text or "encrypted" in stderr_text:
                    logger.debug(f"Key {key_path} requires passphrase")
                    return False
                logger.error(f"Failed to add key: {stderr.decode()}")
                return False

            logger.info(f"Added key to agent: {key_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to add key: {e}")
            return False

    async def _add_key_with_passphrase(self, key_path: str, passphrase: str) -> bool:
        """Add an encrypted key to the agent using SSH_ASKPASS."""
        askpass_script = None
        try:
            # Create temporary askpass script
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False, prefix="merlya_askpass_"
            ) as f:
                # Use printf to avoid issues with special characters
                f.write("#!/bin/sh\n")
                f.write(f'printf "%s" "{passphrase}"\n')
                askpass_script = f.name

            os.chmod(askpass_script, 0o700)

            # Setup environment for SSH_ASKPASS
            env = os.environ.copy()
            env["SSH_ASKPASS"] = askpass_script
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env["DISPLAY"] = os.environ.get("DISPLAY", ":0")

            proc = await asyncio.create_subprocess_exec(
                "ssh-add",
                key_path,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(f"Failed to add encrypted key: {stderr.decode()}")
                return False

            logger.info(f"Added encrypted key to agent: {key_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to add key with passphrase: {e}")
            return False
        finally:
            # Clean up askpass script
            if askpass_script:
                try:
                    Path(askpass_script).unlink(missing_ok=True)
                except Exception:
                    pass

    async def cleanup(self) -> None:
        """Stop the managed agent if we started it."""
        if self.agent_pid:
            try:
                os.kill(self.agent_pid, signal.SIGTERM)
                logger.info(f"Stopped managed SSH agent (PID: {self.agent_pid})")
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning(f"Failed to stop SSH agent: {e}")

            # Restore original environment
            if self._original_sock:
                os.environ["SSH_AUTH_SOCK"] = self._original_sock
            elif "SSH_AUTH_SOCK" in os.environ:
                del os.environ["SSH_AUTH_SOCK"]

            if self._original_pid:
                os.environ["SSH_AGENT_PID"] = self._original_pid
            elif "SSH_AGENT_PID" in os.environ:
                del os.environ["SSH_AGENT_PID"]

            self.agent_pid = None
            self.agent_sock = None


class SSHAuthManager:
    """Intelligent SSH authentication manager."""

    def __init__(self, secrets: SecretStore, ui: ConsoleUI) -> None:
        self.secrets = secrets
        self.ui = ui
        self._managed_agent: ManagedSSHAgent | None = None
        self._mfa_callback: Callable[[str], str] | None = None

    def set_mfa_callback(self, callback: Callable[[str], str]) -> None:
        """Set callback for MFA/keyboard-interactive prompts."""
        self._mfa_callback = callback

    async def prepare_auth(
        self,
        hostname: str,
        username: str | None,
        private_key: str | None,
        host_name: str | None = None,  # Inventory name for credential lookup
    ) -> SSHAuthOptions:
        """Prepare authentication options for a connection."""
        options = SSHAuthOptions()
        host_id = host_name or hostname

        # Case 1: Private key configured
        if private_key:
            await self._prepare_key_auth(private_key, host_id, options)
            return options

        # Case 2: Check if SSH agent is available
        env = await detect_ssh_environment()
        if env.agent_available:
            # Use agent even if no keys listed - asyncssh can still try
            key_count = len(env.agent_keys) if env.agent_keys else 0
            if key_count > 0:
                logger.info(f"Using SSH agent with {key_count} key(s)")
            else:
                logger.info("Using SSH agent (no keys listed but socket available)")
            options.agent_path = env.agent_socket
            # Don't set client_keys - let asyncssh use the agent
            return options

        # Case 3: Check for stored password
        if await self._has_stored_password(host_id):
            await self._prepare_password_auth(host_id, username, hostname, options)
            return options

        # Case 4: No auth configured - ask user
        auth_method = await self._prompt_auth_method(hostname, username)

        if auth_method == "key":
            key_path = await self._prompt_key_path()
            if key_path:
                await self._prepare_key_auth(key_path, host_id, options)
            else:
                # User didn't provide key path - try agent as fallback
                logger.debug("No key path provided, trying agent as fallback")
                options.agent_path = os.environ.get("SSH_AUTH_SOCK")
        else:
            await self._prepare_password_auth(host_id, username, hostname, options)

        return options

    async def _prepare_key_auth(
        self, key_path: str, host_id: str, options: SSHAuthOptions
    ) -> None:
        """Prepare key-based authentication."""
        key_path_obj = Path(key_path).expanduser()

        if not key_path_obj.exists():
            logger.warning(f"Private key not found: {key_path}")
            return

        # Get passphrase if needed (from cache or prompt)
        passphrase = await self._get_passphrase(key_path_obj, host_id)

        # Always load key directly for MFA compatibility
        # Note: Using agent_path with asyncssh doesn't properly trigger
        # keyboard-interactive callbacks after publickey partial success
        logger.info(f"Loading key for auth: {key_path_obj.name}")
        await self._load_key_directly(key_path_obj, passphrase, options)

    async def _load_key_directly(
        self, key_path: Path, passphrase: str | None, options: SSHAuthOptions
    ) -> None:
        """Load a key directly for asyncssh (fallback when agent unavailable)."""
        try:
            import asyncssh

            key = asyncssh.read_private_key(str(key_path), passphrase)
            options.client_keys = [key]
            logger.debug(f"Loaded key directly: {key_path}")
        except Exception as e:
            logger.error(f"Failed to load key {key_path}: {e}")

    async def _get_passphrase(self, key_path: Path, host_id: str) -> str | None:
        """Get passphrase for a key (from cache or prompt)."""
        # Check if key needs passphrase
        if not self._key_is_encrypted(key_path):
            return None

        # Try cache with multiple keys
        cache_keys = [
            f"ssh:passphrase:{host_id}",
            f"ssh:passphrase:{key_path.name}",
            f"ssh:passphrase:{key_path}",
        ]

        for cache_key in cache_keys:
            passphrase = self.secrets.get(cache_key)
            if passphrase:
                logger.debug(f"Found cached passphrase for {key_path.name}")
                return passphrase

        # Prompt user
        passphrase = await self.ui.prompt_secret(f"Passphrase for {key_path}")

        if passphrase:
            # Cache for future use
            for cache_key in cache_keys:
                try:
                    self.secrets.set(cache_key, passphrase)
                except Exception as e:
                    logger.debug(f"Failed to cache passphrase: {e}")
            logger.debug("Passphrase cached successfully")

        return passphrase

    def _key_is_encrypted(self, key_path: Path) -> bool:
        """Check if a private key is encrypted."""
        try:
            import asyncssh

            asyncssh.read_private_key(str(key_path))
            return False
        except Exception:
            # Any error likely means encrypted or invalid
            return True

    async def _prepare_password_auth(
        self, host_id: str, username: str | None, hostname: str, options: SSHAuthOptions
    ) -> None:
        """Prepare password-based authentication."""
        cache_key = f"ssh:password:{host_id}"
        password = self.secrets.get(cache_key)

        if not password:
            user_display = f"{username}@" if username else ""
            password = await self.ui.prompt_secret(f"Password for {user_display}{hostname}")

            if password:
                try:
                    self.secrets.set(cache_key, password)
                except Exception as e:
                    logger.debug(f"Failed to cache password: {e}")

        options.password = password
        options.preferred_auth = "password,keyboard-interactive"

    async def _has_stored_password(self, host_id: str) -> bool:
        """Check if a password is stored for this host."""
        return self.secrets.has(f"ssh:password:{host_id}")

    async def _prompt_auth_method(self, hostname: str, username: str | None) -> str:
        """Prompt user to choose authentication method."""
        user_display = f"{username}@" if username else ""
        self.ui.info(f"No authentication configured for {user_display}{hostname}")

        response = await self.ui.prompt(
            "Authentication method? [key/password]", default="key"
        )

        return "password" if response.lower().startswith("p") else "key"

    async def _prompt_key_path(self) -> str | None:
        """Prompt user for private key path."""
        default_keys = ["~/.ssh/id_ed25519", "~/.ssh/id_rsa"]

        # Find first existing default key
        default = None
        for key in default_keys:
            if Path(key).expanduser().exists():
                default = key
                break

        response = await self.ui.prompt("Private key path", default=default or "")

        if response:
            path = Path(response).expanduser()
            if path.exists():
                return str(path)
            self.ui.error(f"Key file not found: {response}")

        return None

    async def cleanup(self) -> None:
        """Cleanup resources (stop managed agent if any)."""
        if self._managed_agent:
            await self._managed_agent.cleanup()
