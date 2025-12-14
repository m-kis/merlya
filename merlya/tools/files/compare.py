"""
Merlya Tools - File comparison.

Compare files between hosts or between host and local.
"""

from __future__ import annotations

import base64
import hashlib
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult
from merlya.tools.security.base import execute_security_command

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@dataclass
class FileDiff:
    """Result of file comparison."""

    files_identical: bool = False
    hash1: str = ""
    hash2: str = ""
    size1: int = 0
    size2: int = 0
    diff_lines: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    changes: int = 0


async def compare_files(
    ctx: SharedContext,
    host1: str,
    path1: str,
    host2: str | None = None,
    path2: str | None = None,
    show_diff: bool = True,
    context_lines: int = 3,
) -> ToolResult:
    """
    Compare files between two hosts or between host and local.

    Args:
        ctx: Shared context.
        host1: First host name (or "local" for local file).
        path1: Path on first host.
        host2: Second host name (or "local", or None for same host).
        path2: Path on second host (or None for same path).
        show_diff: Include diff output.
        context_lines: Lines of context in diff.

    Returns:
        ToolResult with comparison results.
    """
    # Validate paths
    if not _is_safe_path(path1):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid path: {path1}",
        )

    path2 = path2 or path1
    if not _is_safe_path(path2):
        return ToolResult(
            success=False,
            data=None,
            error=f"❌ Invalid path: {path2}",
        )

    host2 = host2 or host1

    logger.info(f"📁 Comparing {host1}:{path1} with {host2}:{path2}...")

    # Get file contents and hashes
    try:
        content1, hash1, size1 = await _get_file_info(ctx, host1, path1)
        content2, hash2, size2 = await _get_file_info(ctx, host2, path2)
    except FileNotFoundError as e:
        return ToolResult(
            success=False,
            data=None,
            error=str(e),
        )

    # Compare
    diff = FileDiff(
        files_identical=(hash1 == hash2),
        hash1=hash1,
        hash2=hash2,
        size1=size1,
        size2=size2,
    )

    if not diff.files_identical and show_diff:
        diff.diff_lines = _compute_diff(content1, content2, path1, path2, context_lines)
        diff.additions = sum(
            1 for line in diff.diff_lines if line.startswith("+") and not line.startswith("+++")
        )
        diff.deletions = sum(
            1 for line in diff.diff_lines if line.startswith("-") and not line.startswith("---")
        )
        diff.changes = diff.additions + diff.deletions

    return ToolResult(
        success=True,
        data={
            "identical": diff.files_identical,
            "file1": {
                "host": host1,
                "path": path1,
                "hash": diff.hash1,
                "size": diff.size1,
            },
            "file2": {
                "host": host2,
                "path": path2,
                "hash": diff.hash2,
                "size": diff.size2,
            },
            "diff": {
                "additions": diff.additions,
                "deletions": diff.deletions,
                "changes": diff.changes,
                "lines": diff.diff_lines[:500] if diff.diff_lines else [],
                "truncated": len(diff.diff_lines) > 500,
            }
            if not diff.files_identical
            else None,
        },
    )


async def sync_file(
    ctx: SharedContext,
    source_host: str,
    source_path: str,
    dest_host: str,
    dest_path: str | None = None,
    backup: bool = True,
) -> ToolResult:
    """
    Sync a file from source to destination host.

    Args:
        ctx: Shared context.
        source_host: Source host name.
        source_path: Path on source host.
        dest_host: Destination host name.
        dest_path: Path on destination (None = same as source).
        backup: Create backup of destination file.

    Returns:
        ToolResult with sync status.
    """
    dest_path = dest_path or source_path

    # Validate paths
    if not _is_safe_path(source_path) or not _is_safe_path(dest_path):
        return ToolResult(
            success=False,
            data=None,
            error="❌ Invalid path",
        )

    # Get source content
    try:
        content, src_hash, src_size = await _get_file_info(ctx, source_host, source_path)
    except FileNotFoundError as e:
        return ToolResult(
            success=False,
            data=None,
            error=str(e),
        )

    # Check if destination exists and differs
    try:
        _, dest_hash, _ = await _get_file_info(ctx, dest_host, dest_path)
        if src_hash == dest_hash:
            return ToolResult(
                success=True,
                data={
                    "action": "skipped",
                    "reason": "Files are identical",
                },
            )

        # Create backup if requested
        if backup:
            # Get timestamp safely
            timestamp_result = await execute_security_command(
                ctx, dest_host, "date +%Y%m%d%H%M%S", timeout=10
            )
            if timestamp_result.exit_code == 0:
                timestamp = timestamp_result.stdout.strip()
                backup_path = f"{dest_path}.bak.{timestamp}"
                # Use shlex.quote to properly escape paths and prevent command injection
                safe_dest = shlex.quote(dest_path)
                safe_backup = shlex.quote(backup_path)
                backup_cmd = f"cp {safe_dest} {safe_backup}"
                await execute_security_command(ctx, dest_host, backup_cmd, timeout=30)
                logger.info(f"📁 Created backup of {dest_path}")
            else:
                logger.warning("⚠️ Failed to create backup: could not get timestamp")

    except FileNotFoundError:
        pass  # Destination doesn't exist, that's OK

    # Write to destination
    # This is a simplified version - in production you'd use SFTP
    from merlya.tools.files.tools import write_file

    result = await write_file(ctx, dest_host, dest_path, content)

    if result.success:
        return ToolResult(
            success=True,
            data={
                "action": "synced",
                "source": {"host": source_host, "path": source_path},
                "destination": {"host": dest_host, "path": dest_path},
                "size": src_size,
            },
        )

    return ToolResult(
        success=False,
        data=None,
        error=f"❌ Failed to sync file: {result.error}",
    )


async def _get_file_info(
    ctx: SharedContext,
    host: str,
    path: str,
) -> tuple[str, str, int]:
    """Get file content, hash, and size."""
    if host == "local":
        # Local file
        local_path = Path(path).expanduser()
        if not local_path.exists():
            raise FileNotFoundError(f"❌ Local file not found: {path}")

        # Read file as raw bytes to ensure consistent hashing
        content_bytes = local_path.read_bytes()
        file_hash = hashlib.sha256(content_bytes).hexdigest()[:16]
        size = len(content_bytes)

        # Decode bytes to string with deterministic encoding
        content = content_bytes.decode("utf-8", errors="replace")

        return content, file_hash, size

    # Remote file - use shell escaping to prevent command injection
    # Use base64 encoding to preserve exact file content (including trailing newlines)
    # Format: base64_content<NUL>sha256_hash<NUL>size
    safe_path = shlex.quote(path)
    cmd = (
        f"if [ -f {safe_path} ]; then "
        f"base64 -w0 {safe_path} && "
        f"printf '\\0' && "
        f"sha256sum {safe_path} | cut -c1-16 && "
        f"printf '\\0' && "
        f"stat -c%s {safe_path}; "
        f"else exit 1; fi"
    )
    result = await execute_security_command(ctx, host, cmd, timeout=60)

    if result.exit_code != 0:
        raise FileNotFoundError(f"❌ File not found on {host}: {path}")

    # Parse output using NUL separators
    parts = result.stdout.split("\0")
    if len(parts) < 3:
        raise FileNotFoundError(f"❌ Failed to read file on {host}: {path}")

    # Decode base64 content to preserve exact bytes.
    # Decode to text with replacement to avoid failing on non-UTF8 files (binary logs, locale encodings, etc.).
    try:
        content_bytes = base64.b64decode(parts[0])
    except ValueError as e:
        raise FileNotFoundError(f"❌ Failed to decode file content on {host}: {path}") from e

    content = content_bytes.decode("utf-8", errors="replace")

    file_hash = parts[1].strip()
    if not file_hash:
        raise FileNotFoundError(f"❌ Failed to compute hash on {host}: {path}")

    try:
        size = int(parts[2].strip())
    except ValueError as e:
        raise FileNotFoundError(f"❌ Failed to read file size on {host}: {path}") from e

    return content, file_hash, size


def _compute_diff(
    content1: str,
    content2: str,
    path1: str,
    path2: str,
    context: int,
) -> list[str]:
    """Compute unified diff between two contents."""
    import difflib

    lines1 = content1.splitlines(keepends=True)
    lines2 = content2.splitlines(keepends=True)

    diff = difflib.unified_diff(
        lines1,
        lines2,
        fromfile=path1,
        tofile=path2,
        n=context,
    )

    return [line.rstrip("\n") for line in diff]


def _is_safe_path(path: str) -> bool:
    """Validate file path for security."""
    if not path:
        return False

    # Reject path traversal
    if ".." in path:
        return False

    # Reject shell metacharacters that could enable command injection
    # Even though we use shlex.quote, defense in depth is important
    # Explicitly reject dangerous shell metacharacters
    shell_metacharacters = set(";|&$`\\\"'<>(){}[]!#*?~ \n\t\r")
    if any(c in shell_metacharacters for c in path):
        return False

    # Reject newlines and other control characters
    if any(ord(c) < 32 for c in path):
        return False

    # Reject dangerous paths
    dangerous = ("/proc/", "/sys/", "/dev/")
    return not any(path.startswith(d) for d in dangerous)
