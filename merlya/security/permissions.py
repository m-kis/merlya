"""
Privilege elevation manager.

Detects sudo/doas/su capabilities and prepares elevated commands when needed.
Capabilities are cached in host metadata for persistence across sessions.

Priority order for elevation methods:
1. sudo NOPASSWD - Best: no password needed, standard on most systems
2. doas - Often configured without password on BSD systems
3. sudo with password - Common fallback
4. su - Last resort, requires root password

Passwords are stored in the system keyring (macOS Keychain, Linux Secret Service)
and referenced via @elevation:host:password tokens to prevent leakage.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from merlya.ssh.pool import SSHConnectionOptions

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.secrets.store import SecretStore

# Cache TTL for elevation capabilities (24 hours)
ELEVATION_CACHE_TTL = timedelta(hours=24)

# Elevation method priority (lower = better)
ELEVATION_PRIORITY = {
    "sudo": 1,  # NOPASSWD sudo - best
    "doas": 2,  # Often NOPASSWD on BSD
    "sudo_with_password": 3,  # Needs password
    "su": 4,  # Needs root password - last resort
}

_SUDO_PREFIX_RE = re.compile(
    r"^\s*sudo(?:"
    r"(?:\s+-(?:n|S|E|H|k|i|s)\b)"
    r"|(?:\s+-u\s+\S+)"
    r"|(?:\s+-p\s+\S+)"
    r")*\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_DOAS_PREFIX_RE = re.compile(
    r"^\s*doas(?:"
    r"(?:\s+-(?:n|s)\b)"
    r"|(?:\s+-u\s+\S+)"
    r")*\s+(?P<rest>.+)$",
    re.IGNORECASE,
)


@dataclass
class ElevationResult:
    """Result of preparing an elevated command."""

    command: str
    input_data: str | None
    method: str | None
    note: str | None = None
    needs_password: bool = False
    base_command: str | None = None
    password_ref: str | None = None  # @elevation:host:password reference


class PermissionManager:
    """Manage privilege elevation for SSH commands.

    Caches elevation consent per host for the session to avoid repeated prompts.
    Passwords are stored in the system keyring for security.

    Security features:
    - Passwords stored in keyring (not in memory)
    - Returns @secret references instead of raw passwords
    - Lock to prevent race conditions in capability detection
    """

    def __init__(self, ctx: SharedContext) -> None:
        self.ctx = ctx
        self._cache: dict[str, dict[str, Any]] = {}  # Capabilities cache
        self._declined_methods: dict[str, set[str]] = {}  # host -> declined methods
        self._consented_methods: dict[str, str] = {}  # host -> consented method
        self._detection_locks: dict[str, asyncio.Lock] = {}  # Per-host lock for detection
        self._locks_lock = asyncio.Lock()  # Protects _detection_locks dict creation

    @property
    def _secrets(self) -> SecretStore:
        """Get secret store from context."""
        return self.ctx.secrets

    def _password_key(self, host: str, method: str | None = None) -> str:
        """Get keyring key for elevation password.

        Args:
            host: Host name.
            method: Elevation method. If 'su', uses root password key.
        """
        if method == "su":
            return f"elevation:{host}:root:password"
        return f"elevation:{host}:password"

    async def _get_host_lock(self, host: str) -> asyncio.Lock:
        """Get or create a lock for a specific host (thread-safe)."""
        async with self._locks_lock:
            if host not in self._detection_locks:
                self._detection_locks[host] = asyncio.Lock()
            return self._detection_locks[host]

    def _get_cached_password(self, host: str) -> str | None:
        """Get elevation password from keyring.

        Args:
            host: Host name to look up.

        Returns:
            Password string if stored, None otherwise.
        """
        return self._secrets.get(self._password_key(host))

    async def detect_capabilities(self, host: str, force_refresh: bool = False) -> dict[str, Any]:
        """Detect elevation capabilities on a host.

        Capabilities are cached in three layers:
        1. In-memory cache (fastest, per-session)
        2. Host metadata in database (persistent, 24h TTL)
        3. Fresh detection via SSH (slowest, used on cache miss/expiry)

        Thread-safe: uses per-host lock to prevent duplicate SSH probes.

        Args:
            host: Host name from inventory.
            force_refresh: If True, bypass cache and re-detect.
        """
        # Get or create lock for this host atomically
        host_lock = await self._get_host_lock(host)

        async with host_lock:
            # Layer 1: In-memory cache (check inside lock)
            if not force_refresh and host in self._cache:
                logger.debug(f"🔍 Using in-memory cached capabilities for {host}")
                return self._cache[host]

            # Layer 2: Try to load from host metadata (persistent)
            if not force_refresh:
                cached = await self._load_cached_capabilities(host)
                if cached:
                    self._cache[host] = cached
                    logger.debug(f"🔍 Using persisted capabilities for {host}")
                    return cached

            # Layer 3: Fresh detection via SSH
            capabilities = await self._detect_capabilities_ssh(host)

            # Save to both caches
            self._cache[host] = capabilities
            await self._save_capabilities(host, capabilities)

            logger.info(
                "🔒 Permissions for {host}: user={user}, sudo={sudo}, method={method}",
                host=host,
                user=capabilities["user"],
                sudo="yes" if capabilities["has_sudo"] else "no",
                method=capabilities["elevation_method"] or "none",
            )
            return capabilities

    async def _load_cached_capabilities(self, host: str) -> dict[str, Any] | None:
        """Load cached capabilities from host metadata if not expired."""
        try:
            host_entry = await self.ctx.hosts.get_by_name(host)
            if not host_entry or not host_entry.metadata:
                return None

            elevation = host_entry.metadata.get("elevation")
            if not elevation:
                return None

            # Check TTL (timezone-aware)
            cached_at = elevation.get("cached_at")
            if cached_at:
                cached_time = datetime.fromisoformat(cached_at)
                # Handle legacy naive timestamps by assuming UTC
                if cached_time.tzinfo is None:
                    cached_time = cached_time.replace(tzinfo=UTC)
                if datetime.now(UTC) - cached_time > ELEVATION_CACHE_TTL:
                    logger.debug(f"🔒 Cached capabilities for {host} expired")
                    return None

            caps = elevation.get("capabilities")
            return cast("dict[str, Any] | None", caps)
        except Exception as e:
            logger.debug(f"Failed to load cached capabilities for {host}: {e}")
            return None

    async def _save_capabilities(self, host: str, capabilities: dict[str, Any]) -> None:
        """Save capabilities to host metadata for persistence."""
        try:
            host_entry = await self.ctx.hosts.get_by_name(host)
            if not host_entry:
                return

            # Update metadata with elevation info (use UTC for consistency)
            metadata = host_entry.metadata or {}
            metadata["elevation"] = {
                "capabilities": capabilities,
                "cached_at": datetime.now(UTC).isoformat(),
            }

            # Save to database
            await self.ctx.hosts.update_metadata(host_entry.id, metadata)
            logger.debug(f"🔒 Persisted elevation capabilities for {host}")
        except Exception as e:
            logger.debug(f"Failed to save capabilities for {host}: {e}")

    async def _detect_capabilities_ssh(self, host: str) -> dict[str, Any]:
        """Detect elevation capabilities via SSH probes.

        Detection order and priority:
        1. sudo NOPASSWD - Best option, no password needed
        2. doas NOPASSWD - Common on BSD, often configured passwordless
        3. sudo with password - Standard fallback
        4. su - Last resort, requires root password
        """
        capabilities: dict[str, Any] = {
            "user": "unknown",
            "is_root": False,
            "groups": [],
            "has_sudo": False,
            "sudo_nopasswd": False,
            "has_su": False,
            "has_doas": False,
            "doas_nopasswd": False,
            "has_privileged_group": False,
            "privileged_groups": [],
            "elevation_method": None,
            "available_methods": [],  # All available methods with priority
        }

        async def _run(cmd: str) -> tuple[bool, str]:
            try:
                result = await self._execute(host, cmd)
                return result.exit_code == 0, result.stdout.strip()  # type: ignore[attr-defined]
            except (TimeoutError, RuntimeError, OSError) as exc:
                logger.debug(f"Permission probe failed on {host}: {cmd} ({exc})")
                return False, ""

        # Get user info
        ok, user = await _run("whoami")
        if ok:
            capabilities["user"] = user
            capabilities["is_root"] = user == "root"

        # Already root? No elevation needed
        if capabilities["is_root"]:
            capabilities["elevation_method"] = "none"
            return capabilities

        ok, groups = await _run("groups")
        if ok and groups:
            capabilities["groups"] = groups.split()

        privileged = {"wheel", "admin", "sudo", "root"}
        group_set = set(capabilities["groups"])
        capabilities["has_privileged_group"] = bool(group_set & privileged)
        capabilities["privileged_groups"] = list(group_set & privileged)

        available: list[tuple[int, str, bool]] = []  # (priority, method, needs_password)

        # Check sudo
        ok, sudo_path = await _run("which sudo")
        if ok and sudo_path:
            capabilities["has_sudo"] = True
            ok, _ = await _run("sudo -n true")
            if ok:
                capabilities["sudo_nopasswd"] = True
                available.append((ELEVATION_PRIORITY["sudo"], "sudo", False))
            else:
                available.append(
                    (ELEVATION_PRIORITY["sudo_with_password"], "sudo_with_password", True)
                )

        # Check doas (test NOPASSWD)
        ok, doas_path = await _run("which doas")
        if ok and doas_path:
            capabilities["has_doas"] = True
            ok, _ = await _run("doas -n true 2>/dev/null")
            if ok:
                capabilities["doas_nopasswd"] = True
                available.append((ELEVATION_PRIORITY["doas"], "doas", False))
            else:
                # doas with password is similar priority to sudo with password
                available.append(
                    (ELEVATION_PRIORITY["sudo_with_password"], "doas_with_password", True)
                )

        # Check su (always needs password)
        ok, su_path = await _run("which su")
        if ok and su_path:
            capabilities["has_su"] = True
            available.append((ELEVATION_PRIORITY["su"], "su", True))

        # Sort by priority and pick best
        available.sort(key=lambda x: x[0])
        capabilities["available_methods"] = [
            {"method": m, "needs_password": p} for _, m, p in available
        ]

        if available:
            _, best_method, _ = available[0]
            capabilities["elevation_method"] = best_method

        return capabilities

    def requires_elevation(self, command: str) -> bool:
        """Heuristically determine if a command likely needs elevation."""
        root_cmds = [
            "journalctl",
            "dmesg",
            "systemctl",
            "service",
            "apt",
            "yum",
            "dnf",
            "pacman",
            "useradd",
            "userdel",
            "groupadd",
            "visudo",
            "iptables",
            "firewall-cmd",
            "ufw",
            "mount",
            "umount",
            "fdisk",
            "parted",
            "reboot",
            "shutdown",
            "halt",
            "poweroff",
        ]
        root_paths = ["/etc/", "/var/log/", "/root/", "/sys/", "/proc/sys/", "/usr/sbin/", "/sbin/"]
        protected_reads = [
            "/etc/shadow",
            "/etc/gshadow",
            "/etc/sudoers",
            "/var/log/auth.log",
            "/var/log/secure",
            "/var/log/syslog",
            "/var/log/kern.log",
        ]

        cmd_lower = command.lower()
        for root_cmd in root_cmds:
            if cmd_lower.startswith(root_cmd) or f" {root_cmd} " in cmd_lower:
                return True

        for path in root_paths:
            if path in command and any(
                op in command
                for op in [">", ">>", "tee", "mv", "cp", "rm", "mkdir", "touch", "chmod", "chown"]
            ):
                return True

        for p in protected_reads:
            if p in command and any(
                cmd_lower.startswith(f"{r} ") or f" {r} " in cmd_lower
                for r in ["cat", "tail", "head", "grep", "awk", "sed"]
            ):
                return True

        return False

    def _method_needs_password(self, method: str) -> bool:
        """Check if elevation method requires a password."""
        return method in {"sudo_with_password", "doas_with_password", "su"}

    async def prepare_command(
        self,
        host: str,
        command: str,
    ) -> ElevationResult:
        """
        Prepare an elevated command if needed.

        Logic:
        - If we already have a consented method for this host, use it
        - Otherwise, iterate through available_methods (sorted by priority):
          - Skip methods the user has already declined
          - Ask for consent on the first non-declined method
          - If declined, add to declined set and try next method
          - If all declined, return no elevation
        """
        caps = await self.detect_capabilities(host)
        if caps.get("is_root") or caps.get("elevation_method") == "none":
            return ElevationResult(
                command=command,
                input_data=None,
                method=None,
                note="already_root",
                base_command=command,
            )

        available = caps.get("available_methods", [])
        if not available:
            return ElevationResult(
                command=command,
                input_data=None,
                method=None,
                note="no_elevation_available",
            )

        # Check if we already have a consented method for this host
        if host in self._consented_methods:
            method = self._consented_methods[host]
            logger.debug(f"🔒 Using cached elevation method {method} for {host}")
            return await self._prepare_with_method(host, command, caps, method)

        # Get declined methods for this host
        declined = self._declined_methods.get(host, set())

        # Try each available method in priority order
        for method_info in available:
            method = method_info["method"]

            # Skip already declined methods
            if method in declined:
                logger.debug(f"🔒 Skipping declined method {method} for {host}")
                continue

            # Ask for consent
            confirm = await self.ctx.ui.prompt_confirm(
                f"🔒 Command may require elevation on {host}. Use {method}?",
                default=False,
            )

            if confirm:
                # User consented - save and use this method
                self._consented_methods[host] = method
                return await self._prepare_with_method(host, command, caps, method)

            # User declined - add to declined set and try next
            if host not in self._declined_methods:
                self._declined_methods[host] = set()
            self._declined_methods[host].add(method)
            logger.debug(f"🔒 User declined {method} for {host}, trying next...")

        # All methods declined
        return ElevationResult(
            command=command,
            input_data=None,
            method=None,
            note="all_methods_declined",
            base_command=command,
        )

    async def _prepare_with_method(
        self,
        host: str,
        command: str,
        caps: dict[str, Any],
        method: str,
    ) -> ElevationResult:
        """Prepare elevated command using a specific method."""
        # NOPASSWD methods - just use them
        if not self._method_needs_password(method):
            elevated_command, input_data = self._elevate_command(command, caps, method, None)
            return ElevationResult(
                command=elevated_command,
                input_data=input_data,
                method=method,
                note="nopasswd",
                needs_password=False,
                base_command=command,
            )

        # Password-requiring methods - use method-aware password key
        password_key = self._password_key(host, method)
        password = self._secrets.get(password_key)

        if password:
            elevated_command, input_data = self._elevate_command(command, caps, method, password)
            return ElevationResult(
                command=elevated_command,
                input_data=input_data,
                method=method,
                note="password_from_keyring",
                needs_password=False,
                base_command=command,
                password_ref=f"@{password_key}",
            )

        # No password in keyring - caller must prompt user
        return ElevationResult(
            command=command,
            input_data=None,
            method=method,
            note="password_needed",
            needs_password=True,
            base_command=command,
            password_ref=f"@{password_key}",
        )

    def store_password(self, host: str, password: str, method: str | None = None) -> str:
        """Store elevation password in keyring.

        Args:
            host: Host name.
            password: Password to store.
            method: Elevation method. If 'su', stores as root password.

        Returns:
            Secret reference (@elevation:host:password) for use in commands.
        """
        password_key = self._password_key(host, method)
        self._secrets.set(password_key, password)
        logger.debug(f"🔒 Stored elevation password for {host} ({method or 'user'}) in keyring")
        return f"@{password_key}"

    def cache_password(self, host: str, password: str, method: str | None = None) -> None:
        """Store elevation password (alias for store_password for compatibility)."""
        self.store_password(host, password, method)

    def clear_cache(self, host: str | None = None) -> None:
        """Clear cached consent and password for a host (or all hosts)."""
        if host:
            self._declined_methods.pop(host, None)
            self._consented_methods.pop(host, None)
            self._cache.pop(host, None)
            # Remove passwords from keyring (both user and root)
            self._secrets.remove(self._password_key(host))
            self._secrets.remove(self._password_key(host, "su"))
        else:
            self._declined_methods.clear()
            self._consented_methods.clear()
            self._cache.clear()
            # Remove all elevation passwords from keyring
            for key in self._secrets.list_names():
                if key.startswith("elevation:"):
                    self._secrets.remove(key)

    def elevate_command(
        self,
        command: str,
        capabilities: dict[str, Any],
        method: str,
        password: str | None = None,
        login_shell: bool = False,
    ) -> tuple[str, str | None]:
        """Prefix command with the chosen elevation method.

        Public wrapper for _elevate_command.

        Args:
            command: The command to elevate.
            capabilities: Host capabilities dict (must include 'is_root' key).
            method: Elevation method ('sudo', 'sudo_with_password', 'doas', 'doas_with_password', 'su').
            password: Optional password for methods that require it.
            login_shell: Use login shell for su (loads profile scripts).

        Returns:
            Tuple of (elevated_command, input_data).
        """
        return self._elevate_command(command, capabilities, method, password, login_shell)

    def _elevate_command(
        self,
        command: str,
        capabilities: dict[str, Any],
        method: str,
        password: str | None = None,
        login_shell: bool = False,
    ) -> tuple[str, str | None]:
        """Prefix command with the chosen elevation method.

        Args:
            command: Command to elevate.
            capabilities: Host capabilities dict.
            method: Elevation method (sudo, sudo_with_password, doas, doas_with_password, su).
            password: Password for methods that require it (None for NOPASSWD).
            login_shell: Use login shell for su (su - instead of su).

        Returns:
            Tuple of (elevated_command, stdin_input).
        """
        if capabilities.get("is_root"):
            return command, None

        # Normalize any pre-elevated command (e.g., LLM adds sudo/doas) to ensure
        # we can apply the selected method deterministically and avoid hanging
        # on interactive password prompts.
        m = _SUDO_PREFIX_RE.match(command)
        if m:
            command = m.group("rest")
        else:
            m = _DOAS_PREFIX_RE.match(command)
            if m:
                command = m.group("rest")

        if method == "sudo":
            # NOPASSWD sudo
            return f"sudo -n {command}", None

        if method == "sudo_with_password":
            if password:
                # -S reads password from stdin, -p '' disables prompt
                return f"sudo -S -p '' {command}", f"{password}\n"
            # Try without password first (might be NOPASSWD for this specific command)
            return f"sudo -n {command}", None

        if method == "doas":
            # NOPASSWD doas (common on OpenBSD)
            return f"doas {command}", None

        if method == "doas_with_password":
            if password:
                # doas reads the password from /dev/tty; the SSH layer must allocate a PTY
                # when providing stdin (see SSHPool._execute_once).
                escaped_cmd = command.replace("'", "'\"'\"'")
                return f"doas sh -c '{escaped_cmd}'", f"{password}\n"
            return f"doas {command}", None

        if method == "su":
            escaped = command.replace("'", "'\"'\"'")
            # su - creates a login shell (loads /etc/profile, ~/.profile etc.)
            # su -c just runs command in current environment
            su_cmd = "su -" if login_shell else "su"
            return f"{su_cmd} -c '{escaped}'", f"{password}\n" if password else None

        logger.warning(f"⚠️ Unknown elevation method {method}, running without elevation")
        return command, None

    async def _execute(self, host: str, command: str) -> object:
        """Execute a probe command using the shared SSH pool."""
        ssh_pool = await self.ctx.get_ssh_pool()
        options = SSHConnectionOptions(connect_timeout=10)
        return await ssh_pool.execute(host=host, command=command, timeout=10, options=options)
