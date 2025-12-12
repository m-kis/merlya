"""
Merlya Tools - System tools.

Includes: get_system_info, check_disk_usage, check_memory, check_cpu, etc.
"""

from merlya.tools.system.cron import add_cron, list_cron, remove_cron
from merlya.tools.system.health import health_summary
from merlya.tools.system.logs import grep_logs, tail_logs
from merlya.tools.system.network import (
    check_network,
    check_port,
    dns_lookup,
    ping,
    traceroute,
)
from merlya.tools.system.services import list_services, manage_service
from merlya.tools.system.tools import (
    analyze_logs,
    check_all_disks,
    check_cpu,
    check_disk_usage,
    check_docker,
    check_memory,
    check_service_status,
    get_system_info,
    list_processes,
)

__all__ = [
    # Existing tools
    "analyze_logs",
    "check_all_disks",
    "check_cpu",
    "check_disk_usage",
    "check_docker",
    "check_memory",
    "check_service_status",
    "get_system_info",
    "list_processes",
    # New tools - Services
    "list_services",
    "manage_service",
    # New tools - Logs
    "grep_logs",
    "tail_logs",
    # New tools - Health
    "health_summary",
    # New tools - Network
    "check_network",
    "check_port",
    "dns_lookup",
    "ping",
    "traceroute",
    # New tools - Cron
    "add_cron",
    "list_cron",
    "remove_cron",
]
