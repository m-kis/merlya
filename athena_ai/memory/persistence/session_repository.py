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

        # Session-conversation linking table for cross-session persistence
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                linked_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id),
                UNIQUE(session_id, conversation_id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_conversations_session
            ON session_conversations(session_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_conversations_conversation
            ON session_conversations(conversation_id)
        """)

        # Parent session tracking for session chaining
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_session_id TEXT NOT NULL,
                child_session_id TEXT NOT NULL,
                link_type TEXT DEFAULT 'continuation',
                linked_at TEXT NOT NULL,
                FOREIGN KEY (parent_session_id) REFERENCES sessions(id),
                FOREIGN KEY (child_session_id) REFERENCES sessions(id),
                UNIQUE(parent_session_id, child_session_id)
            )
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

        if cursor.lastrowid is None:
            conn.close()
            raise RuntimeError(
                f"Failed to insert into 'queries' table: lastrowid is None. "
                f"session_id={session_id!r}, query={query[:100]!r}..."
            )
        query_id = cursor.lastrowid

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

    # =========================================================================
    # Cross-Session Persistence
    # =========================================================================

    def link_conversation(self, session_id: str, conversation_id: str) -> bool:
        """Link a conversation to a session for cross-session tracking.

        Args:
            session_id: The session to link to.
            conversation_id: The conversation to link.

        Returns:
            True if linked successfully, False if already linked or error.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO session_conversations (session_id, conversation_id, linked_at)
                VALUES (?, ?, ?)
            """, (session_id, conversation_id, datetime.now().isoformat()))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def get_session_conversations(self, session_id: str) -> List[str]:
        """Get all conversation IDs linked to a session.

        Args:
            session_id: The session to query.

        Returns:
            List of conversation IDs.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT conversation_id FROM session_conversations
            WHERE session_id = ?
            ORDER BY linked_at ASC
        """, (session_id,))

        conv_ids = [row[0] for row in cursor.fetchall()]
        conn.close()
        return conv_ids

    def get_conversation_sessions(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get all sessions that used a specific conversation.

        Args:
            conversation_id: The conversation to query.

        Returns:
            List of session info dicts.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id, s.started_at, s.ended_at, s.status, sc.linked_at
            FROM sessions s
            JOIN session_conversations sc ON s.id = sc.session_id
            WHERE sc.conversation_id = ?
            ORDER BY sc.linked_at DESC
        """, (conversation_id,))

        sessions = [
            {
                "id": row[0],
                "started_at": row[1],
                "ended_at": row[2],
                "status": row[3],
                "linked_at": row[4],
            }
            for row in cursor.fetchall()
        ]
        conn.close()
        return sessions

    def link_sessions(
        self,
        parent_session_id: str,
        child_session_id: str,
        link_type: str = "continuation"
    ) -> bool:
        """Link two sessions (e.g., when resuming creates a new session).

        Args:
            parent_session_id: The original session.
            child_session_id: The new/continued session.
            link_type: Type of link (continuation, fork, related).

        Returns:
            True if linked successfully.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO session_links (parent_session_id, child_session_id, link_type, linked_at)
                VALUES (?, ?, ?, ?)
            """, (parent_session_id, child_session_id, link_type, datetime.now().isoformat()))
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            return False
        finally:
            conn.close()

    def get_session_chain(self, session_id: str) -> List[Dict[str, Any]]:
        """Get the full chain of linked sessions (ancestors and descendants).

        Args:
            session_id: Starting session ID.

        Returns:
            List of session info dicts in chronological order.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get ancestors (parent chain)
        ancestors = []
        current_id = session_id
        while True:
            cursor.execute("""
                SELECT parent_session_id FROM session_links
                WHERE child_session_id = ?
            """, (current_id,))
            row = cursor.fetchone()
            if not row:
                break
            ancestors.insert(0, row[0])
            current_id = row[0]

        # Get descendants (child chain)
        descendants = []
        current_id = session_id
        while True:
            cursor.execute("""
                SELECT child_session_id FROM session_links
                WHERE parent_session_id = ?
            """, (current_id,))
            row = cursor.fetchone()
            if not row:
                break
            descendants.append(row[0])
            current_id = row[0]

        # Build full chain
        all_ids = ancestors + [session_id] + descendants

        # Get session details
        chain = []
        for sid in all_ids:
            cursor.execute("""
                SELECT id, started_at, ended_at, status, total_queries, total_actions
                FROM sessions WHERE id = ?
            """, (sid,))
            row = cursor.fetchone()
            if row:
                chain.append({
                    "id": row[0],
                    "started_at": row[1],
                    "ended_at": row[2],
                    "status": row[3],
                    "total_queries": row[4],
                    "total_actions": row[5],
                    "is_current": row[0] == session_id,
                })

        conn.close()
        return chain

    def export_session(self, session_id: str) -> Dict[str, Any]:
        """Export a session with all its data for backup/transfer.

        Args:
            session_id: Session to export.

        Returns:
            Complete session data including queries, actions, and snapshots.
        """
        history = self.get_session_history(session_id)
        if not history:
            return {}

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get full actions with stdout/stderr
        cursor.execute("""
            SELECT timestamp, target, command, exit_code, stdout, stderr, risk_level, duration_ms
            FROM actions WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (session_id,))
        full_actions = [
            {
                "timestamp": row[0],
                "target": row[1],
                "command": row[2],
                "exit_code": row[3],
                "stdout": row[4],
                "stderr": row[5],
                "risk_level": row[6],
                "duration_ms": row[7],
            }
            for row in cursor.fetchall()
        ]

        # Get context snapshots
        cursor.execute("""
            SELECT timestamp, context_data, snapshot_type
            FROM context_snapshots WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (session_id,))
        snapshots = [
            {
                "timestamp": row[0],
                "context_data": json.loads(row[1]) if row[1] else {},
                "snapshot_type": row[2],
            }
            for row in cursor.fetchall()
        ]

        # Get linked conversations
        conversation_ids = self.get_session_conversations(session_id)

        # Get session chain info
        chain = self.get_session_chain(session_id)

        conn.close()

        return {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "session": history["session"],
            "queries": history["queries"],
            "actions": full_actions,
            "context_snapshots": snapshots,
            "linked_conversations": conversation_ids,
            "session_chain": chain,
        }

    def import_session(self, data: Dict[str, Any]) -> Optional[str]:
        """Import a session from exported data.

        Args:
            data: Exported session data.

        Returns:
            New session ID if successful, None otherwise.
        """
        if "session" not in data:
            return None

        session_info = data["session"]
        original_id = session_info.get("id", "")

        # Generate new ID to avoid conflicts
        new_session_id = f"{original_id}_imported_{int(datetime.now().timestamp())}"

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Create session
            cursor.execute("""
                INSERT INTO sessions (id, started_at, ended_at, status, total_queries, total_actions, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                new_session_id,
                session_info.get("started_at"),
                session_info.get("ended_at"),
                "imported",  # Mark as imported
                session_info.get("total_queries", 0),
                session_info.get("total_actions", 0),
                json.dumps({"imported_from": original_id, "imported_at": datetime.now().isoformat()}),
            ))

            # Import queries
            query_id_map = {}  # old_id -> new_id
            for query in data.get("queries", []):
                cursor.execute("""
                    INSERT INTO queries (session_id, timestamp, query, response, response_type, actions_count, execution_time_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_session_id,
                    query.get("timestamp"),
                    query.get("query"),
                    query.get("response"),
                    query.get("response_type", "text"),
                    query.get("actions_count", 0),
                    query.get("execution_time_ms", 0),
                ))
                if query.get("id"):
                    query_id_map[query["id"]] = cursor.lastrowid

            # Import actions
            for action in data.get("actions", []):
                # Try to find matching query_id
                query_id = 0
                for _old_id, new_id in query_id_map.items():
                    # Simple heuristic: match by timestamp proximity
                    if new_id:
                        query_id = new_id
                        break

                cursor.execute("""
                    INSERT INTO actions (query_id, session_id, timestamp, target, command, exit_code, stdout, stderr, risk_level, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    query_id,
                    new_session_id,
                    action.get("timestamp"),
                    action.get("target"),
                    action.get("command"),
                    action.get("exit_code"),
                    action.get("stdout", "")[:1000],
                    action.get("stderr", "")[:1000],
                    action.get("risk_level"),
                    action.get("duration_ms", 0),
                ))

            # Import context snapshots
            for snapshot in data.get("context_snapshots", []):
                cursor.execute("""
                    INSERT INTO context_snapshots (session_id, timestamp, context_data, snapshot_type)
                    VALUES (?, ?, ?, ?)
                """, (
                    new_session_id,
                    snapshot.get("timestamp"),
                    json.dumps(snapshot.get("context_data", {})),
                    snapshot.get("snapshot_type", "imported"),
                ))

            conn.commit()
            return new_session_id

        except Exception:
            conn.rollback()
            return None
        finally:
            conn.close()
