"""
Merlya Tools - Log Store.

Provides raw log storage and retrieval with slicing capabilities.
Logs are stored in SQLite and can be referenced by ID.
"""

from merlya.tools.logs.store import (
    LogRef,
    RawLogEntry,
    get_raw_log,
    get_raw_log_slice,
    store_raw_log,
)

__all__ = [
    "LogRef",
    "RawLogEntry",
    "get_raw_log",
    "get_raw_log_slice",
    "store_raw_log",
]
