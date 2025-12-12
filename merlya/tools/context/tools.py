"""
Merlya Tools - Context Tools implementation.

Provides summarized views of infrastructure to minimize token usage.
Instead of dumping all host data, these tools return compact summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class HostsSummary:
    """Compact summary of hosts inventory."""

    total_count: int
    healthy_count: int
    unhealthy_count: int
    unknown_count: int
    by_tag: dict[str, int] = field(default_factory=dict)
    by_status: dict[str, int] = field(default_factory=dict)
    sample_hosts: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Format as compact text for LLM context."""
        lines = [
            f"📊 Inventory: {self.total_count} hosts",
            f"   ✅ Healthy: {self.healthy_count}",
            f"   ❌ Unhealthy: {self.unhealthy_count}",
            f"   ❓ Unknown: {self.unknown_count}",
        ]

        if self.by_tag:
            tag_str = ", ".join(f"{k}:{v}" for k, v in sorted(self.by_tag.items())[:5])
            lines.append(f"   🏷️ Tags: {tag_str}")

        if self.sample_hosts:
            lines.append(f"   📋 Sample: {', '.join(self.sample_hosts[:5])}")

        return "\n".join(lines)


@dataclass
class HostDetails:
    """Detailed information about a single host."""

    name: str
    hostname: str
    port: int
    username: str | None
    jump_host: str | None
    tags: list[str]
    health_status: str
    last_seen: str | None
    os_info: dict[str, Any] | None
    metadata: dict[str, Any]

    def to_text(self) -> str:
        """Format as compact text for LLM context."""
        lines = [
            f"🖥️ Host: {self.name}",
            f"   Address: {self.hostname}:{self.port}",
            f"   Status: {self.health_status}",
        ]

        if self.username:
            lines.append(f"   User: {self.username}")

        if self.jump_host:
            lines.append(f"   Via: {self.jump_host}")

        if self.tags:
            lines.append(f"   Tags: {', '.join(self.tags)}")

        if self.os_info:
            os_str = self.os_info.get("name", "Unknown")
            if self.os_info.get("version"):
                os_str += f" {self.os_info['version']}"
            lines.append(f"   OS: {os_str}")

        if self.last_seen:
            lines.append(f"   Last seen: {self.last_seen}")

        return "\n".join(lines)


@dataclass
class GroupSummary:
    """Summary of host groups."""

    name: str
    host_count: int
    healthy_count: int
    sample_hosts: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Format as compact text."""
        health_pct = (self.healthy_count / max(self.host_count, 1)) * 100
        hosts_str = ", ".join(self.sample_hosts[:3])
        return f"📁 {self.name}: {self.host_count} hosts ({health_pct:.0f}% healthy) [{hosts_str}]"


async def list_hosts_summary(
    ctx: SharedContext,
    tag: str | None = None,
    status: str | None = None,
) -> HostsSummary:
    """
    Get a compact summary of hosts inventory.

    This tool provides a token-efficient summary instead of listing all hosts.
    Use get_host_details() for specific host information.

    Args:
        ctx: Shared context with database access.
        tag: Optional tag filter.
        status: Optional status filter (healthy, unhealthy, unknown).

    Returns:
        HostsSummary with counts and sample hosts.

    Example:
        summary = await list_hosts_summary(ctx, tag="production")
        print(summary.to_text())
        # 📊 Inventory: 42 hosts
        #    ✅ Healthy: 38
        #    ❌ Unhealthy: 2
        #    ❓ Unknown: 2
        #    🏷️ Tags: production:42, web:20, db:10
        #    📋 Sample: web-01, web-02, db-01, api-01, cache-01
    """
    from merlya.persistence.repositories import HostRepository

    repo = HostRepository(ctx.db)

    # Get hosts with optional filters
    if tag:
        hosts = await repo.get_by_tag(tag)
    else:
        hosts = await repo.get_all()

    # Apply status filter if specified
    if status:
        status_lower = status.lower()
        hosts = [h for h in hosts if h.health_status.lower() == status_lower]

    # Calculate counts (use lowercase for case-insensitive comparison)
    total = len(hosts)
    healthy = sum(1 for h in hosts if h.health_status.lower() == "healthy")
    unhealthy = sum(1 for h in hosts if h.health_status.lower() in ("unhealthy", "failed"))
    unknown = total - healthy - unhealthy

    # Count by tag
    tag_counts: dict[str, int] = {}
    for host in hosts:
        for t in host.tags or []:
            tag_counts[t] = tag_counts.get(t, 0) + 1

    # Count by status
    status_counts: dict[str, int] = {}
    for host in hosts:
        s = host.health_status
        status_counts[s] = status_counts.get(s, 0) + 1

    # Sample hosts (first 5)
    sample = [h.name for h in hosts[:5]]

    logger.debug(f"📊 Hosts summary: {total} total, {healthy} healthy")

    return HostsSummary(
        total_count=total,
        healthy_count=healthy,
        unhealthy_count=unhealthy,
        unknown_count=unknown,
        by_tag=dict(sorted(tag_counts.items(), key=lambda x: -x[1])[:10]),
        by_status=status_counts,
        sample_hosts=sample,
    )


async def get_host_details(
    ctx: SharedContext,
    host_name: str,
) -> HostDetails | None:
    """
    Get detailed information about a specific host.

    Args:
        ctx: Shared context with database access.
        host_name: Host name or ID to look up.

    Returns:
        HostDetails if found, None otherwise.

    Example:
        details = await get_host_details(ctx, "web-01")
        if details:
            print(details.to_text())
    """
    from merlya.persistence.repositories import HostRepository

    repo = HostRepository(ctx.db)
    host = await repo.get_by_name(host_name)

    if not host:
        # Try by ID
        host = await repo.get_by_id(host_name)

    if not host:
        logger.warning(f"⚠️ Host not found: {host_name}")
        return None

    logger.debug(f"🖥️ Got details for host: {host.name}")

    return HostDetails(
        name=host.name,
        hostname=host.hostname,
        port=host.port,
        username=host.username,
        jump_host=host.jump_host,
        tags=host.tags or [],
        health_status=host.health_status,
        last_seen=host.last_seen.isoformat() if host.last_seen else None,
        os_info=host.os_info.model_dump() if host.os_info else None,
        metadata=host.metadata or {},
    )


async def list_groups(
    ctx: SharedContext,
) -> list[GroupSummary]:
    """
    List host groups with summary information.

    Groups are derived from tags. Each unique tag is treated as a group.

    Args:
        ctx: Shared context with database access.

    Returns:
        List of GroupSummary objects.

    Example:
        groups = await list_groups(ctx)
        for group in groups:
            print(group.to_text())
        # 📁 production: 42 hosts (90% healthy) [web-01, db-01, api-01]
        # 📁 staging: 10 hosts (100% healthy) [stg-web-01, stg-db-01]
    """
    from merlya.persistence.repositories import HostRepository

    repo = HostRepository(ctx.db)
    all_hosts = await repo.get_all()

    # Group hosts by tags
    groups: dict[str, list[Any]] = {}
    for host in all_hosts:
        for tag in host.tags or []:
            if tag not in groups:
                groups[tag] = []
            groups[tag].append(host)

    # Build summaries
    summaries = []
    for tag, hosts in sorted(groups.items(), key=lambda x: -len(x[1])):
        healthy = sum(1 for h in hosts if (h.health_status or "").lower() == "healthy")
        sample = [h.name for h in hosts[:3]]

        summaries.append(
            GroupSummary(
                name=tag,
                host_count=len(hosts),
                healthy_count=healthy,
                sample_hosts=sample,
            )
        )

    logger.debug(f"📁 Found {len(summaries)} groups")

    return summaries


async def get_infrastructure_context(
    ctx: SharedContext,
    include_groups: bool = True,
    max_groups: int = 5,
) -> str:
    """
    Get a compact infrastructure context for LLM.

    Combines hosts summary and groups into a single context string.

    Args:
        ctx: Shared context with database access.
        include_groups: Include group summaries.
        max_groups: Maximum groups to include.

    Returns:
        Formatted context string.

    Example:
        context = await get_infrastructure_context(ctx)
        # Returns a compact overview suitable for LLM context
    """
    lines = []

    # Hosts summary
    summary = await list_hosts_summary(ctx)
    lines.append(summary.to_text())

    # Groups if requested
    if include_groups:
        groups = await list_groups(ctx)
        if groups:
            lines.append("\n📁 Groups:")
            for group in groups[:max_groups]:
                lines.append(f"   {group.to_text()}")

            if len(groups) > max_groups:
                lines.append(f"   ... and {len(groups) - max_groups} more groups")

    return "\n".join(lines)
