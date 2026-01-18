"""
Merlya Audit - SQLite storage.

Provides persistent storage for audit events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from merlya.persistence.database import Database

    from .models import AuditEvent, AuditEventType

# Maximum allowed limit for get_recent queries (prevent excessive memory usage)
MAX_RECENT_LIMIT = 1000


async def ensure_table(db: Database) -> None:
    """Ensure audit_logs table exists."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            user TEXT,
            details TEXT,
            success INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_type ON audit_logs(event_type)")
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC)"
    )
    await db.commit()


async def store_event(db: Database, event: AuditEvent) -> None:
    """Store an audit event in the database."""
    try:
        await db.execute(
            """
            INSERT INTO audit_logs (id, event_type, action, target, user, details, success)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.event_type.value,
                event.action,
                event.target,
                event.user,
                json.dumps(event.details) if event.details else None,
                1 if event.success else 0,
            ),
        )
        await db.commit()
    except Exception as e:
        logger.error(f"❌ CRITICAL: Failed to persist audit log: {e}", exc_info=True)
        # Re-raise to alert callers - audit logs are critical for compliance
        raise


async def get_recent(
    db: Database,
    limit: int = 50,
    event_type: AuditEventType | None = None,
) -> list[dict[str, Any]]:
    """
    Get recent audit events.

    Args:
        db: Database instance.
        limit: Maximum number of events to return (1-1000, default 50).
        event_type: Filter by event type.

    Returns:
        List of audit event dictionaries.

    Raises:
        ValueError: If limit is invalid (< 1 or > MAX_RECENT_LIMIT).
    """
    # Validate limit to prevent negative values or excessive queries
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")
    if limit > MAX_RECENT_LIMIT:
        raise ValueError(f"limit must be at most {MAX_RECENT_LIMIT}, got {limit}")

    query = "SELECT * FROM audit_logs"
    params: tuple[Any, ...] = ()

    if event_type:
        query += " WHERE event_type = ?"
        params = (event_type.value,)

    query += " ORDER BY created_at DESC LIMIT ?"
    params = (*params, limit)

    try:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "event_type": row["event_type"],
                "action": row["action"],
                "target": row["target"],
                "user": row["user"],
                "details": json.loads(row["details"]) if row["details"] else None,
                "success": bool(row["success"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"Failed to get audit logs: {e}")
        return []


async def export_json(
    db: Database,
    limit: int = 100,
    event_type: AuditEventType | None = None,
    since: datetime | None = None,
) -> str:
    """
    Export audit logs as JSON (SIEM-compatible format).

    Args:
        db: Database instance.
        limit: Maximum events to export (1-1000).
        event_type: Filter by event type.
        since: Only export events after this timestamp.

    Returns:
        JSON string with audit events in SIEM-friendly format.
    """
    query = "SELECT * FROM audit_logs"
    conditions: list[str] = []
    params: list[Any] = []

    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type.value)

    if since:
        conditions.append("created_at >= ?")
        params.append(since.isoformat())

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(min(limit, MAX_RECENT_LIMIT))

    try:
        cursor = await db.execute(query, tuple(params))
        rows = await cursor.fetchall()

        events = []
        for row in rows:
            # Format for SIEM compatibility (CEF-like structure)
            event = {
                "timestamp": row["created_at"],
                "event_id": row["id"],
                "event_type": row["event_type"],
                "action": row["action"],
                "target": row["target"],
                "user": row["user"],
                "success": bool(row["success"]),
                "severity": "INFO" if row["success"] else "WARNING",
                "source": "merlya",
                "details": json.loads(row["details"]) if row["details"] else {},
            }
            events.append(event)

        return json.dumps(
            {
                "events": events,
                "count": len(events),
                "exported_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )

    except Exception as e:
        logger.warning(f"Failed to export audit logs: {e}")
        return json.dumps({"events": [], "count": 0, "error": str(e)})


__all__ = [
    "MAX_RECENT_LIMIT",
    "ensure_table",
    "export_json",
    "get_recent",
    "store_event",
]
