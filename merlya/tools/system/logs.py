"""
Merlya Tools - Log analysis.

Intelligent log searching and analysis across remote hosts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.core.os_detect import OSFamily, detect_os
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Common log file locations by category
LOG_PATHS = {
    "system": [
        "/var/log/syslog",
        "/var/log/messages",
        "/var/log/system.log",  # macOS
    ],
    "auth": [
        "/var/log/auth.log",
        "/var/log/secure",
        "/var/log/authlog",
    ],
    "kernel": [
        "/var/log/kern.log",
        "/var/log/dmesg",
    ],
    "nginx": [
        "/var/log/nginx/error.log",
        "/var/log/nginx/access.log",
    ],
    "apache": [
        "/var/log/apache2/error.log",
        "/var/log/httpd/error_log",
        "/var/log/apache2/access.log",
        "/var/log/httpd/access_log",
    ],
    "mysql": [
        "/var/log/mysql/error.log",
        "/var/log/mariadb/mariadb.log",
    ],
    "postgres": [
        "/var/log/postgresql/postgresql-*-main.log",
        "/var/lib/pgsql/data/log/postgresql-*.log",
    ],
    "docker": [
        "/var/log/docker.log",
    ],
    "journal": [],  # Use journalctl
}

# Time period to grep duration mapping
TIME_PERIODS = {
    "5m": {"minutes": 5, "journal": "--since '5 minutes ago'"},
    "15m": {"minutes": 15, "journal": "--since '15 minutes ago'"},
    "30m": {"minutes": 30, "journal": "--since '30 minutes ago'"},
    "1h": {"minutes": 60, "journal": "--since '1 hour ago'"},
    "2h": {"minutes": 120, "journal": "--since '2 hours ago'"},
    "6h": {"minutes": 360, "journal": "--since '6 hours ago'"},
    "12h": {"minutes": 720, "journal": "--since '12 hours ago'"},
    "24h": {"minutes": 1440, "journal": "--since '24 hours ago'"},
    "7d": {"minutes": 10080, "journal": "--since '7 days ago'"},
}


@dataclass
class LogMatch:
    """A single log match."""

    line: str
    file: str
    line_number: int | None = None
    timestamp: str | None = None
    level: str | None = None


@dataclass
class GrepLogsResult:
    """Result of log grep operation."""

    matches: list[LogMatch] = field(default_factory=list)
    total_matches: int = 0
    files_searched: list[str] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


async def grep_logs(
    ctx: SharedContext,
    host: str,
    pattern: str,
    log_category: str | None = None,
    log_paths: list[str] | None = None,
    since: str = "1h",
    level: Literal["error", "warn", "info", "debug", "all"] | None = None,
    max_lines: int = 100,
    context_lines: int = 0,
    use_regex: bool = True,
) -> ToolResult:
    """
    Search logs on a remote host with intelligent defaults.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        pattern: Search pattern (regex by default).
        log_category: Category to search (system, auth, nginx, etc.).
        log_paths: Explicit paths to search (overrides category).
        since: Time period (5m, 15m, 1h, 24h, 7d).
        level: Filter by log level (error, warn, info, debug).
        max_lines: Maximum lines to return.
        context_lines: Lines of context around matches (like grep -C).
        use_regex: Use regex pattern matching.

    Returns:
        ToolResult with matching log lines.
    """
    # Validate pattern
    if not pattern or len(pattern) < 2:
        return ToolResult(
            success=False,
            data=None,
            error="❌ Pattern must be at least 2 characters",
        )

    if len(pattern) > 500:
        return ToolResult(
            success=False,
            data=None,
            error="❌ Pattern too long (max 500 chars)",
        )

    # Sanitize pattern for shell
    safe_pattern = _escape_pattern(pattern)

    # Detect OS for journal support
    os_info = await detect_os(ctx, host)

    # Determine which log sources to search
    sources = await _determine_log_sources(
        ctx, host, os_info, log_category, log_paths
    )

    if not sources["files"] and not sources["use_journal"]:
        return ToolResult(
            success=False,
            data=None,
            error="❌ No log files found to search",
        )

    result = GrepLogsResult()

    # Build the grep command
    grep_opts = _build_grep_options(use_regex, context_lines, level)
    time_filter = TIME_PERIODS.get(since, TIME_PERIODS["1h"])

    # Search journal if available and appropriate
    if sources["use_journal"]:
        journal_matches = await _search_journal(
            ctx, host, safe_pattern, time_filter, level, max_lines // 2
        )
        result.matches.extend(journal_matches)
        result.files_searched.append("journalctl")

    # Search log files
    for log_file in sources["files"]:
        if len(result.matches) >= max_lines:
            result.truncated = True
            break

        remaining = max_lines - len(result.matches)
        file_matches = await _search_log_file(
            ctx, host, log_file, safe_pattern, grep_opts, remaining
        )
        result.matches.extend(file_matches)
        if file_matches:
            result.files_searched.append(log_file)

    result.total_matches = len(result.matches)

    if result.total_matches == 0:
        return ToolResult(
            success=True,
            data={
                "matches": [],
                "total": 0,
                "files_searched": result.files_searched,
                "message": f"No matches found for '{pattern}' in {len(result.files_searched)} source(s)",
            },
        )

    logger.info(f"🔍 Found {result.total_matches} matches for '{pattern}' on {host}")

    return ToolResult(
        success=True,
        data={
            "matches": [
                {
                    "line": m.line,
                    "file": m.file,
                    "line_number": m.line_number,
                    "level": m.level,
                }
                for m in result.matches
            ],
            "total": result.total_matches,
            "files_searched": result.files_searched,
            "truncated": result.truncated,
            "pattern": pattern,
            "since": since,
        },
    )


async def tail_logs(
    ctx: SharedContext,
    host: str,
    log_path: str | None = None,
    log_category: str = "system",
    lines: int = 50,
    follow: bool = False,
) -> ToolResult:
    """
    Tail log files on a remote host.

    Args:
        ctx: Shared context.
        host: Host name from inventory.
        log_path: Explicit path to tail.
        log_category: Category if no path specified.
        lines: Number of lines to show.
        follow: Stream new lines (not yet implemented).

    Returns:
        ToolResult with log lines.
    """
    if follow:
        return ToolResult(
            success=False,
            data=None,
            error="❌ Follow mode not yet implemented",
        )

    # Determine log file
    if log_path:
        target_file = log_path
    else:
        os_info = await detect_os(ctx, host)
        sources = await _determine_log_sources(ctx, host, os_info, log_category, None)
        if not sources["files"]:
            return ToolResult(
                success=False,
                data=None,
                error=f"❌ No log files found for category '{log_category}'",
            )
        target_file = sources["files"][0]

    # Validate path
    if not _is_safe_log_path(target_file):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid log path: {target_file}",
        )

    cmd = f"tail -n {min(lines, 1000)} {target_file} 2>/dev/null"
    result = await execute_security_command(ctx, host, cmd, timeout=30)

    if result.exit_code != 0:
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Failed to read log: {result.stderr or 'File not found'}",
        )

    log_lines = result.stdout.strip().split("\n") if result.stdout else []

    return ToolResult(
        success=True,
        data={
            "file": target_file,
            "lines": log_lines,
            "count": len(log_lines),
        },
    )


async def _determine_log_sources(
    ctx: SharedContext,
    host: str,
    os_info: OSInfo,
    category: str | None,
    explicit_paths: list[str] | None,
) -> dict:
    """Determine which log sources to search."""

    sources = {"files": [], "use_journal": False}

    # Use explicit paths if provided
    if explicit_paths:
        for path in explicit_paths:
            if _is_safe_log_path(path):
                sources["files"].append(path)
        return sources

    # Detect available log sources
    if category == "journal" or (category is None and os_info.family != OSFamily.MACOS):
        # Check if journalctl is available
        result = await execute_security_command(
            ctx, host, "command -v journalctl >/dev/null && echo yes", timeout=5
        )
        if result.exit_code == 0 and "yes" in result.stdout:
            sources["use_journal"] = True

    # Get category paths or default to system
    category_paths = LOG_PATHS.get(category or "system", LOG_PATHS["system"])

    # Check which files exist
    for path in category_paths:
        if "*" in path:
            # Handle glob patterns
            check_cmd = f"ls {path} 2>/dev/null | head -1"
        else:
            check_cmd = f"test -f {path} && echo exists"

        result = await execute_security_command(ctx, host, check_cmd, timeout=5)
        if result.exit_code == 0 and result.stdout.strip():
            if "*" in path:
                sources["files"].append(result.stdout.strip().split("\n")[0])
            else:
                sources["files"].append(path)

    return sources


async def _search_journal(
    ctx: SharedContext,
    host: str,
    pattern: str,
    time_filter: dict,
    level: str | None,
    max_lines: int,
) -> list[LogMatch]:
    """Search systemd journal."""
    matches = []

    # Build journalctl command
    cmd_parts = ["journalctl", "--no-pager", "-o", "short-iso"]
    cmd_parts.append(time_filter.get("journal", "--since '1 hour ago'"))

    if level:
        priority_map = {"error": "err", "warn": "warning", "info": "info", "debug": "debug"}
        if level in priority_map:
            cmd_parts.append(f"-p {priority_map[level]}")

    cmd_parts.append(f"2>/dev/null | grep -E '{pattern}' | tail -n {max_lines}")

    cmd = " ".join(cmd_parts)
    result = await execute_security_command(ctx, host, cmd, timeout=60)

    if result.exit_code == 0 and result.stdout:
        for line in result.stdout.strip().split("\n"):
            if line:
                matches.append(LogMatch(
                    line=line[:500],
                    file="journal",
                    level=_detect_log_level(line),
                ))

    return matches


async def _search_log_file(
    ctx: SharedContext,
    host: str,
    log_file: str,
    pattern: str,
    grep_opts: str,
    max_lines: int,
) -> list[LogMatch]:
    """Search a single log file."""
    matches = []

    cmd = f"grep {grep_opts} '{pattern}' {log_file} 2>/dev/null | tail -n {max_lines}"
    result = await execute_security_command(ctx, host, cmd, timeout=60)

    if result.exit_code == 0 and result.stdout:
        for line in result.stdout.strip().split("\n"):
            if line:
                matches.append(LogMatch(
                    line=line[:500],
                    file=log_file,
                    level=_detect_log_level(line),
                ))

    return matches


def _build_grep_options(use_regex: bool, context_lines: int, level: str | None) -> str:
    """Build grep command options."""
    opts = ["-n"]  # Line numbers

    if not use_regex:
        opts.append("-F")  # Fixed string
    else:
        opts.append("-E")  # Extended regex

    if context_lines > 0:
        opts.append(f"-C {min(context_lines, 10)}")

    opts.append("-i")  # Case insensitive

    return " ".join(opts)


def _escape_pattern(pattern: str) -> str:
    """Escape pattern for safe shell use."""
    # Escape single quotes and backslashes
    return pattern.replace("\\", "\\\\").replace("'", "'\"'\"'")


def _is_safe_log_path(path: str) -> bool:
    """Validate log path for security."""
    # Only allow paths in /var/log or common log locations
    allowed_prefixes = (
        "/var/log/",
        "/var/lib/",
        "/home/",
        "/opt/",
        "/usr/local/var/log/",
    )

    # Normalize and check
    normalized = path.replace("//", "/")

    if ".." in normalized:
        return False

    return any(normalized.startswith(prefix) for prefix in allowed_prefixes)


def _detect_log_level(line: str) -> str | None:
    """Detect log level from line content."""
    line_lower = line.lower()

    if any(x in line_lower for x in ["error", "err]", "erro", "[e]", "fatal", "crit"]):
        return "error"
    if any(x in line_lower for x in ["warn", "wrn]", "[w]"]):
        return "warn"
    if any(x in line_lower for x in ["info", "inf]", "[i]"]):
        return "info"
    if any(x in line_lower for x in ["debug", "dbg]", "[d]", "trace"]):
        return "debug"

    return None
