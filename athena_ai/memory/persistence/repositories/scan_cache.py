"""
Scan Cache Repository Mixin - Manages scan result caching.

Handles caching of scan results (nmap, ports, services, etc.) with TTL support.

Note: All timestamps (created_at, expires_at) are stored in UTC for consistency
across timezone boundaries. Comparisons and generation use timezone-aware UTC.
"""

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ScanCacheRepositoryMixin:
    """Mixin for scan cache operations."""

    def _init_scan_cache_tables(self, cursor: sqlite3.Cursor) -> None:
        """Initialize scan cache table."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scan_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                scan_type TEXT NOT NULL,
                data TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE,
                UNIQUE(host_id, scan_type)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_scan_cache_expires ON scan_cache(expires_at)
        """)

    def get_scan_cache(self, host_id: int, scan_type: str) -> Optional[Dict[str, Any]]:
        """Get cached scan data if not expired.

        Args:
            host_id: Host ID to get cache for.
            scan_type: Type of scan (e.g., 'nmap', 'ports').

        Returns:
            Cache dictionary with parsed data, or None if not found/expired.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT id, host_id, scan_type, data, ttl_seconds, created_at, expires_at
                    FROM scan_cache
                    WHERE host_id = ? AND scan_type = ? AND expires_at > ?
                """, (host_id, scan_type, datetime.now(timezone.utc).isoformat()))
                row = cursor.fetchone()
                if row:
                    result = self._row_to_dict(row)
                    try:
                        result["data"] = json.loads(result["data"])
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(
                            "Failed to parse scan cache JSON for host_id=%s, scan_type=%s: %s",
                            host_id, scan_type, e
                        )
                        result["data"] = None
                    return result
                return None
            finally:
                cursor.close()

    def save_scan_cache(
        self,
        host_id: int,
        scan_type: str,
        data: Dict,
        ttl_seconds: int,
    ) -> None:
        """Save scan data to cache.

        Args:
            host_id: Host ID to cache for.
            scan_type: Type of scan.
            data: Scan data dictionary.
            ttl_seconds: Time to live in seconds.

        Raises:
            ValueError: If any input parameter is invalid.
        """
        # Validate host_id
        if not isinstance(host_id, int) or host_id <= 0:
            raise ValueError(f"host_id must be a positive integer, got: {host_id!r}")

        # Validate scan_type
        if not isinstance(scan_type, str):
            raise ValueError(f"scan_type must be a string, got: {type(scan_type).__name__}")
        scan_type_stripped = scan_type.strip()
        if not scan_type_stripped:
            raise ValueError("scan_type must be a non-empty string after stripping whitespace")

        # Validate data
        if data is None:
            raise ValueError("data must not be None")
        if not isinstance(data, dict):
            raise ValueError(f"data must be a dict/mapping, got: {type(data).__name__}")

        # Validate ttl_seconds
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be a positive integer, got: {ttl_seconds!r}")

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO scan_cache
                    (host_id, scan_type, data, ttl_seconds, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    host_id,
                    scan_type_stripped,
                    json.dumps(data),
                    ttl_seconds,
                    now.isoformat(),
                    expires_at.isoformat(),
                ))
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                logger.error(
                    "Failed to save scan cache for host_id=%s, scan_type=%s: %s",
                    host_id, scan_type_stripped, e
                )
                raise
            finally:
                cursor.close()

    def delete_scan_cache(
        self,
        host_id: Optional[int] = None,
        scan_type: Optional[str] = None,
    ) -> None:
        """Delete scan cache entries.

        Args:
            host_id: Optional host ID to filter by.
            scan_type: Optional scan type to filter by.

        If neither argument provided, deletes all cache entries.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                if host_id is not None and scan_type is not None:
                    cursor.execute(
                        "DELETE FROM scan_cache WHERE host_id = ? AND scan_type = ?",
                        (host_id, scan_type)
                    )
                elif host_id is not None:
                    cursor.execute("DELETE FROM scan_cache WHERE host_id = ?", (host_id,))
                elif scan_type is not None:
                    cursor.execute("DELETE FROM scan_cache WHERE scan_type = ?", (scan_type,))
                else:
                    cursor.execute("DELETE FROM scan_cache")

                conn.commit()
            finally:
                cursor.close()

    def cleanup_expired_cache(self) -> int:
        """Remove all expired cache entries.

        Returns:
            Number of entries deleted.
        """
        deleted = 0
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "DELETE FROM scan_cache WHERE expires_at < ?",
                    (datetime.now(timezone.utc).isoformat(),)
                )
                deleted = cursor.rowcount
                conn.commit()
            finally:
                cursor.close()

        return deleted

    # Hostname-based convenience methods

    def set_scan_cache(
        self,
        hostname: str,
        scan_type: str,
        data: Dict,
        ttl_seconds: int,
    ) -> None:
        """Save scan cache by hostname (convenience method).

        Only caches data for hosts that exist in the inventory.
        For hosts not in inventory, the cache is memory-only (in CacheManager).

        Args:
            hostname: Hostname to cache for.
            scan_type: Type of scan.
            data: Scan data dictionary.
            ttl_seconds: Time to live in seconds.
        """
        host = self.get_host_by_name(hostname)
        if host:
            self.save_scan_cache(host["id"], scan_type, data, ttl_seconds)
        # If host not in inventory, skip persistent cache (use memory cache only)

    def get_scan_cache_by_hostname(
        self,
        hostname: str,
        scan_type: str,
    ) -> Optional[Dict[str, Any]]:
        """Get scan cache by hostname (convenience method).

        Args:
            hostname: Hostname to get cache for.
            scan_type: Type of scan.

        Returns:
            Cache dictionary or None if not found.
        """
        host = self.get_host_by_name(hostname)
        if host:
            return self.get_scan_cache(host["id"], scan_type)
        return None

    def clear_host_cache(self, hostname: str) -> None:
        """Clear all cached scan data for a hostname.

        Args:
            hostname: Hostname to clear cache for.
        """
        host = self.get_host_by_name(hostname)
        if host:
            self.delete_scan_cache(host_id=host["id"])
