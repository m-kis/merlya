"""
Host management tools.
"""
from typing import Annotated

from athena_ai.tools.base import get_tool_context, validate_host
from athena_ai.utils.logger import logger


def get_infrastructure_context() -> str:
    """
    Get current infrastructure context from HostRegistry.

    Returns:
        Infrastructure summary with stats and sample hosts
    """
    ctx = get_tool_context()
    logger.info("Tool: get_infrastructure_context")

    if not ctx.host_registry:
        return "❌ Host registry not initialized"

    if ctx.host_registry.is_empty():
        ctx.host_registry.load_all_sources()

    lines = []

    if not ctx.host_registry.is_empty():
        stats = ctx.host_registry.get_stats()
        total = stats.get("total_hosts", 0)
        by_env = stats.get("by_environment", {})
        sources = stats.get("loaded_sources", [])

        lines.append(f"📋 HOST REGISTRY: {total} validated hosts")
        lines.append(f"   Sources: {', '.join(sources)}")
        lines.append("")

        if by_env:
            lines.append("   By environment:")
            for env, count in sorted(by_env.items()):
                lines.append(f"     • {env}: {count} hosts")
            lines.append("")

        # Sample hosts
        all_hosts = ctx.host_registry.hostnames
        mongo_hosts = [h for h in all_hosts if 'mongo' in h.lower()]
        prod_hosts = [h for h in all_hosts if 'prod' in h.lower()]

        if mongo_hosts:
            lines.append(f"   MongoDB servers ({len(mongo_hosts)} found):")
            for h in sorted(mongo_hosts)[:10]:
                lines.append(f"     • {h}")
            if len(mongo_hosts) > 10:
                lines.append(f"     ... and {len(mongo_hosts) - 10} more")
            lines.append("")

        if prod_hosts:
            lines.append(f"   Production servers ({len(prod_hosts)} found):")
            for h in sorted(prod_hosts)[:10]:
                lines.append(f"     • {h}")
            if len(prod_hosts) > 10:
                lines.append(f"     ... and {len(prod_hosts) - 10} more")
            lines.append("")

        lines.append("💡 Use list_hosts(pattern='mongo') for filtered lists")
    else:
        lines.append("📋 HOST REGISTRY: No hosts loaded")
        lines.append("   Check inventory sources (/etc/hosts, ~/.ssh/config)")

    return "\n".join(lines)


def list_hosts(
    environment: Annotated[str, "Filter by environment: 'production', 'staging', 'development', or 'all'"] = "all",
    pattern: Annotated[str, "Filter by hostname pattern (regex)"] = ""
) -> str:
    """
    List all available hosts from the inventory.

    IMPORTANT: Always use this tool FIRST to see what hosts are available.

    Args:
        environment: Filter by environment
        pattern: Optional regex pattern

    Returns:
        List of available hosts
    """
    ctx = get_tool_context()
    logger.info(f"Tool: list_hosts (env={environment}, pattern={pattern})")

    if not ctx.host_registry:
        return "❌ Host registry not initialized"

    if ctx.host_registry.is_empty():
        ctx.host_registry.load_all_sources()

    env_filter = None if environment == "all" else environment
    pattern_filter = pattern if pattern else None
    hosts = ctx.host_registry.filter(environment=env_filter, pattern=pattern_filter)

    if not hosts:
        if environment != "all" or pattern:
            return f"❌ No hosts found (environment={environment}, pattern={pattern})\n\n💡 Try list_hosts(environment='all')"
        return "❌ No hosts in inventory."

    lines = [f"📋 AVAILABLE HOSTS ({len(hosts)} found):", ""]

    # Group by environment
    by_env = {}
    for host in hosts:
        env = host.environment or "unknown"
        if env not in by_env:
            by_env[env] = []
        by_env[env].append(host)

    for env, env_hosts in sorted(by_env.items()):
        lines.append(f"  [{env.upper()}]")
        for host in sorted(env_hosts, key=lambda h: h.hostname):
            ip_info = f" ({host.ip_address})" if host.ip_address else ""
            groups_info = f" [{', '.join(host.groups)}]" if host.groups else ""
            lines.append(f"    • {host.hostname}{ip_info}{groups_info}")
        lines.append("")

    lines.append("💡 Use these exact hostnames with execute_command()")
    return "\n".join(lines)


def scan_host(
    hostname: Annotated[str, "Hostname or IP address to scan"]
) -> str:
    """
    Scan a remote host to detect OS, kernel, services.

    IMPORTANT: The hostname MUST exist in the inventory.

    Args:
        hostname: Hostname or IP address

    Returns:
        Scan results
    """
    ctx = get_tool_context()
    logger.info(f"Tool: scan_host {hostname}")

    is_valid, message = validate_host(hostname)
    if not is_valid:
        return f"❌ BLOCKED: Cannot scan '{hostname}'\n\n{message}\n\n💡 Use list_hosts()"

    try:
        info = ctx.context_manager.scan_host(hostname)

        if not info.get('accessible'):
            return f"❌ Host {hostname} not accessible\n\nError: {info.get('error', 'Unknown')}"

        lines = [
            f"✅ Host {hostname} scan completed", "",
            f"IP Address: {info.get('ip', 'unknown')}",
            f"OS: {info.get('os', 'unknown')}",
            f"Kernel: {info.get('kernel', 'unknown')}",
        ]

        services = info.get('services', [])
        if services:
            lines.append(f"\nRunning Services ({len(services)}):")
            for svc in services[:15]:
                lines.append(f"  • {svc}")
            if len(services) > 15:
                lines.append(f"  ... and {len(services) - 15} more")

        # Save to memory
        if ctx.context_memory:
            try:
                ctx.context_memory.save_host_fact(hostname, "os", info.get('os', 'unknown'))
                ctx.context_memory.save_host_fact(hostname, "kernel", info.get('kernel', 'unknown'))
                ctx.context_memory.record_host_usage(hostname)
            except Exception:
                pass

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Scan failed for {hostname}\n\nError: {e}"


def check_permissions(
    target: Annotated[str, "Target host to check"]
) -> str:
    """
    Check sudo availability and user permissions.

    IMPORTANT: The target MUST exist in the inventory.

    Args:
        target: Target host

    Returns:
        Permission capabilities summary
    """
    ctx = get_tool_context()
    logger.info(f"Tool: check_permissions on {target}")

    is_valid, message = validate_host(target)
    if not is_valid:
        return f"❌ BLOCKED: Cannot check '{target}'\n\n{message}\n\n💡 Use list_hosts()"

    try:
        ctx.permissions.detect_capabilities(target)
        summary = ctx.permissions.format_capabilities_summary(target)
        return f"✅ Permission check for {target}\n\n{summary}"
    except Exception as e:
        return f"❌ Permission check failed: {e}"
