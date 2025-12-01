"""
System information tools.
"""
from typing import Annotated

from merlya.tools.base import get_tool_context, validate_host
from merlya.utils.logger import logger


def disk_info(
    host: Annotated[str, "Target host"],
    path: Annotated[str, "Path for size check"] = "",
    mode: Annotated[str, "Mode: 'df', 'du', 'size', 'all'"] = "df",
    check_smart: Annotated[bool, "Check SMART health"] = False,
    check_raid: Annotated[bool, "Check RAID status"] = False,
    depth: Annotated[int, "Depth for du mode"] = 1
) -> str:
    """
    Comprehensive disk information.

    Modes: df (partitions), du (folder size), size (file/folder), all (everything)

    Args:
        host: Target host
        path: Path for size check
        mode: df, du, size, or all
        check_smart: Enable SMART check
        check_raid: Enable RAID check
        depth: Depth for du mode

    Returns:
        Disk information report
    """
    ctx = get_tool_context()
    logger.info(f"Tool: disk_info on {host} (mode={mode})")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    results = []

    # Partition usage
    if mode in ['df', 'all'] or (mode == 'size' and not path):
        cmd = f"df -h '{path}'" if path else "df -h"
        res = ctx.executor.execute(host, cmd, confirm=True)
        if res['success']:
            results.append(f"## Partition Usage\n```\n{res['stdout']}\n```")

    # Folder breakdown
    if mode == 'du' and path:
        res = ctx.executor.execute(host, f"du -h --max-depth={depth} '{path}' 2>/dev/null | sort -hr | head -20", confirm=True)
        if res['success']:
            results.append(f"## Folder Breakdown: {path}\n```\n{res['stdout']}\n```")

    # Single size
    if mode == 'size' and path:
        res = ctx.executor.execute(host, f"du -sh '{path}' 2>/dev/null", confirm=True)
        if res['success']:
            results.append(f"## Size: {path}\n```\n{res['stdout']}\n```")

    # All mode extras
    if mode == 'all':
        res = ctx.executor.execute(host, "du -sh /var/log /tmp /home /opt /var 2>/dev/null | sort -hr", confirm=True)
        if res['success']:
            results.append(f"## Largest Directories\n```\n{res['stdout']}\n```")

        res = ctx.executor.execute(host, "df -i | head -10", confirm=True)
        if res['success']:
            results.append(f"## Inode Usage\n```\n{res['stdout']}\n```")

    # SMART health
    if check_smart:
        res = ctx.executor.execute(host, "lsblk -d -o NAME,TYPE | grep disk | awk '{print $1}'", confirm=True)
        if res['success']:
            for disk in res['stdout'].strip().split('\n')[:3]:
                if disk:
                    smart_res = ctx.executor.execute(host, f"sudo smartctl -H /dev/{disk} 2>/dev/null || echo 'unavailable'", confirm=True)
                    if smart_res['success']:
                        results.append(f"## SMART: {disk}\n```\n{smart_res['stdout']}\n```")

    # RAID status
    if check_raid:
        res = ctx.executor.execute(host, "cat /proc/mdstat 2>/dev/null", confirm=True)
        if res['success'] and 'Personalities' in res['stdout']:
            results.append(f"## Software RAID\n```\n{res['stdout']}\n```")

    if results:
        return "✅ Disk Info:\n\n" + "\n\n".join(results)
    return "❌ Could not retrieve disk information"


def memory_info(
    host: Annotated[str, "Target host"]
) -> str:
    """
    Get memory information.

    Args:
        host: Target host

    Returns:
        Memory report
    """
    ctx = get_tool_context()
    logger.info(f"Tool: memory_info on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    results = []

    res = ctx.executor.execute(host, "free -h", confirm=True)
    if res['success']:
        results.append(f"## Memory Usage\n```\n{res['stdout']}\n```")

    res = ctx.executor.execute(host, "ps aux --sort=-%mem | head -10", confirm=True)
    if res['success']:
        results.append(f"## Top Memory Consumers\n```\n{res['stdout']}\n```")

    if results:
        return "✅ Memory Info:\n\n" + "\n\n".join(results)
    return "❌ Could not retrieve memory information"


def network_connections(
    host: Annotated[str, "Target host"],
    port: Annotated[int, "Filter by port (0=all)"] = 0,
    state: Annotated[str, "Filter by state"] = "all"
) -> str:
    """
    List network connections.

    Args:
        host: Target host
        port: Filter by port
        state: LISTEN, ESTABLISHED, or all

    Returns:
        Network connections
    """
    ctx = get_tool_context()
    logger.info(f"Tool: network_connections on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    cmd = "ss -tuln"
    if state == "LISTEN":
        cmd = "ss -tuln | grep LISTEN"
    elif state == "ESTABLISHED":
        cmd = "ss -tun state established"

    if port > 0:
        cmd += f" | grep ':{port}'"

    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        filter_note = ""
        if port > 0:
            filter_note += f" (port {port})"
        if state != "all":
            filter_note += f" ({state})"
        return f"✅ Network Connections{filter_note}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


def process_list(
    host: Annotated[str, "Target host"],
    filter: Annotated[str, "Filter by process name"] = "",
    sort_by: Annotated[str, "Sort by: cpu, mem, time"] = "cpu"
) -> str:
    """
    List running processes.

    Args:
        host: Target host
        filter: Grep filter
        sort_by: cpu, mem, or time

    Returns:
        Process list
    """
    ctx = get_tool_context()
    logger.info(f"Tool: process_list on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    sort_map = {"cpu": "-%cpu", "mem": "-%mem", "time": "-etime"}
    sort_flag = sort_map.get(sort_by, "-%cpu")

    cmd = f"ps aux --sort={sort_flag} | head -20"
    if filter:
        cmd = f"ps aux | grep -E '{filter}' | grep -v grep | head -20"

    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        filter_note = f" (filter: {filter})" if filter else ""
        return f"✅ Processes (sorted by {sort_by}){filter_note}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


def service_control(
    host: Annotated[str, "Target host"],
    service: Annotated[str, "Service name"],
    action: Annotated[str, "Action: status, start, stop, restart, reload, enable, disable"]
) -> str:
    """
    Control systemd services.

    CRITICAL: start/stop/restart modify service state!

    Args:
        host: Target host
        service: Service name
        action: status, start, stop, restart, reload, enable, disable

    Returns:
        Service status
    """
    ctx = get_tool_context()
    logger.info(f"Tool: service_control {action} {service} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    valid = ['status', 'start', 'stop', 'restart', 'reload', 'enable', 'disable']
    if action not in valid:
        return f"❌ Invalid action '{action}'. Use: {', '.join(valid)}"

    cmd = f"systemctl {action} {service}"
    if action == "status":
        cmd = f"systemctl status {service} 2>&1 | head -20"

    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success'] or action == "status":
        output = result.get('stdout', '') or result.get('stderr', '')
        return f"✅ systemctl {action} {service}:\n```\n{output}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"
