"""
Host Data Converters.
"""

import json
import sqlite3
from typing import Any, Dict


def host_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a host row to dictionary with JSON parsing.

    Args:
        row: Database row.

    Returns:
        Host dictionary with parsed JSON fields.
    """
    d = dict(row)
    # Parse JSON fields with appropriate defaults
    for field in ["aliases", "groups"]:
        if d.get(field):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
        else:
            d[field] = []
    # Metadata defaults to empty dict
    if d.get("metadata"):
        try:
            d["metadata"] = json.loads(d["metadata"])
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
    else:
        d["metadata"] = {}
    return d


def version_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a generic sqlite3.Row to dictionary with JSON parsing for changes field.

    Used for host_versions table rows.

    Args:
        row: Database row.

    Returns:
        Dictionary with parsed 'changes' JSON field (if present).
    """
    d = dict(row)
    # Parse 'changes' JSON field if present
    if "changes" in d and d["changes"]:
        try:
            d["changes"] = json.loads(d["changes"])
        except (json.JSONDecodeError, TypeError):
            d["changes"] = {}
    elif "changes" in d:
        d["changes"] = {}
    return d
