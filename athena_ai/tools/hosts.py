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


def search_inventory(
    query: Annotated[str, "Search query (hostname, IP, group, or environment)"]
) -> str:
    """
    Search hosts in the inventory.

    Searches across hostname, IP address, groups, and environment.

    Args:
        query: Search query

    Returns:
        Matching hosts from inventory
    """
    ctx = get_tool_context()
    logger.info(f"Tool: search_inventory query={query}")

    if not ctx.inventory_repo:
        return "❌ Inventory not available"

    try:
        hosts = ctx.inventory_repo.search_hosts(query, limit=50)

        if not hosts:
            return f"❌ No hosts found matching '{query}'\n\n💡 Try a different search term or use /inventory list"

        lines = [f"📋 INVENTORY SEARCH: {len(hosts)} hosts matching '{query}'", ""]

        for host in hosts:
            ip_info = f" ({host['ip_address']})" if host.get('ip_address') else ""
            env_info = f" [{host['environment']}]" if host.get('environment') else ""
            groups = host.get('groups', [])
            groups_info = f" groups: {', '.join(groups[:3])}" if groups else ""
            lines.append(f"  • {host['hostname']}{ip_info}{env_info}{groups_info}")

        lines.append("")
        lines.append("💡 Use @hostname syntax to reference these hosts in prompts")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Search failed: {e}"


def get_host_details(
    hostname: Annotated[str, "Hostname to get details for"]
) -> str:
    """
    Get detailed information about a specific host from inventory.

    Args:
        hostname: Hostname to look up

    Returns:
        Host details including metadata, groups, relations
    """
    ctx = get_tool_context()
    logger.info(f"Tool: get_host_details hostname={hostname}")

    if not ctx.inventory_repo:
        return "❌ Inventory not available"

    try:
        host = ctx.inventory_repo.get_host_by_name(hostname)

        if not host:
            # Search for similar hosts
            similar = ctx.inventory_repo.search_hosts(hostname, limit=5)
            if similar:
                suggestions = ", ".join(h['hostname'] for h in similar[:5])
                return f"❌ Host '{hostname}' not found\n\n💡 Similar hosts: {suggestions}"
            return f"❌ Host '{hostname}' not found in inventory"

        lines = [f"📋 HOST DETAILS: {host['hostname']}", ""]

        # Basic info
        if host.get('ip_address'):
            lines.append(f"  IP Address: {host['ip_address']}")
        if host.get('environment'):
            lines.append(f"  Environment: {host['environment']}")
        if host.get('os'):
            lines.append(f"  OS: {host['os']}")

        # Groups
        groups = host.get('groups', [])
        if groups:
            lines.append(f"  Groups: {', '.join(groups)}")

        # Metadata
        metadata = host.get('metadata', {})
        if metadata:
            lines.append("  Metadata:")
            for key, value in list(metadata.items())[:10]:
                lines.append(f"    {key}: {value}")

        # Source
        if host.get('source'):
            lines.append(f"  Source: {host['source']}")

        # Check for relations
        try:
            relations = ctx.inventory_repo.get_host_relations(hostname)
            if relations:
                lines.append(f"\n  Relations ({len(relations)}):")
                for rel in relations[:5]:
                    direction = "→" if rel['source_hostname'] == hostname else "←"
                    other = rel['target_hostname'] if rel['source_hostname'] == hostname else rel['source_hostname']
                    lines.append(f"    {direction} {other} ({rel['relation_type']})")
        except Exception:
            pass

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to get host details: {e}"


def list_inventory_hosts(
    environment: Annotated[str, "Filter by environment (prod, staging, dev, all)"] = "all",
    group: Annotated[str, "Filter by group name"] = "",
    limit: Annotated[int, "Maximum number of hosts to return"] = 50
) -> str:
    """
    List hosts from the inventory with optional filters.

    Args:
        environment: Filter by environment
        group: Filter by group name
        limit: Maximum hosts to return

    Returns:
        List of inventory hosts
    """
    ctx = get_tool_context()
    logger.info(f"Tool: list_inventory_hosts env={environment} group={group}")

    if not ctx.inventory_repo:
        return "❌ Inventory not available"

    try:
        hosts = ctx.inventory_repo.list_hosts(limit=limit * 2)  # Get more to filter

        # Filter by environment
        if environment and environment != "all":
            hosts = [h for h in hosts if h.get('environment', '').lower() == environment.lower()]

        # Filter by group
        if group:
            hosts = [h for h in hosts if group.lower() in [g.lower() for g in h.get('groups', [])]]

        # Apply limit
        hosts = hosts[:limit]

        if not hosts:
            filter_info = []
            if environment != "all":
                filter_info.append(f"environment={environment}")
            if group:
                filter_info.append(f"group={group}")
            filter_str = f" with filters: {', '.join(filter_info)}" if filter_info else ""
            return f"❌ No hosts found{filter_str}\n\n💡 Try /inventory list or list_inventory_hosts(environment='all')"

        lines = [f"📋 INVENTORY HOSTS ({len(hosts)} found):", ""]

        # Group by environment
        by_env = {}
        for host in hosts:
            env = host.get('environment', 'unknown') or 'unknown'
            if env not in by_env:
                by_env[env] = []
            by_env[env].append(host)

        for env, env_hosts in sorted(by_env.items()):
            lines.append(f"  [{env.upper()}]")
            for host in sorted(env_hosts, key=lambda h: h['hostname']):
                ip_info = f" ({host['ip_address']})" if host.get('ip_address') else ""
                lines.append(f"    • {host['hostname']}{ip_info}")
            lines.append("")

        lines.append("💡 Use @hostname syntax to reference hosts in prompts")
        lines.append("💡 Use search_inventory('query') for specific searches")

        return "\n".join(lines)

    except Exception as e:
        return f"❌ Failed to list hosts: {e}"
