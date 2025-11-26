import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


class HostRepository:
    """
    Handles persistence for hosts, processes, inventory, and scans.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Initialize SQLite tables for hosts and inventory."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Hosts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hosts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT NOT NULL,
                ip_address TEXT,
                environment TEXT,
                role TEXT,
                service TEXT,
                status TEXT,
                last_seen TEXT NOT NULL,
                first_discovered TEXT NOT NULL,
                ssh_port INTEGER DEFAULT 22,
                metadata TEXT,
                UNIQUE(hostname, ip_address)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_hosts_environment
            ON hosts(environment, role)
        """)

        # Processes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS processes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                process_name TEXT NOT NULL,
                pid INTEGER,
                user TEXT,
                cpu_percent REAL,
                memory_percent REAL,
                status TEXT,
                command_line TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_processes_host
            ON processes(host_id, timestamp)
        """)

        # Inventory table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host_id INTEGER NOT NULL,
                inventory_type TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                category TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (host_id) REFERENCES hosts(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_inventory_host_type
            ON inventory(host_id, inventory_type, key)
        """)

        # Scans table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT DEFAULT 'running',
                hosts_scanned INTEGER DEFAULT 0,
                hosts_discovered INTEGER DEFAULT 0,
                error_message TEXT,
                metadata TEXT
            )
        """)

        conn.commit()
        conn.close()

    def add_or_update_host(
        self,
        hostname: str,
        ip_address: Optional[str] = None,
        environment: Optional[str] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        status: str = "active",
        ssh_port: int = 22,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add or update a host in the database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        now = datetime.now().isoformat()

        # Check if host exists
        cursor.execute("""
            SELECT id, first_discovered FROM hosts
            WHERE hostname = ? AND (ip_address = ? OR ip_address IS NULL)
        """, (hostname, ip_address))

        existing = cursor.fetchone()

        if existing:
            # Update existing host
            host_id = existing[0]

            cursor.execute("""
                UPDATE hosts
                SET environment = ?, role = ?, service = ?, status = ?,
                    last_seen = ?, ssh_port = ?, metadata = ?
                WHERE id = ?
            """, (
                environment, role, service, status, now, ssh_port,
                json.dumps(metadata or {}), host_id
            ))
        else:
            # Insert new host
            cursor.execute("""
                INSERT INTO hosts
                (hostname, ip_address, environment, role, service, status,
                 last_seen, first_discovered, ssh_port, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hostname, ip_address, environment, role, service, status,
                now, now, ssh_port, json.dumps(metadata or {})
            ))
            host_id = cursor.lastrowid

        conn.commit()
        conn.close()

        logger.debug(f"Added/updated host: {hostname} (ID: {host_id})")
        return host_id

    def get_hosts(
        self,
        environment: Optional[str] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query hosts from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM hosts WHERE 1=1"
        params = []

        if environment:
            query += " AND environment = ?"
            params.append(environment)

        if role:
            query += " AND role = ?"
            params.append(role)

        if service:
            query += " AND service = ?"
            params.append(service)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY last_seen DESC"

        cursor.execute(query, params)

        hosts = []
        for row in cursor.fetchall():
            hosts.append({
                "id": row[0],
                "hostname": row[1],
                "ip_address": row[2],
                "environment": row[3],
                "role": row[4],
                "service": row[5],
                "status": row[6],
                "last_seen": row[7],
                "first_discovered": row[8],
                "ssh_port": row[9],
                "metadata": json.loads(row[10]) if row[10] else {}
            })

        conn.close()
        return hosts

    def add_process(
        self,
        host_id: int,
        process_name: str,
        pid: Optional[int] = None,
        user: Optional[str] = None,
        cpu_percent: Optional[float] = None,
        memory_percent: Optional[float] = None,
        status: Optional[str] = None,
        command_line: Optional[str] = None
    ) -> int:
        """Add process information for a host."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO processes
            (host_id, process_name, pid, user, cpu_percent, memory_percent,
             status, command_line, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            host_id, process_name, pid, user, cpu_percent, memory_percent,
            status, command_line, datetime.now().isoformat()
        ))

        process_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return process_id

    def get_processes(
        self,
        host_id: Optional[int] = None,
        process_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query processes from database."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM processes WHERE 1=1"
        params = []

        if host_id:
            query += " AND host_id = ?"
            params.append(host_id)

        if process_name:
            query += " AND process_name LIKE ?"
            params.append(f"%{process_name}%")

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)

        processes = []
        for row in cursor.fetchall():
            processes.append({
                "id": row[0],
                "host_id": row[1],
                "process_name": row[2],
                "pid": row[3],
                "user": row[4],
                "cpu_percent": row[5],
                "memory_percent": row[6],
                "status": row[7],
                "command_line": row[8],
                "timestamp": row[9]
            })

        conn.close()
        return processes

    def add_inventory_item(
        self,
        host_id: int,
        inventory_type: str,
        key: str,
        value: Optional[str] = None,
        category: Optional[str] = None
    ) -> int:
        """Add inventory item for a host."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO inventory
            (host_id, inventory_type, key, value, category, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            host_id, inventory_type, key, value, category,
            datetime.now().isoformat()
        ))

        item_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return item_id

    def get_inventory(
        self,
        host_id: Optional[int] = None,
        inventory_type: Optional[str] = None,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query inventory items."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        query = "SELECT * FROM inventory WHERE 1=1"
        params = []

        if host_id:
            query += " AND host_id = ?"
            params.append(host_id)

        if inventory_type:
            query += " AND inventory_type = ?"
            params.append(inventory_type)

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY timestamp DESC"

        cursor.execute(query, params)

        items = []
        for row in cursor.fetchall():
            items.append({
                "id": row[0],
                "host_id": row[1],
                "inventory_type": row[2],
                "key": row[3],
                "value": row[4],
                "category": row[5],
                "timestamp": row[6]
            })

        conn.close()
        return items

    def start_scan(
        self,
        scan_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Record the start of a scan operation."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO scans
            (scan_type, started_at, status, metadata)
            VALUES (?, ?, 'running', ?)
        """, (
            scan_type,
            datetime.now().isoformat(),
            json.dumps(metadata or {})
        ))

        scan_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Started scan: {scan_type} (ID: {scan_id})")
        return scan_id

    def complete_scan(
        self,
        scan_id: int,
        hosts_scanned: int = 0,
        hosts_discovered: int = 0,
        error_message: Optional[str] = None
    ):
        """Mark a scan as complete."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        status = "failed" if error_message else "completed"

        cursor.execute("""
            UPDATE scans
            SET completed_at = ?, status = ?, hosts_scanned = ?,
                hosts_discovered = ?, error_message = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            status,
            hosts_scanned,
            hosts_discovered,
            error_message,
            scan_id
        ))

        conn.commit()
        conn.close()

        logger.info(f"Completed scan {scan_id}: {status}")

    def get_scans(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent scans."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM scans
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))

        scans = []
        for row in cursor.fetchall():
            scans.append({
                "id": row[0],
                "scan_type": row[1],
                "started_at": row[2],
                "completed_at": row[3],
                "status": row[4],
                "hosts_scanned": row[5],
                "hosts_discovered": row[6],
                "error_message": row[7],
                "metadata": json.loads(row[8]) if row[8] else {}
            })

        conn.close()
        return scans
