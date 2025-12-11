"""
Privilege elevation manager.

Detects sudo/doas/su capabilities and prepares elevated commands when needed.
Capabilities are cached in host metadata for persistence across sessions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger

from merlya.ssh.pool import SSHConnectionOptions

# Cache TTL for elevation capabilities (24 hours)
ELEVATION_CACHE_TTL = timedelta(hours=24)

# Password cache TTL (30 minutes for security)
PASSWORD_CACHE_TTL = timedelta(minutes=30)


@dataclass
class CachedPassword:
    """Password with expiration timestamp."""

    password: str
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC) + PASSWORD_CACHE_TTL)

    def is_expired(self) -> bool:
        """Check if the cached password has expired."""
        return datetime.now(UTC) > self.expires_at


@dataclass
class ElevationResult:
    """Result of preparing an elevated command."""

    command: str
    input_data: str | None
    method: str | None
    note: str | None = None
    needs_password: bool = False
    base_command: str | None = None


class PermissionManager:
    """Manage privilege elevation for SSH commands.

    Caches elevation consent and passwords per host for the session to avoid
    repeated prompts.

    Security features:
    - Password cache with TTL (30 min expiry)
    - Lock to prevent race conditions in capability detection
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._cache: dict[str, dict[str, Any]] = {}  # Capabilities cache
        self._consent_cache: dict[str, bool] = {}  # host -> user consented
        self._password_cache: dict[str, CachedPassword] = {}  # host -> password with TTL
        self._detection_locks: dict[str, asyncio.Lock] = {}  # Per-host lock for detection
        self._locks_lock = asyncio.Lock()  # Protects _detection_locks dict creation

    async def _get_host_lock(self, host: str) -> asyncio.Lock:
        """Get or create a lock for a specific host (thread-safe)."""
        async with self._locks_lock:
            if host not in self._detection_locks:
                self._detection_locks[host] = asyncio.Lock()
            return self._detection_locks[host]

    def _get_cached_password(self, host: str) -> str | None:
        """Get cached password if not expired, atomically cleaning up expired entries.

        Uses pop() for atomic cleanup to prevent race conditions between
        concurrent coroutines accessing the same password cache entry.

        Args:
            host: Host name to look up.

        Returns:
            Password string if cached and not expired, None otherwise.
        """
        cached_pwd = self._password_cache.get(host)
        if cached_pwd is None:
            return None
        if cached_pwd.is_expired():
            # Use pop for atomic cleanup (handles concurrent access safely)
            self._password_cache.pop(host, None)
            logger.debug(f"🔒 Password cache expired for {host}")
            return None
        return cached_pwd.password

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

            return elevation.get("capabilities")
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
        """Detect elevation capabilities via SSH probes."""
        capabilities: dict[str, Any] = {
            "user": "unknown",
            "is_root": False,
            "groups": [],
            "has_sudo": False,
            "sudo_nopasswd": False,
            "has_su": False,
            "has_doas": False,
            "has_privileged_group": False,
            "privileged_groups": [],
            "elevation_method": None,
        }

        async def _run(cmd: str) -> tuple[bool, str]:
            try:
                result = await self._execute(host, cmd)
                return result.exit_code == 0, result.stdout.strip()  # type: ignore[attr-defined]
            except (TimeoutError, RuntimeError, OSError) as exc:
                logger.debug(f"Permission probe failed on {host}: {cmd} ({exc})")
                return False, ""

        ok, user = await _run("whoami")
        if ok:
            capabilities["user"] = user
            capabilities["is_root"] = user == "root"

        ok, groups = await _run("groups")
        if ok and groups:
            capabilities["groups"] = groups.split()

        privileged = {"wheel", "admin", "sudo", "root"}
        group_set = set(capabilities["groups"])
        capabilities["has_privileged_group"] = bool(group_set & privileged)
        capabilities["privileged_groups"] = list(group_set & privileged)

        ok, sudo_path = await _run("which sudo")
        if ok and sudo_path:
            capabilities["has_sudo"] = True
            ok, _ = await _run("sudo -n true")
            if ok:
                capabilities["sudo_nopasswd"] = True
                capabilities["elevation_method"] = "sudo"
            else:
                capabilities["elevation_method"] = "sudo_with_password"

        ok, doas_path = await _run("which doas")
        if ok and doas_path and not capabilities["elevation_method"]:
            capabilities["has_doas"] = True
            capabilities["elevation_method"] = "doas"

        ok, su_path = await _run("which su")
        if ok and su_path:
            capabilities["has_su"] = True
            if (
                not capabilities["elevation_method"]
                or capabilities["elevation_method"] == "sudo_with_password"
            ):
                capabilities["elevation_method"] = "su"

        if capabilities["is_root"]:
            capabilities["elevation_method"] = "none"

        return capabilities

    def requires_elevation(self, command: str) -> bool:
        """Heuristically determine if a command likely needs elevation."""
        root_cmds = [
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

    async def prepare_command(
        self,
        host: str,
        command: str,
    ) -> ElevationResult:
        """
        Prepare an elevated command if needed.

        Uses cached consent and password to avoid repeated prompts.
        First time for a host: asks for confirmation.
        Subsequent times: uses cached consent.
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

        method = caps.get("elevation_method")
        if not method:
            return ElevationResult(
                command=command,
                input_data=None,
                method=None,
                note="no_elevation_available",
            )

        # Check consent cache first
        if host in self._consent_cache:
            if not self._consent_cache[host]:
                # User previously declined for this host
                return ElevationResult(
                    command=command,
                    input_data=None,
                    method=None,
                    note="user_declined_cached",
                    base_command=command,
                )
            # User previously consented - use cached decision
            logger.debug(f"🔒 Using cached elevation consent for {host}")
        else:
            # First time - ask for consent
            confirm = await self.ctx.ui.prompt_confirm(
                f"🔒 Command may require elevation on {host}. Use {method}?",
                default=False,
            )
            self._consent_cache[host] = confirm
            if not confirm:
                return ElevationResult(
                    command=command,
                    input_data=None,
                    method=None,
                    note="user_declined",
                    base_command=command,
                )

        # Check if we have cached password (with TTL check)
        password = self._get_cached_password(host)

        if password:
            # Use cached password
            elevated_command, input_data = self._elevate_command(command, caps, method, password)
            return ElevationResult(
                command=elevated_command,
                input_data=input_data,
                method=method,
                note="password_cached",
                needs_password=False,
                base_command=command,
            )

        # No cached password - try without password first
        # su/sudo might work without password on some systems
        elevated_command, input_data = self._elevate_command(command, caps, method, None)
        return ElevationResult(
            command=elevated_command,
            input_data=input_data,
            method=method,
            note="try_without_password",
            needs_password=False,  # Will retry with password if it fails
            base_command=command,
        )

    def cache_password(self, host: str, password: str) -> None:
        """Cache elevation password for a host (with TTL expiry)."""
        self._password_cache[host] = CachedPassword(password=password)
        logger.debug(f"🔒 Cached elevation password for {host} (expires in {PASSWORD_CACHE_TTL})")

    def clear_cache(self, host: str | None = None) -> None:
        """Clear cached consent and password for a host (or all hosts)."""
        if host:
            self._consent_cache.pop(host, None)
            self._password_cache.pop(host, None)
            self._cache.pop(host, None)
        else:
            self._consent_cache.clear()
            self._password_cache.clear()
            self._cache.clear()

    def elevate_command(
        self,
        command: str,
        capabilities: dict[str, Any],
        method: str,
        password: str | None = None,
    ) -> tuple[str, str | None]:
        """Prefix command with the chosen elevation method.

        Public wrapper for _elevate_command.

        Args:
            command: The command to elevate.
            capabilities: Host capabilities dict (must include 'is_root' key).
            method: Elevation method ('sudo', 'sudo_with_password', 'doas', 'su').
            password: Optional password for methods that require it.

        Returns:
            Tuple of (elevated_command, input_data).
        """
        return self._elevate_command(command, capabilities, method, password)

    def _elevate_command(
        self,
        command: str,
        capabilities: dict[str, Any],
        method: str,
        password: str | None = None,
    ) -> tuple[str, str | None]:
        """Prefix command with the chosen elevation method."""
        if capabilities.get("is_root"):
            return command, None

        stripped = command.strip()
        if stripped.startswith(("sudo ", "doas ", "su ", "su-")):
            return command, None

        if method == "sudo":
            return f"sudo -n {command}", None
        if method == "sudo_with_password":
            if password:
                return f"sudo -S -p '' {command}", f"{password}\n"
            return f"sudo -n {command}", None
        if method == "doas":
            return f"doas {command}", None
        if method == "su":
            escaped = command.replace("'", "'\"'\"'")
            return f"su -c '{escaped}'", f"{password}\n" if password else None

        logger.warning(f"⚠️ Unknown elevation method {method}, running without elevation")
        return command, None

    async def _execute(self, host: str, command: str) -> object:
        """Execute a probe command using the shared SSH pool."""
        ssh_pool = await self.ctx.get_ssh_pool()
        options = SSHConnectionOptions(connect_timeout=10)
        return await ssh_pool.execute(host=host, command=command, timeout=10, options=options)
