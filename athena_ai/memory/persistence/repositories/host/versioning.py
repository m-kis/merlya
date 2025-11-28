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


def compute_changes(old_data: Optional[Dict], new_data: Dict) -> Dict:
    """Compute changes between old and new data.

    Args:
        old_data: Previous host data.
        new_data: New host data.

    Returns:
        Dictionary of changed fields with old and new values.
    """
    changes = {}
    for key, new_value in new_data.items():
        if new_value is not None:
            old_value = old_data.get(key) if isinstance(old_data, dict) else None
            if old_value != new_value:
                changes[key] = {"old": old_value, "new": new_value}
    return changes
