"""
Scan Cache Repository Mixin - Manages scan result caching.

Handles caching of scan results (nmap, ports, services, etc.) with TTL support.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


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
            CREATE INDEX IF NOT EXISTS idx_scan_cache_host ON scan_cache(host_id, scan_type)
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
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM scan_cache
            WHERE host_id = ? AND scan_type = ? AND expires_at > ?
        """, (host_id, scan_type, datetime.now().isoformat()))

        row = cursor.fetchone()
        conn.close()

        if row:
            result = self._row_to_dict(row)
            result["data"] = json.loads(result["data"])
            return result
        return None

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
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        expires_at = now + timedelta(seconds=ttl_seconds)

        cursor.execute("""
            INSERT OR REPLACE INTO scan_cache
            (host_id, scan_type, data, ttl_seconds, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            host_id,
            scan_type,
            json.dumps(data),
            ttl_seconds,
            now.isoformat(),
            expires_at.isoformat(),
        ))

        conn.commit()
        conn.close()

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
        conn = self._get_connection()
        cursor = conn.cursor()

        if host_id and scan_type:
            cursor.execute(
                "DELETE FROM scan_cache WHERE host_id = ? AND scan_type = ?",
                (host_id, scan_type)
            )
        elif host_id:
            cursor.execute("DELETE FROM scan_cache WHERE host_id = ?", (host_id,))
        elif scan_type:
            cursor.execute("DELETE FROM scan_cache WHERE scan_type = ?", (scan_type,))
        else:
            cursor.execute("DELETE FROM scan_cache")

        conn.commit()
        conn.close()

    def cleanup_expired_cache(self) -> int:
        """Remove all expired cache entries.

        Returns:
            Number of entries deleted.
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM scan_cache WHERE expires_at < ?", (datetime.now().isoformat(),))
        deleted = cursor.rowcount

        conn.commit()
        conn.close()

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
