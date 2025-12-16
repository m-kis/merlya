"""
Merlya Tools - File operations.

Provides tools for reading, writing, and managing files on remote hosts.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# Validation patterns and limits
_VALID_MODE_PATTERN = re.compile(r"^[0-7]{3,4}$")
_MAX_PATH_LENGTH = 4096
_MAX_PATTERN_LENGTH = 256
_MAX_TRANSFER_SIZE = 100 * 1024 * 1024  # 100 MB max file transfer


@dataclass
class FileResult:
    """Result of a file operation."""

    success: bool
    data: str | list[dict[str, Any]] | list[str] | dict[str, Any] | None = None
    error: str | None = None


def _normalize_host(host_name: str) -> str:
    """Normalize host name by stripping @ prefix if present.

    The LLM may pass @hostname format which needs to be stripped
    before resolving against the inventory.
    """
    if host_name.startswith("@"):
        return host_name[1:]
    return host_name


def _validate_path(path: str) -> str | None:
    """Validate and sanitize file path. Returns error message or None if valid."""
    if not path:
        return "Path cannot be empty"
    if len(path) > _MAX_PATH_LENGTH:
        return f"Path too long (max {_MAX_PATH_LENGTH} chars)"
    if "\x00" in path:
        return "Path contains null bytes"
    return None


def _validate_mode(mode: str) -> str | None:
    """Validate file mode. Returns error message or None if valid."""
    if not _VALID_MODE_PATTERN.match(mode):
        return f"Invalid mode format: {mode} (expected octal like 0644)"
    return None


async def read_file(
    _ctx: SharedContext,
    host_name: str,
    path: str,
    lines: int | None = None,
    tail: bool = False,
) -> FileResult:
    """
    Read file content from a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: File path.
        lines: Number of lines to read (optional).
        tail: If True, read from end of file.

    Returns:
        FileResult with file content.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate path
    if error := _validate_path(path):
        return FileResult(success=False, error=error)

    # Validate lines
    if lines is not None and (lines < 1 or lines > 100000):
        return FileResult(success=False, error="Lines must be between 1 and 100000")

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)

        # Build command with safe quoting
        if lines:
            cmd = (
                f"tail -n {int(lines)} {quoted_path}"
                if tail
                else f"head -n {int(lines)} {quoted_path}"
            )
        else:
            cmd = f"cat {quoted_path}"

        result = await ssh_pool.execute(host_name, cmd)

        if result.exit_code != 0:
            return FileResult(
                success=False,
                error=result.stderr or f"Failed to read file: exit code {result.exit_code}",
            )

        return FileResult(success=True, data=result.stdout)

    except Exception as e:
        logger.error(f"Failed to read file on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def write_file(
    _ctx: SharedContext,
    host_name: str,
    path: str,
    content: str,
    mode: str = "0644",
    backup: bool = True,
) -> FileResult:
    """
    Write content to a file on a remote host.

    Uses base64 encoding to safely transfer content without shell interpretation.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: File path.
        content: Content to write.
        mode: File mode (permissions).
        backup: Create backup before writing.

    Returns:
        FileResult with operation status.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate inputs
    if error := _validate_path(path):
        return FileResult(success=False, error=error)
    if error := _validate_mode(mode):
        return FileResult(success=False, error=error)

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)

        # Create backup if requested
        if backup:
            backup_path = shlex.quote(path + ".bak")
            backup_cmd = f"[ -f {quoted_path} ] && cp {quoted_path} {backup_path}"
            backup_result = await ssh_pool.execute(host_name, backup_cmd)
            # Exit code 1 means file doesn't exist (which is fine)
            if backup_result.exit_code not in (0, 1):
                logger.warning(f"Backup may have failed for {path}")

        # Use base64 encoding to safely transfer content
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        write_cmd = f"echo {shlex.quote(encoded)} | base64 -d > {quoted_path}"
        result = await ssh_pool.execute(host_name, write_cmd)

        if result.exit_code != 0:
            return FileResult(
                success=False,
                error=result.stderr or f"Failed to write file: exit code {result.exit_code}",
            )

        # Set permissions
        chmod_result = await ssh_pool.execute(host_name, f"chmod {mode} {quoted_path}")
        if chmod_result.exit_code != 0:
            logger.warning(f"Failed to set permissions on {path}")

        return FileResult(success=True, data=f"File written: {path}")

    except Exception as e:
        logger.error(f"Failed to write file on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def list_directory(
    _ctx: SharedContext,
    host_name: str,
    path: str,
    all_files: bool = False,
    long_format: bool = False,
) -> FileResult:
    """
    List directory contents on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: Directory path.
        all_files: Include hidden files.
        long_format: Use long listing format.

    Returns:
        FileResult with directory listing.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate path
    if error := _validate_path(path):
        return FileResult(success=False, error=error)

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)

        # Build ls command
        flags = "-1"  # One file per line
        if all_files:
            flags += "a"
        if long_format:
            flags = flags.replace("-1", "-l")
            if all_files:
                flags = "-la"

        result = await ssh_pool.execute(host_name, f"ls {flags} {quoted_path}")

        if result.exit_code != 0:
            return FileResult(
                success=False,
                error=result.stderr or f"Failed to list directory: exit code {result.exit_code}",
            )

        # Parse output
        lines = result.stdout.strip().split("\n") if result.stdout else []

        if long_format:
            # Parse long format into structured data
            entries = []
            for line in lines:
                if not line or line.startswith("total"):
                    continue
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    entries.append(
                        {
                            "permissions": parts[0],
                            "links": parts[1],
                            "owner": parts[2],
                            "group": parts[3],
                            "size": parts[4],
                            "date": f"{parts[5]} {parts[6]} {parts[7]}",
                            "name": parts[8],
                        }
                    )
            return FileResult(success=True, data=entries)
        else:
            return FileResult(success=True, data=lines)

    except Exception as e:
        logger.error(f"Failed to list directory on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def file_exists(
    _ctx: SharedContext,
    host_name: str,
    path: str,
) -> FileResult:
    """
    Check if a file exists on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: File path.

    Returns:
        FileResult with boolean.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate path
    if error := _validate_path(path):
        return FileResult(success=False, error=error)

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)
        result = await ssh_pool.execute(host_name, f"test -e {quoted_path} && echo exists")

        exists = result.exit_code == 0 and "exists" in (result.stdout or "")
        return FileResult(success=True, data="exists" if exists else "not_found")

    except Exception as e:
        logger.error(f"Failed to check file on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def file_info(
    _ctx: SharedContext,
    host_name: str,
    path: str,
) -> FileResult:
    """
    Get file information (stat) from a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: File path.

    Returns:
        FileResult with file metadata.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate path
    if error := _validate_path(path):
        return FileResult(success=False, error=error)

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)

        # Use stat command for portable file info (Linux then macOS fallback)
        stat_cmd = f"stat -c '%n|%s|%U|%G|%a|%Y' {quoted_path} 2>/dev/null || stat -f '%N|%z|%Su|%Sg|%Lp|%m' {quoted_path}"
        result = await ssh_pool.execute(host_name, stat_cmd)

        if result.exit_code != 0:
            return FileResult(
                success=False,
                error=result.stderr or "File not found or permission denied",
            )

        # Parse stat output
        parts = result.stdout.strip().split("|")
        if len(parts) >= 6:
            return FileResult(
                success=True,
                data={
                    "name": parts[0],
                    "size": int(parts[1]),
                    "owner": parts[2],
                    "group": parts[3],
                    "mode": parts[4],
                    "modified": int(parts[5]),
                },
            )
        else:
            return FileResult(success=False, error="Failed to parse file info")

    except Exception as e:
        logger.error(f"Failed to get file info on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def search_files(
    _ctx: SharedContext,
    host_name: str,
    path: str,
    pattern: str,
    file_type: str | None = None,
    max_depth: int | None = None,
) -> FileResult:
    """
    Search for files on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: Search path.
        pattern: File name pattern.
        file_type: Type filter (f=file, d=directory).
        max_depth: Maximum search depth.

    Returns:
        FileResult with matching files.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate inputs
    if error := _validate_path(path):
        return FileResult(success=False, error=error)

    if not pattern or len(pattern) > _MAX_PATTERN_LENGTH:
        return FileResult(success=False, error=f"Pattern must be 1-{_MAX_PATTERN_LENGTH} chars")

    # Validate file_type (only allow 'f' or 'd')
    if file_type is not None and file_type not in ("f", "d"):
        return FileResult(success=False, error="file_type must be 'f' (file) or 'd' (directory)")

    # Validate max_depth
    if max_depth is not None and (max_depth < 1 or max_depth > 100):
        return FileResult(success=False, error="max_depth must be between 1 and 100")

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)
        quoted_pattern = shlex.quote(pattern)

        # Build find command with safe quoting
        cmd = f"find {quoted_path}"
        if max_depth:
            cmd += f" -maxdepth {int(max_depth)}"
        if file_type:
            cmd += f" -type {file_type}"  # Already validated to be 'f' or 'd'
        cmd += f" -name {quoted_pattern} 2>/dev/null | head -1000"  # Limit results

        result = await ssh_pool.execute(host_name, cmd)

        # find returns 0 even with no matches
        files = [f for f in result.stdout.strip().split("\n") if f] if result.stdout else []

        return FileResult(success=True, data=files)

    except Exception as e:
        logger.error(f"Failed to search files on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def delete_file(
    _ctx: SharedContext,
    host_name: str,
    path: str,
    force: bool = False,
) -> FileResult:
    """
    Delete a file on a remote host.

    Args:
        ctx: Shared context.
        host_name: Host name.
        path: File path.
        force: Force deletion without confirmation.

    Returns:
        FileResult with operation status.
    """
    from merlya.ssh import SSHPool

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate path
    if error := _validate_path(path):
        return FileResult(success=False, error=error)

    # Prevent dangerous deletions
    dangerous_paths = ("/", "/etc", "/var", "/usr", "/home", "/root", "/bin", "/sbin")
    if path.rstrip("/") in dangerous_paths:
        return FileResult(success=False, error=f"Refusing to delete system path: {path}")

    try:
        ssh_pool = await SSHPool.get_instance()
        quoted_path = shlex.quote(path)

        # Build rm command
        cmd = f"rm -f {quoted_path}" if force else f"rm {quoted_path}"
        result = await ssh_pool.execute(host_name, cmd)

        if result.exit_code != 0:
            return FileResult(
                success=False,
                error=result.stderr or f"Failed to delete file: exit code {result.exit_code}",
            )

        return FileResult(success=True, data=f"Deleted: {path}")

    except Exception as e:
        logger.error(f"Failed to delete file on {host_name}: {e}")
        return FileResult(success=False, error=str(e))


def _format_size(size: int) -> str:
    """Format file size in human-readable format."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}" if size >= 10 else f"{size} {unit}"
        size //= 1024
    return f"{size:.1f} TB"


async def upload_file(
    ctx: SharedContext,
    host_name: str,
    local_path: str,
    remote_path: str,
    max_size: int | None = _MAX_TRANSFER_SIZE,
) -> FileResult:
    """
    Upload a local file to a remote host via SFTP.

    Args:
        ctx: Shared context.
        host_name: Target host name.
        local_path: Local file path.
        remote_path: Remote destination path.
        max_size: Maximum file size in bytes. Set to None to disable limit.
                  Default is 100 MB.

    Returns:
        FileResult with transfer status.
    """
    from pathlib import Path

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate paths
    if error := _validate_path(local_path):
        return FileResult(success=False, error=f"Local path: {error}")
    if error := _validate_path(remote_path):
        return FileResult(success=False, error=f"Remote path: {error}")

    local = Path(local_path).expanduser()
    if not local.exists():
        return FileResult(success=False, error=f"Local file not found: {local_path}")

    if not local.is_file():
        return FileResult(success=False, error=f"Not a file: {local_path}")

    # Check file size limit if enabled
    size = local.stat().st_size
    if max_size is not None and size > max_size:
        max_mb = max_size // (1024 * 1024)
        return FileResult(
            success=False,
            error=f"File too large: {_format_size(size)} (max {max_mb} MB)",
        )

    try:
        ssh_pool = await ctx.get_ssh_pool()
        await ssh_pool.upload_file(host_name, local, remote_path)

        # File size already computed above
        size_str = _format_size(size)

        return FileResult(
            success=True,
            data={
                "local": str(local),
                "remote": f"{host_name}:{remote_path}",
                "size": size,
                "message": f"Transfer complete ({size_str})",
            },
        )

    except FileNotFoundError as e:
        return FileResult(success=False, error=str(e))
    except Exception as e:
        logger.error(f"Upload failed to {host_name}: {e}")
        return FileResult(success=False, error=str(e))


async def download_file(
    ctx: SharedContext,
    host_name: str,
    remote_path: str,
    local_path: str | None = None,
) -> FileResult:
    """
    Download a file from a remote host via SFTP.

    Args:
        ctx: Shared context.
        host_name: Source host name.
        remote_path: Remote file path.
        local_path: Local destination path (default: current directory with remote filename).

    Returns:
        FileResult with transfer status.
    """
    from pathlib import Path

    # Normalize host name (strip @ prefix if present)
    host_name = _normalize_host(host_name)

    # Validate remote path
    if error := _validate_path(remote_path):
        return FileResult(success=False, error=f"Remote path: {error}")

    # Default local path: current directory with remote filename
    if local_path is None:
        remote_name = Path(remote_path).name
        # Validate extracted filename to prevent path traversal
        if not remote_name or remote_name in (".", ".."):
            return FileResult(success=False, error="Invalid remote filename")
        local_path = f"./{remote_name}"

    if error := _validate_path(local_path):
        return FileResult(success=False, error=f"Local path: {error}")

    local = Path(local_path).expanduser()

    try:
        ssh_pool = await ctx.get_ssh_pool()
        await ssh_pool.download_file(host_name, remote_path, local)

        # Get file size for reporting
        size = local.stat().st_size
        size_str = _format_size(size)

        return FileResult(
            success=True,
            data={
                "remote": f"{host_name}:{remote_path}",
                "local": str(local.absolute()),
                "size": size,
                "message": f"Saved to: {local} ({size_str})",
            },
        )

    except Exception as e:
        logger.error(f"Download failed from {host_name}: {e}")
        return FileResult(success=False, error=str(e))
