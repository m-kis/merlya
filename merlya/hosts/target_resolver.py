"""
Merlya Hosts - Target resolver for local/remote routing.

Centralizes the logic for determining whether a command should be
executed locally or on a remote host via SSH.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host


class TargetType(Enum):
    """Type of execution target."""

    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"


# Canonical local host aliases - these always execute locally
LOCAL_ALIASES: frozenset[str] = frozenset(
    {
        "local",
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",  # nosec B104 - not a binding, just a filter list entry
    }
)


@dataclass
class ResolvedTarget:
    """Result of target resolution."""

    original_query: str  # What the user/agent provided
    target_type: TargetType  # LOCAL or REMOTE
    hostname: str  # Resolved hostname/IP for SSH (or "local")
    host_entry: Host | None  # Host from inventory (if found)
    source: str  # "local_alias", "inventory", "dns", "session_context", "fallback"

    @property
    def is_local(self) -> bool:
        """Check if target is local execution."""
        return self.target_type == TargetType.LOCAL

    @property
    def is_remote(self) -> bool:
        """Check if target is remote execution."""
        return self.target_type == TargetType.REMOTE


class HostTargetResolver:
    """
    Centralized resolver for determining execution targets.

    This class is the single source of truth for deciding whether a command
    should be executed locally or on a remote host. It prevents the common
    issue where the LLM ignores user-specified hosts.

    Resolution priority:
    1. Local aliases ("local", "localhost", "127.0.0.1", "::1")
    2. Inventory lookup (by name)
    3. Inventory lookup (by hostname/IP)
    4. DNS resolution
    5. Session context (last_remote_target for follow-ups)
    6. Fallback: treat as hostname if looks like IP/FQDN
    """

    def __init__(self, ctx: SharedContext) -> None:
        """
        Initialize resolver.

        Args:
            ctx: Shared context with hosts repository and session.
        """
        self._ctx = ctx

    @staticmethod
    def is_local_target(host: str) -> bool:
        """
        Check if a host string refers to the local machine.

        This is a static method that can be used without a full context,
        for quick checks in hot paths.

        Args:
            host: Host string to check.

        Returns:
            True if host refers to local machine.
        """
        if not host:
            return False
        return host.lower().strip() in LOCAL_ALIASES

    @staticmethod
    def looks_like_ip(value: str) -> bool:
        """
        Check if a value looks like an IP address.

        Args:
            value: String to check.

        Returns:
            True if value looks like IPv4 or IPv6 address.
        """
        # IPv4 pattern
        parts = value.split(".")
        if len(parts) == 4:
            try:
                return all(0 <= int(p) <= 255 for p in parts)
            except ValueError:
                pass

        # IPv6 pattern (simplified check)
        if ":" in value and not value.startswith("@"):
            try:
                socket.inet_pton(socket.AF_INET6, value)
                return True
            except OSError:
                pass

        return False

    @staticmethod
    def looks_like_hostname(value: str) -> bool:
        """
        Check if a value looks like a valid hostname.

        Args:
            value: String to check.

        Returns:
            True if value looks like a hostname/FQDN.
        """
        if not value or value.startswith("@"):
            return False

        # Must start with alphanumeric
        if not value[0].isalnum():
            return False

        # Allow alphanumeric, dots, and hyphens
        valid_chars = set("abcdefghijklmnopqrstuvwxyz0123456789.-")
        return all(c in valid_chars for c in value.lower())

    async def resolve(
        self,
        host: str,
        *,
        allow_session_fallback: bool = True,
    ) -> ResolvedTarget:
        """
        Resolve a host string to an execution target.

        This is the main entry point for target resolution. It should be
        called before any command execution to determine the correct target.

        Args:
            host: Host string from user/agent (can be name, IP, hostname).
            allow_session_fallback: If True, use last_remote_target when
                                    host is ambiguous.

        Returns:
            ResolvedTarget with all resolution details.

        Example:
            resolver = HostTargetResolver(ctx)
            target = await resolver.resolve("pine64")
            if target.is_remote:
                await ssh_execute(target.hostname, command)
            else:
                await bash_execute(command)
        """
        if not host:
            logger.warning("⚠️ Empty host provided to resolver")
            return ResolvedTarget(
                original_query="",
                target_type=TargetType.UNKNOWN,
                hostname="",
                host_entry=None,
                source="empty",
            )

        # Normalize input
        host = host.strip()

        # Strip @ prefix if present (LLM sometimes adds it)
        if host.startswith("@"):
            host = host[1:]
            logger.debug(f"🔧 Stripped @ prefix from host: {host}")

        # 1. Check local aliases first
        if self.is_local_target(host):
            logger.debug(f"🖥️ Target '{host}' is local alias")
            return ResolvedTarget(
                original_query=host,
                target_type=TargetType.LOCAL,
                hostname="local",
                host_entry=None,
                source="local_alias",
            )

        # 2. Check inventory by name
        host_entry = await self._ctx.hosts.get_by_name(host)
        if host_entry:
            logger.info(f"🖥️ Target '{host}' found in inventory → {host_entry.hostname}")
            return ResolvedTarget(
                original_query=host,
                target_type=TargetType.REMOTE,
                hostname=host_entry.hostname,
                host_entry=host_entry,
                source="inventory",
            )

        # 3. Check inventory by hostname/IP (in case user passed IP directly)
        host_entry = await self._ctx.hosts.get_by_hostname(host)
        if host_entry:
            logger.info(f"🖥️ Target '{host}' matched inventory hostname → {host_entry.name}")
            return ResolvedTarget(
                original_query=host,
                target_type=TargetType.REMOTE,
                hostname=host_entry.hostname,
                host_entry=host_entry,
                source="inventory",
            )

        # 4. Try DNS resolution if it looks like a hostname
        if self.looks_like_hostname(host) or self.looks_like_ip(host):
            try:
                resolved_ip = socket.gethostbyname(host)
                logger.info(f"🌐 Target '{host}' resolved via DNS → {resolved_ip}")
                return ResolvedTarget(
                    original_query=host,
                    target_type=TargetType.REMOTE,
                    hostname=host,  # Use original hostname for SSH
                    host_entry=None,
                    source="dns",
                )
            except socket.gaierror:
                logger.debug(f"🌐 DNS resolution failed for '{host}'")

        # 5. Check if it's an IP address (use directly even without DNS)
        if self.looks_like_ip(host):
            logger.info(f"🌐 Target '{host}' is IP address, using directly")
            return ResolvedTarget(
                original_query=host,
                target_type=TargetType.REMOTE,
                hostname=host,
                host_entry=None,
                source="ip_direct",
            )

        # 6. Session context fallback (for follow-up questions)
        if allow_session_fallback and self._ctx.session.last_remote_target:
            last_target = self._ctx.session.last_remote_target
            logger.info(f"🔄 Target '{host}' unresolved, using session context: {last_target}")
            # Recursively resolve the last target (but don't allow another fallback)
            return await self.resolve(last_target, allow_session_fallback=False)

        # 7. Unknown target - return as-is but mark as unknown
        logger.warning(f"⚠️ Target '{host}' could not be resolved")
        return ResolvedTarget(
            original_query=host,
            target_type=TargetType.UNKNOWN,
            hostname=host,
            host_entry=None,
            source="unknown",
        )

    async def resolve_or_fail(
        self,
        host: str,
        *,
        allow_session_fallback: bool = True,
    ) -> ResolvedTarget:
        """
        Resolve a host string, raising an error if it cannot be resolved.

        This is a stricter version of resolve() that fails instead of
        returning an UNKNOWN target.

        Args:
            host: Host string from user/agent.
            allow_session_fallback: If True, use last_remote_target.

        Returns:
            ResolvedTarget (never UNKNOWN).

        Raises:
            ValueError: If host cannot be resolved.
        """
        target = await self.resolve(host, allow_session_fallback=allow_session_fallback)

        if target.target_type == TargetType.UNKNOWN:
            suggestions = await self.find_similar_hosts(host)
            msg = f"❌ Host '{host}' not found in inventory and DNS resolution failed."
            if suggestions:
                msg += f"\n\n💡 Did you mean: {', '.join(suggestions)}?"
            msg += f"\n\n📝 To add this host: /hosts add {host}"
            raise ValueError(msg)

        return target

    async def find_similar_hosts(self, query: str) -> list[str]:
        """Find similar host names for suggestions."""
        all_hosts = await self._ctx.hosts.get_all()
        similar: list[str] = []

        query_lower = query.lower()
        for host in all_hosts:
            name_lower = host.name.lower()
            hostname_lower = host.hostname.lower()

            # Substring matching
            if (
                query_lower in name_lower
                or name_lower in query_lower
                or query_lower in hostname_lower
            ):
                similar.append(host.name)

        return similar[:5]

    def update_session_target(self, target: ResolvedTarget) -> None:
        """
        Update session context with resolved target.

        Call this after successful remote execution to enable follow-up
        questions without re-specifying the host.

        Args:
            target: Successfully resolved target.
        """
        if target.is_remote and target.hostname:
            self._ctx.session.last_remote_target = target.original_query
            logger.debug(f"📝 Updated session target: {target.original_query}")


def is_local_target(host: str) -> bool:
    """
    Convenience function to check if a host is local.

    This is a module-level function for quick checks without instantiating
    the full resolver.

    Args:
        host: Host string to check.

    Returns:
        True if host refers to local machine.
    """
    return HostTargetResolver.is_local_target(host)
