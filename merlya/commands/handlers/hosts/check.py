"""
Merlya Commands - Host check command.

Implements /hosts check subcommand with SSH connectivity testing.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, TypedDict

from loguru import logger

from merlya.commands.registry import CommandResult, subcommand
from merlya.core.types import HostStatus

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host


class SSHConnectionTestResult(TypedDict):
    """Result of SSH connection test."""

    success: bool
    latency_ms: int | None
    os_info: str | None
    error: str | None


class HostCheckResult(TypedDict):
    """Result of host check operation."""

    host: Host
    result: SSHConnectionTestResult


async def test_ssh_connection(
    ctx: SharedContext,
    hostname: str,
    port: int,
    username: str | None,
    timeout: int = 10,
) -> SSHConnectionTestResult:
    """
    Test SSH connection to a host.

    Returns dict with: success, latency_ms, error, os_info
    """
    from merlya.ssh import SSHConnectionOptions

    try:
        ssh_pool = await ctx.get_ssh_pool()
        opts = SSHConnectionOptions(port=port, connect_timeout=timeout)

        start = time.monotonic()

        # Try to execute a simple command
        result = await ssh_pool.execute(
            host=hostname,
            command="echo ok && uname -s 2>/dev/null || echo unknown",
            timeout=timeout,
            username=username,
            options=opts,
            retry=False,  # Don't retry for connection test
        )

        latency = int((time.monotonic() - start) * 1000)

        if result.exit_code == 0:
            os_info = result.stdout.strip().split("\n")[-1] if result.stdout else "unknown"
            return {
                "success": True,
                "latency_ms": latency,
                "os_info": os_info,
                "error": None,
            }
        else:
            return {
                "success": False,
                "latency_ms": latency,
                "os_info": None,
                "error": result.stderr or "Command failed",
            }

    except Exception as e:
        logger.debug(f"Connection test failed: {e}")
        return {
            "success": False,
            "latency_ms": None,
            "os_info": None,
            "error": str(e),
        }


def parse_check_options(args: list[str]) -> tuple[bool, str | None, str | None]:
    """
    Parse options for hosts check command.

    Returns:
        Tuple of (parallel, tag, host_name).
    """
    parallel = "--parallel" in args
    tag = None
    host_name = None

    for arg in args:
        if arg.startswith("--tag="):
            tag = arg[6:]
        elif not arg.startswith("--"):
            host_name = arg

    return parallel, tag, host_name


async def get_hosts_to_check(
    ctx: SharedContext,
    host_name: str | None,
    tag: str | None,
) -> tuple[list[Host], CommandResult | None]:
    """
    Get hosts to check based on filters.

    Returns:
        Tuple of (hosts_list, error_result).
        error_result is None if hosts were found successfully.
    """
    if host_name:
        host = await ctx.hosts.get_by_name(host_name)
        if not host:
            return [], CommandResult(success=False, message=f"Host '{host_name}' not found.")
        return [host], None

    if tag:
        hosts = await ctx.hosts.get_by_tag(tag)
        if not hosts:
            return [], CommandResult(success=False, message=f"No hosts found with tag '{tag}'.")
        return hosts, None

    hosts = await ctx.hosts.get_all()
    if not hosts:
        return [], CommandResult(success=True, message="No hosts in inventory.")
    return hosts, None


async def check_hosts_parallel(
    ctx: SharedContext,
    hosts: list[Host],
    max_concurrent: int = 10,
) -> list[HostCheckResult]:
    """Check hosts in parallel with semaphore-limited concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def check_one(host: Host) -> HostCheckResult:
        async with semaphore:
            result = await test_ssh_connection(ctx, host.hostname, host.port, host.username)
            return {"host": host, "result": result}

    tasks = [check_one(h) for h in hosts]
    return await asyncio.gather(*tasks)


async def check_hosts_sequential(
    ctx: SharedContext,
    hosts: list[Host],
) -> list[HostCheckResult]:
    """Check hosts sequentially with progress display."""
    results: list[HostCheckResult] = []
    for i, host in enumerate(hosts):
        ctx.ui.muted(f"  [{i + 1}/{len(hosts)}] Checking {host.name}...")
        result = await test_ssh_connection(ctx, host.hostname, host.port, host.username)
        results.append({"host": host, "result": result})
    return results


async def process_check_results(
    ctx: SharedContext,
    results: list[HostCheckResult],
) -> tuple[int, int, list[list[str]]]:
    """
    Process check results and update host statuses.

    Returns:
        Tuple of (healthy_count, unhealthy_count, table_rows).
    """
    healthy = 0
    unhealthy = 0
    rows: list[list[str]] = []

    for item in results:
        host = item["host"]
        result = item["result"]

        if result["success"]:
            healthy += 1
            status = "ok"
            latency = f"{result['latency_ms']}ms"
            error = "-"
            host.health_status = HostStatus.HEALTHY
        else:
            unhealthy += 1
            status = "err"
            latency = "-"
            error = result["error"][:50] if result["error"] else "Unknown error"
            host.health_status = HostStatus.UNREACHABLE

        await ctx.hosts.update(host)
        rows.append([status, host.name, host.hostname, latency, error])

    return healthy, unhealthy, rows


@subcommand(
    "hosts",
    "check",
    "Check connectivity to hosts",
    "/hosts check [<name>|--tag=<tag>|--all]",
)
async def cmd_hosts_check(ctx: SharedContext, args: list[str]) -> CommandResult:
    """
    Check SSH connectivity to hosts.

    Examples:
        /hosts check           - Check all hosts
        /hosts check webserver - Check specific host
        /hosts check --tag=prod - Check hosts with tag
        /hosts check --parallel - Check all hosts in parallel
    """
    # Parse options
    parallel, tag, host_name = parse_check_options(args)

    # Get hosts to check
    hosts_to_check, error = await get_hosts_to_check(ctx, host_name, tag)
    if error:
        return error

    ctx.ui.info(f"Checking {len(hosts_to_check)} host(s)...")

    # Run checks
    if parallel and len(hosts_to_check) > 1:
        results = await check_hosts_parallel(ctx, hosts_to_check)
    else:
        results = await check_hosts_sequential(ctx, hosts_to_check)

    # Process results and update statuses
    healthy, unhealthy, rows = await process_check_results(ctx, results)

    # Display results
    ctx.ui.table(
        headers=["Status", "Name", "Hostname", "Latency", "Error"],
        rows=rows,
        title=f"Connectivity Check ({healthy} healthy, {unhealthy} unreachable)",
    )

    if unhealthy == 0:
        return CommandResult(
            success=True,
            message=f"All {healthy} host(s) are reachable.",
        )
    return CommandResult(
        success=True,
        message=f"{unhealthy}/{len(hosts_to_check)} host(s) unreachable.",
    )


__all__ = [
    "HostCheckResult",
    "SSHConnectionTestResult",
    "check_hosts_parallel",
    "check_hosts_sequential",
    "cmd_hosts_check",
    "get_hosts_to_check",
    "parse_check_options",
    "process_check_results",
    "test_ssh_connection",
]
