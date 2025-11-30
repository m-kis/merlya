import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


class SessionRepository:
    """
    Handles persistence for sessions, queries, actions, and context snapshots.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Initialize SQLite tables for sessions."""
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

        # Queries table
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

        # Actions table
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

        conn.commit()
        conn.close()

    def start_session(self, session_id: str, metadata: Optional[Dict[str, Any]] = None):
        """Start a new work session."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO sessions (id, started_at, status, metadata)
            VALUES (?, ?, 'active', ?)
        """, (session_id, datetime.now().isoformat(), json.dumps(metadata or {})))

        conn.commit()
        conn.close()

    def log_query(
        self,
        session_id: str,
        query: str,
        response: str,
        response_type: str = "text",
        actions_count: int = 0,
        execution_time_ms: int = 0
    ) -> int:
        """Log a user query and its response."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO queries (session_id, timestamp, query, response, response_type, actions_count, execution_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            datetime.now().isoformat(),
            query,
            response,
            response_type,
            actions_count,
            execution_time_ms
        ))

        query_id = cursor.lastrowid or 0

        # Update session stats
        cursor.execute("""
            UPDATE sessions
            SET total_queries = total_queries + 1
            WHERE id = ?
        """, (session_id,))

        conn.commit()
        conn.close()

        return query_id

    def log_action(
        self,
        session_id: str,
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
            session_id,
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
        """, (session_id,))

        conn.commit()
        conn.close()

    def save_context_snapshot(self, session_id: str, context_data: Dict[str, Any], snapshot_type: str = "auto"):
        """Save a snapshot of the current context."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO context_snapshots (session_id, timestamp, context_data, snapshot_type)
            VALUES (?, ?, ?, ?)
        """, (
            session_id,
            datetime.now().isoformat(),
            json.dumps(context_data),
            snapshot_type
        ))

        conn.commit()
        conn.close()

    def end_session(self, session_id: str):
        """End the current session."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE sessions
            SET ended_at = ?, status = 'completed'
            WHERE id = ?
        """, (datetime.now().isoformat(), session_id))

        conn.commit()
        conn.close()

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
            return False

        # Reactivate session
        cursor.execute("""
            UPDATE sessions
            SET status = 'active', ended_at = NULL
            WHERE id = ?
        """, (session_id,))

        conn.commit()
        conn.close()
        return True

    def get_conversation_history(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent conversation history for current session."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT timestamp, query, response
            FROM queries
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (session_id, limit))

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
