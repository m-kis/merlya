"""
Host Versioning Logic.
"""

import json
import sqlite3
from datetime import datetime
from typing import Dict, Optional


def add_host_version(
    cursor: sqlite3.Cursor,
    host_id: int,
    changes: Dict,
    changed_by: str,
) -> None:
    """Add a version entry for a host.

    Args:
        cursor: Database cursor.
        host_id: Host ID to version.
        changes: Dictionary of changes made.
        changed_by: Who made the change.
    """
    cursor.execute(
        "SELECT COALESCE(MAX(version), 0) FROM host_versions WHERE host_id = ?",
        (host_id,)
    )
    current_version = cursor.fetchone()[0]
    new_version = current_version + 1

    cursor.execute("""
        INSERT INTO host_versions (host_id, version, changes, changed_by, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (host_id, new_version, json.dumps(changes), changed_by, datetime.now().isoformat()))


def compute_changes(
    old_data: Optional[Dict],
    new_data: Dict,
    track_none_changes: bool = False,
) -> Dict:
    """Compute changes between old and new data.

    Args:
        old_data: Previous host data.
        new_data: New host data (fields with None are skipped unless track_none_changes=True).
        track_none_changes: If True, record changes even when new_value is None
            (i.e., field is being cleared). Default False for backward compatibility
            with the current upsert semantics where None means "preserve existing".

    Returns:
        Dictionary of changed fields with old and new values.
    """
    changes = {}
    for key, new_value in new_data.items():
        old_value = old_data.get(key) if isinstance(old_data, dict) else None
        # Skip None values unless explicitly tracking field clears
        if new_value is None and not track_none_changes:
            continue
        if old_value != new_value:
            changes[key] = {"old": old_value, "new": new_value}
    return changes
