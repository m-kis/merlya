import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


class SessionManager:
    """
    Manages work sessions like Claude Code to never lose context.
    Stores all queries, responses, actions, and context in SQLite + Markdown.
    """

    def __init__(self, env: str = "dev"):
        self.env = env
        self.base_dir = Path.home() / ".athena" / env
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.base_dir / "sessions.db"
        self.sessions_md_dir = self.base_dir / "sessions"
        self.sessions_md_dir.mkdir(exist_ok=True)

        self.current_session_id: Optional[str] = None
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database with tables."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT DEFAULT 'active',
                total_queries INTEGER DEFAULT 0,
                total_actions INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)

        # Queries table (interactions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                response TEXT,
                response_type TEXT,
                actions_count INTEGER DEFAULT 0,
                execution_time_ms INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # Actions table (commands executed)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                target TEXT NOT NULL,
                command TEXT NOT NULL,
                exit_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                risk_level TEXT,
                duration_ms INTEGER,
                FOREIGN KEY (query_id) REFERENCES queries(id),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # Context snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS context_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                context_data TEXT NOT NULL,
                snapshot_type TEXT DEFAULT 'auto',
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)

        # Conversations table (replaces JSON files)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                token_count INTEGER DEFAULT 0,
                compacted INTEGER DEFAULT 0,
                is_current INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)

        # Messages table (conversation messages)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                tokens INTEGER DEFAULT 0,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, timestamp)
        """)

        # Hosts table (discovered/scanned hosts)
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

        # Processes table (process information from scans)
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

        # Inventory table (infrastructure inventory - comprehensive view)
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

        # Scans table (scan history)
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

        logger.debug(f"Session database initialized at {self.db_path}")

    def start_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Start a new work session."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session_id = session_id

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO sessions (id, started_at, status, metadata)
            VALUES (?, ?, 'active', ?)
        """, (session_id, datetime.now().isoformat(), json.dumps(metadata or {})))

        conn.commit()
        conn.close()

        # Create session markdown file
        self._create_session_md(session_id)

        logger.info(f"Started session: {session_id}")
        return session_id

    def _create_session_md(self, session_id: str):
        """Create a markdown file for the session."""
        md_path = self.sessions_md_dir / f"{session_id}.md"

        content = f"""# Athena Session - {session_id}

**Environment**: {self.env}
**Started**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Status**: Active

---

## Queries

"""
        md_path.write_text(content)

    def log_query(
        self,
        query: str,
        response: str,
        response_type: str = "text",
        actions_count: int = 0,
        execution_time_ms: int = 0
    ) -> int:
        """Log a user query and its response."""
        if not self.current_session_id:
            self.start_session()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO queries (session_id, timestamp, query, response, response_type, actions_count, execution_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            self.current_session_id,
            datetime.now().isoformat(),
            query,
            response,
            response_type,
            actions_count,
            execution_time_ms
        ))

        query_id = cursor.lastrowid

        # Update session stats
        cursor.execute("""
            UPDATE sessions
            SET total_queries = total_queries + 1
            WHERE id = ?
        """, (self.current_session_id,))

        conn.commit()
        conn.close()

        # Append to markdown
        self._append_to_session_md(query, response, actions_count)

        logger.debug(f"Logged query #{query_id} in session {self.current_session_id}")
        return query_id

    def _append_to_session_md(self, query: str, response: str, actions_count: int):
        """Append query/response to session markdown file."""
        md_path = self.sessions_md_dir / f"{self.current_session_id}.md"

        timestamp = datetime.now().strftime("%H:%M:%S")

        content = f"""
### {timestamp} - Query

**Q**: {query}

**A**:
```
{response}
```

**Actions executed**: {actions_count}

---

"""
        with open(md_path, 'a') as f:
            f.write(content)

    def log_action(
        self,
        query_id: int,
        target: str,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        risk_level: str,
        duration_ms: int = 0
    ):
        """Log an executed action."""
        if not self.current_session_id:
            logger.warning("No active session, cannot log action")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO actions (
                query_id, session_id, timestamp, target, command,
                exit_code, stdout, stderr, risk_level, duration_ms
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            query_id,
            self.current_session_id,
            datetime.now().isoformat(),
            target,
            command,
            exit_code,
            stdout[:1000],  # Limit stdout size
            stderr[:1000],  # Limit stderr size
            risk_level,
            duration_ms
        ))

        # Update session stats
        cursor.execute("""
            UPDATE sessions
            SET total_actions = total_actions + 1
            WHERE id = ?
        """, (self.current_session_id,))

        conn.commit()
        conn.close()

        logger.debug(f"Logged action: {command} on {target}")

    def save_context_snapshot(self, context_data: Dict[str, Any], snapshot_type: str = "auto"):
        """Save a snapshot of the current context."""
        if not self.current_session_id:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO context_snapshots (session_id, timestamp, context_data, snapshot_type)
            VALUES (?, ?, ?, ?)
        """, (
            self.current_session_id,
            datetime.now().isoformat(),
            json.dumps(context_data),
            snapshot_type
        ))

        conn.commit()
        conn.close()

        logger.debug(f"Saved context snapshot ({snapshot_type})")

    def end_session(self):
        """End the current session."""
        if not self.current_session_id:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE sessions
            SET ended_at = ?, status = 'completed'
            WHERE id = ?
        """, (datetime.now().isoformat(), self.current_session_id))

        conn.commit()
        conn.close()

        # Finalize markdown
        md_path = self.sessions_md_dir / f"{self.current_session_id}.md"
        with open(md_path, 'a') as f:
            f.write(f"\n\n---\n**Session ended**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        logger.info(f"Ended session: {self.current_session_id}")
        self.current_session_id = None

    def get_session_history(self, session_id: str) -> Dict[str, Any]:
        """Get full history of a session."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get session info
        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        session = cursor.fetchone()

        if not session:
            conn.close()
            return {}

        # Get queries
        cursor.execute("""
            SELECT id, timestamp, query, response, actions_count, execution_time_ms
            FROM queries
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (session_id,))
        queries = cursor.fetchall()

        # Get actions
        cursor.execute("""
            SELECT timestamp, target, command, exit_code, risk_level
            FROM actions
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (session_id,))
        actions = cursor.fetchall()

        conn.close()

        return {
            "session": {
                "id": session[0],
                "started_at": session[1],
                "ended_at": session[2],
                "status": session[3],
                "total_queries": session[4],
                "total_actions": session[5],
            },
            "queries": [
                {
                    "id": q[0],
                    "timestamp": q[1],
                    "query": q[2],
                    "response": q[3],
                    "actions_count": q[4],
                    "execution_time_ms": q[5],
                }
                for q in queries
            ],
            "actions": [
                {
                    "timestamp": a[0],
                    "target": a[1],
                    "command": a[2],
                    "exit_code": a[3],
                    "risk_level": a[4],
                }
                for a in actions
            ],
        }

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent sessions."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, started_at, ended_at, status, total_queries, total_actions
            FROM sessions
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,))

        sessions = cursor.fetchall()
        conn.close()

        return [
            {
                "id": s[0],
                "started_at": s[1],
                "ended_at": s[2],
                "status": s[3],
                "total_queries": s[4],
                "total_actions": s[5],
            }
            for s in sessions
        ]

    def resume_session(self, session_id: str) -> bool:
        """Resume a previous session."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT id, status FROM sessions WHERE id = ?", (session_id,))
        session = cursor.fetchone()

        if not session:
            conn.close()
            logger.error(f"Session {session_id} not found")
            return False

        # Reactivate session
        cursor.execute("""
            UPDATE sessions
            SET status = 'active', ended_at = NULL
            WHERE id = ?
        """, (session_id,))

        conn.commit()
        conn.close()

        self.current_session_id = session_id
        logger.info(f"Resumed session: {session_id}")
        return True

    def get_conversation_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent conversation history for current session.
        Used to provide context to the AI.

        Args:
            limit: Max number of recent exchanges to return

        Returns:
            List of {query, response, timestamp} dicts
        """
        if not self.current_session_id:
            return []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, query, response
            FROM queries
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (self.current_session_id, limit))

        rows = cursor.fetchall()
        conn.close()

        # Reverse to get chronological order (oldest first)
        history = []
        for row in reversed(rows):
            history.append({
                "timestamp": row[0],
                "query": row[1],
                "response": row[2][:500] if row[2] else ""  # Limit response length
            })

        return history

    def export_session_md(self, session_id: str, output_path: Optional[Path] = None) -> Path:
        """Export session to markdown file."""
        if not output_path:
            output_path = Path(f"session_{session_id}.md")

        history = self.get_session_history(session_id)

        content = f"""# Athena Session Export

**Session ID**: {session_id}
**Started**: {history['session']['started_at']}
**Ended**: {history['session']['ended_at'] or 'Active'}
**Total Queries**: {history['session']['total_queries']}
**Total Actions**: {history['session']['total_actions']}

---

## Query History

"""

        for query in history['queries']:
            content += f"""
### Query at {query['timestamp']}

**Q**: {query['query']}

**Response**:
```
{query['response'][:500]}...
```

**Actions**: {query['actions_count']} | **Time**: {query['execution_time_ms']}ms

---

"""

        content += "\n## Actions Log\n\n"
        for action in history['actions']:
            content += f"- `{action['timestamp']}` [{action['target']}] {action['command']} (exit: {action['exit_code']}, risk: {action['risk_level']})\n"

        output_path.write_text(content)
        logger.info(f"Session exported to {output_path}")
        return output_path

    # ========================================================================
    # Infrastructure Data Management (Hosts, Processes, Inventory, Scans)
    # ========================================================================

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
        """
        Add or update a host in the database.

        Args:
            hostname: Host name
            ip_address: IP address
            environment: Environment (prod, preprod, dev, etc.)
            role: Role (web, db, cache, etc.)
            service: Service type (nginx, postgres, etc.)
            status: Host status
            ssh_port: SSH port
            metadata: Additional metadata as dict

        Returns:
            Host ID
        """
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
            existing[1]

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
        """
        Query hosts from database.

        Args:
            environment: Filter by environment
            role: Filter by role
            service: Filter by service
            status: Filter by status

        Returns:
            List of host dicts
        """
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
        """
        Add process information for a host.

        Args:
            host_id: Host ID from hosts table
            process_name: Process name
            pid: Process ID
            user: User running the process
            cpu_percent: CPU usage percentage
            memory_percent: Memory usage percentage
            status: Process status
            command_line: Full command line

        Returns:
            Process ID
        """
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
        """
        Query processes from database.

        Args:
            host_id: Filter by host ID
            process_name: Filter by process name
            limit: Max results

        Returns:
            List of process dicts
        """
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
        """
        Add inventory item for a host.

        Args:
            host_id: Host ID
            inventory_type: Type (software, hardware, config, etc.)
            key: Item key
            value: Item value
            category: Category for grouping

        Returns:
            Inventory item ID
        """
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
        """
        Query inventory items.

        Args:
            host_id: Filter by host ID
            inventory_type: Filter by type
            category: Filter by category

        Returns:
            List of inventory items
        """
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
        """
        Record the start of a scan operation.

        Args:
            scan_type: Type of scan (ssh, nmap, discovery, etc.)
            metadata: Additional scan metadata

        Returns:
            Scan ID
        """
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
        """
        Mark a scan as complete.

        Args:
            scan_id: Scan ID
            hosts_scanned: Number of hosts scanned
            hosts_discovered: Number of new hosts discovered
            error_message: Error message if scan failed
        """
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
        """
        Get recent scans.

        Args:
            limit: Max number of scans to return

        Returns:
            List of scan dicts
        """
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
