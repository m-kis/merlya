"""
Host Database Schema.
"""

import sqlite3


def init_host_tables(cursor: sqlite3.Cursor) -> None:
    """Initialize hosts and host versions tables."""
    # Hosts v2 table (main host storage)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hosts_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL UNIQUE,
            ip_address TEXT,
            aliases TEXT,
            environment TEXT,
            groups TEXT,
            role TEXT,
            service TEXT,
            ssh_port INTEGER DEFAULT 22,
            status TEXT DEFAULT 'unknown',
            source_id INTEGER,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES inventory_sources(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hosts_v2_hostname ON hosts_v2(hostname)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hosts_v2_environment ON hosts_v2(environment)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hosts_v2_source ON hosts_v2(source_id)
    """)

    # Host versions table (versioning)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS host_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            changes TEXT NOT NULL,
            changed_by TEXT DEFAULT 'system',
            created_at TEXT NOT NULL,
            FOREIGN KEY (host_id) REFERENCES hosts_v2(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_host_versions_host ON host_versions(host_id, version)
    """)
