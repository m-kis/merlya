"""
File operation tools.
"""
import base64
from typing import Annotated

from athena_ai.tools.base import get_tool_context, validate_host
from athena_ai.utils.logger import logger


def read_remote_file(
    host: Annotated[str, "Target host"],
    path: Annotated[str, "Absolute path to file"],
    lines: Annotated[int, "Number of lines (0=all)"] = 100
) -> str:
    """
    Read contents of a remote file.

    Args:
        host: Target host
        path: Absolute path
        lines: Number of lines (0=all)

    Returns:
        File contents or error
    """
    ctx = get_tool_context()
    logger.info(f"Tool: read_remote_file {path} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    cmd = f"cat '{path}'" if lines == 0 else f"head -n {lines} '{path}'"
    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        content = result['stdout']
        return f"✅ {path} ({content.count(chr(10))} lines):\n```\n{content}\n```"

    return f"❌ Failed to read {path}: {result.get('stderr', 'Unknown error')}"


def glob_files(
    pattern: Annotated[str, "Glob pattern (e.g. /var/log/*.log)"],
    host: Annotated[str, "Target host"]
) -> str:
    """
    List files matching a glob pattern.

    Args:
        pattern: Glob pattern
        host: Target host

    Returns:
        List of matching files
    """
    ctx = get_tool_context()
    logger.info(f"Tool: glob_files {pattern} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    result = ctx.executor.execute(host, f"ls -d {pattern}", confirm=True)

    if result['success']:
        files = result['stdout'].strip().split('\n')
        return f"✅ Found {len(files)} files:\n```\n{result['stdout']}\n```"

    return f"❌ No files found: {result.get('stderr', 'Unknown error')}"


def grep_files(
    pattern: Annotated[str, "Regex pattern"],
    path: Annotated[str, "File or directory path"],
    host: Annotated[str, "Target host"],
    recursive: Annotated[bool, "Search recursively"] = False
) -> str:
    """
    Search for text patterns using grep.

    Args:
        pattern: Regex pattern
        path: Path to search
        host: Target host
        recursive: Recursive search

    Returns:
        Matching lines
    """
    ctx = get_tool_context()
    logger.info(f"Tool: grep_files '{pattern}' in {path} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    flags = "-Er" if recursive else "-E"
    cmd = f"grep {flags} '{pattern}' '{path}' | head -n 50"
    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        output = result['stdout']
        if not output:
            return f"✅ No matches for '{pattern}' in {path}"
        return f"✅ Grep results:\n```\n{output}\n```"

    return f"❌ Grep failed: {result.get('stderr', 'Unknown error')}"


def find_file(
    name: Annotated[str, "Filename pattern (e.g. *.conf)"],
    path: Annotated[str, "Search start path"],
    host: Annotated[str, "Target host"]
) -> str:
    """
    Find files by name.

    Args:
        name: Filename pattern
        path: Start path
        host: Target host

    Returns:
        List of found files
    """
    ctx = get_tool_context()
    logger.info(f"Tool: find_file {name} in {path} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    cmd = f"find '{path}' -name '{name}' -type f 2>/dev/null | head -n 20"
    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        output = result['stdout']
        if not output:
            return f"✅ No files found matching '{name}' in {path}"
        return f"✅ Found files:\n```\n{output}\n```"

    return f"❌ Find failed: {result.get('stderr', 'Unknown error')}"


def write_remote_file(
    host: Annotated[str, "Target host"],
    path: Annotated[str, "Absolute path to file"],
    content: Annotated[str, "Content to write"],
    backup: Annotated[bool, "Create .bak backup"] = True
) -> str:
    """
    Write content to a remote file.

    CRITICAL: This modifies files!

    Args:
        host: Target host
        path: Absolute path
        content: Content to write
        backup: Create backup (default: True)

    Returns:
        Success or error
    """
    ctx = get_tool_context()
    logger.info(f"Tool: write_remote_file {path} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    encoded = base64.b64encode(content.encode()).decode()
    cmds = []
    if backup:
        cmds.append(f"cp -p '{path}' '{path}.bak' 2>/dev/null || true")
    cmds.append(f"echo '{encoded}' | base64 -d > '{path}'")

    result = ctx.executor.execute(host, " && ".join(cmds), confirm=True)

    if result['success']:
        note = " (backup created)" if backup else ""
        return f"✅ Written to {path}{note}"

    return f"❌ Failed to write {path}: {result.get('stderr', 'Unknown error')}"


def tail_logs(
    host: Annotated[str, "Target host"],
    path: Annotated[str, "Log file path"],
    lines: Annotated[int, "Number of lines"] = 50,
    grep: Annotated[str, "Optional grep filter"] = ""
) -> str:
    """
    Tail a log file with optional grep filter.

    Args:
        host: Target host
        path: Log file path
        lines: Number of lines
        grep: Optional filter

    Returns:
        Log content
    """
    ctx = get_tool_context()
    logger.info(f"Tool: tail_logs {path} on {host}")

    is_valid, msg = validate_host(host)
    if not is_valid:
        return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    cmd = f"tail -n {lines} '{path}'"
    if grep:
        cmd += f" | grep -E '{grep}'"

    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        filter_note = f" (filtered: {grep})" if grep else ""
        return f"✅ Last {lines} lines of {path}{filter_note}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed to read {path}: {result.get('stderr', 'Unknown error')}"
