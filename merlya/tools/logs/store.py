"""
Merlya Tools - Log Store implementation.

Stores raw command outputs in SQLite for later retrieval.
Provides slicing capabilities to extract specific portions of logs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.persistence.database import Database


@dataclass
class LogRef:
    """Reference to a stored log."""

    id: str
    host_id: str | None
    command: str
    line_count: int
    byte_size: int
    created_at: datetime


@dataclass
class RawLogEntry:
    """A stored raw log entry."""

    id: str
    host_id: str | None
    command: str
    output: str
    exit_code: int | None
    line_count: int
    byte_size: int
    created_at: datetime
    expires_at: datetime | None


async def store_raw_log(
    db: Database,
    command: str,
    output: str,
    host_id: str | None = None,
    exit_code: int | None = None,
    ttl_hours: int = 24,
) -> LogRef:
    """
    Store a raw log output for later retrieval.

    Args:
        db: Database connection.
        command: Command that generated the output.
        output: Raw output to store.
        host_id: Optional host ID the command was run on.
        exit_code: Optional command exit code.
        ttl_hours: Time-to-live in hours (default 24).

    Returns:
        LogRef with ID to retrieve the log later.

    Example:
        log_ref = await store_raw_log(
            db=ctx.db,
            command="journalctl -n 1000",
            output=log_output,
            host_id="web-01",
        )
        # Later: get_raw_log_slice(db, log_ref.id, around_line=500, window=50)
    """
    log_id = str(uuid.uuid4())
    now = datetime.now()
    expires_at = now + timedelta(hours=ttl_hours)

    # Calculate metrics
    line_count = output.count("\n") + (1 if output and not output.endswith("\n") else 0)
    byte_size = len(output.encode("utf-8"))

    await db.execute(
        """
        INSERT INTO raw_logs (id, host_id, command, output, exit_code,
                             line_count, byte_size, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (log_id, host_id, command, output, exit_code, line_count, byte_size, now, expires_at),
    )
    await db.connection.commit()

    logger.debug(f"📝 Stored log {log_id[:8]}... ({line_count} lines, {byte_size} bytes)")

    return LogRef(
        id=log_id,
        host_id=host_id,
        command=command,
        line_count=line_count,
        byte_size=byte_size,
        created_at=now,
    )


async def get_raw_log(db: Database, log_id: str) -> RawLogEntry | None:
    """
    Retrieve a complete raw log by ID.

    Args:
        db: Database connection.
        log_id: Log reference ID.

    Returns:
        RawLogEntry if found, None otherwise.
    """
    async with await db.execute(
        "SELECT * FROM raw_logs WHERE id = ?",
        (log_id,),
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            logger.warning(f"⚠️ Log not found: {log_id[:8]}...")
            return None

        return RawLogEntry(
            id=row["id"],
            host_id=row["host_id"],
            command=row["command"],
            output=row["output"],
            exit_code=row["exit_code"],
            line_count=row["line_count"],
            byte_size=row["byte_size"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )


async def get_raw_log_slice(
    db: Database,
    log_id: str,
    around_line: int | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    window: int = 50,
) -> tuple[str, int, int] | None:
    """
    Retrieve a slice of a stored log.

    Args:
        db: Database connection.
        log_id: Log reference ID.
        around_line: Center the slice around this line (1-indexed).
        start_line: Start line (1-indexed, inclusive).
        end_line: End line (1-indexed, inclusive).
        window: Number of lines before/after around_line (default 50).

    Returns:
        Tuple of (sliced_output, actual_start_line, actual_end_line)
        or None if log not found.

    Example:
        # Get 50 lines before and after line 500
        slice_text, start, end = await get_raw_log_slice(
            db, log_ref.id, around_line=500, window=50
        )
        # Returns lines 450-550

        # Or get specific range
        slice_text, start, end = await get_raw_log_slice(
            db, log_ref.id, start_line=100, end_line=200
        )
    """
    log_entry = await get_raw_log(db, log_id)
    if not log_entry:
        return None

    lines = log_entry.output.split("\n")
    total_lines = len(lines)

    # Determine slice bounds
    if around_line is not None:
        # Center around a specific line
        around_idx = max(0, around_line - 1)  # Convert to 0-indexed
        start_idx = max(0, around_idx - window)
        end_idx = min(total_lines, around_idx + window + 1)
    elif start_line is not None:
        # Explicit range
        start_idx = max(0, start_line - 1)  # Convert to 0-indexed
        end_idx = min(total_lines, end_line or total_lines)
    else:
        # Default: first N lines
        start_idx = 0
        end_idx = min(total_lines, window * 2)

    # Extract slice
    sliced_lines = lines[start_idx:end_idx]
    sliced_output = "\n".join(sliced_lines)

    # Return 1-indexed line numbers for display
    actual_start = start_idx + 1
    actual_end = start_idx + len(sliced_lines)

    logger.debug(
        f"📄 Log slice {log_id[:8]}...: lines {actual_start}-{actual_end} of {total_lines}"
    )

    return sliced_output, actual_start, actual_end


async def cleanup_expired_logs(db: Database) -> int:
    """
    Remove expired log entries.

    Args:
        db: Database connection.

    Returns:
        Number of logs deleted.
    """
    now = datetime.now()

    async with await db.execute(
        "DELETE FROM raw_logs WHERE expires_at < ?",
        (now,),
    ) as cursor:
        deleted = int(cursor.rowcount or 0)

    await db.connection.commit()

    if deleted > 0:
        logger.info(f"🧹 Cleaned up {deleted} expired logs")

    return deleted


async def get_logs_by_host(
    db: Database,
    host_id: str,
    limit: int = 10,
) -> list[LogRef]:
    """
    Get recent log references for a host.

    Args:
        db: Database connection.
        host_id: Host ID to filter by.
        limit: Maximum number of logs to return.

    Returns:
        List of LogRef objects.
    """
    async with await db.execute(
        """
        SELECT id, host_id, command, line_count, byte_size, created_at
        FROM raw_logs
        WHERE host_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (host_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
        return [
            LogRef(
                id=row["id"],
                host_id=row["host_id"],
                command=row["command"],
                line_count=row["line_count"],
                byte_size=row["byte_size"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
