import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from athena_ai.memory.conversation_manager.models import Conversation, Message


class ConversationStore(ABC):
    """Abstract interface for conversation storage."""

    @abstractmethod
    def save_conversation(self, conversation: Conversation) -> None:
        """Save/update conversation."""
        pass

    @abstractmethod
    def save_message(self, conversation_id: str, message: Message) -> None:
        """Save single message."""
        pass

    @abstractmethod
    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Load conversation by ID."""
        pass

    @abstractmethod
    def load_current(self) -> Optional[Conversation]:
        """Load current active conversation."""
        pass

    @abstractmethod
    def set_current(self, conversation_id: str) -> None:
        """Set conversation as current."""
        pass

    @abstractmethod
    def archive(self, conversation_id: str) -> None:
        """Archive conversation (mark as not current)."""
        pass

    @abstractmethod
    def delete(self, conversation_id: str) -> bool:
        """Delete conversation."""
        pass

    @abstractmethod
    def list_all(self, limit: int = 20) -> List[dict[str, Any]]:
        """List all conversations."""
        pass


class SQLiteStore(ConversationStore):
    """SQLite-based conversation storage."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        """Ensure database schema exists."""
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TEXT,
                updated_at TEXT,
                token_count INTEGER DEFAULT 0,
                compacted INTEGER DEFAULT 0,
                is_current INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                timestamp TEXT,
                tokens INTEGER DEFAULT 0,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")
        conn.commit()
        conn.close()

    def save_conversation(self, conversation: Conversation) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO conversations (id, title, created_at, updated_at, token_count, compacted, is_current)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            conversation.id,
            conversation.title,
            conversation.created_at.isoformat(),
            conversation.updated_at.isoformat(),
            conversation.token_count,
            1 if conversation.compacted else 0,
        ))

        conn.commit()
        conn.close()

    def save_message(self, conversation_id: str, message: Message) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO messages (conversation_id, role, content, timestamp, tokens)
            VALUES (?, ?, ?, ?, ?)
        """, (conversation_id, message.role, message.content, message.timestamp.isoformat(), message.tokens))

        # Update conversation stats
        cursor.execute("""
            UPDATE conversations SET updated_at = ?, token_count = token_count + ? WHERE id = ?
        """, (datetime.now().isoformat(), message.tokens, conversation_id))

        conn.commit()
        conn.close()

    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, title, created_at, updated_at, token_count, compacted
            FROM conversations WHERE id = ?
        """, (conversation_id,))

        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        conversation = Conversation(
            id=row[0], title=row[1],
            created_at=datetime.fromisoformat(row[2]),
            updated_at=datetime.fromisoformat(row[3]),
            token_count=row[4], compacted=bool(row[5]),
        )

        # Load messages
        cursor.execute("""
            SELECT id, conversation_id, role, content, timestamp, tokens
            FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC
        """, (conversation_id,))

        for msg_row in cursor.fetchall():
            conversation.messages.append(Message.from_db_row(msg_row))

        conn.close()
        return conversation

    def load_current(self) -> Optional[Conversation]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM conversations WHERE is_current = 1 LIMIT 1")
        row = cursor.fetchone()
        conn.close()

        if row:
            return self.load_conversation(row[0])
        return None

    def set_current(self, conversation_id: str) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE conversations SET is_current = 0")
        cursor.execute("UPDATE conversations SET is_current = 1 WHERE id = ?", (conversation_id,))
        conn.commit()
        conn.close()

    def archive(self, conversation_id: str) -> None:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE conversations SET is_current = 0 WHERE id = ?", (conversation_id,))
        conn.commit()
        conn.close()

    def delete(self, conversation_id: str) -> bool:
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def list_all(self, limit: int = 20) -> List[dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at, c.token_count, c.is_current,
                   COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (limit,))

        conversations = [
            {
                "id": row[0], "title": row[1], "created_at": row[2], "updated_at": row[3],
                "token_count": row[4], "current": bool(row[5]), "message_count": row[6],
            }
            for row in cursor.fetchall()
        ]

        conn.close()
        return conversations


class JsonStore(ConversationStore):
    """JSON file-based conversation storage."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_conversation(self, conversation: Conversation) -> None:
        # Save as current
        current_file = self.storage_dir / "current.json"
        with open(current_file, 'w') as f:
            json.dump(conversation.to_dict(), f, indent=2)

    def save_message(self, conversation_id: str, message: Message) -> None:
        # JSON store saves full conversation, not individual messages
        pass

    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        conv_file = self.storage_dir / f"{conversation_id}.json"
        if not conv_file.exists():
            return None
        with open(conv_file, 'r') as f:
            return Conversation.from_dict(json.load(f))

    def load_current(self) -> Optional[Conversation]:
        current_file = self.storage_dir / "current.json"
        if not current_file.exists():
            return None
        with open(current_file, 'r') as f:
            return Conversation.from_dict(json.load(f))

    def set_current(self, conversation_id: str) -> None:
        conv = self.load_conversation(conversation_id)
        if conv:
            self.save_conversation(conv)

    def archive(self, conversation_id: str) -> None:
        current = self.load_current()
        if current and current.id == conversation_id:
            archive_file = self.storage_dir / f"{conversation_id}.json"
            with open(archive_file, 'w') as f:
                json.dump(current.to_dict(), f, indent=2)

    def delete(self, conversation_id: str) -> bool:
        conv_file = self.storage_dir / f"{conversation_id}.json"
        if conv_file.exists():
            conv_file.unlink()
            return True
        return False

    def list_all(self, limit: int = 20) -> List[dict[str, Any]]:
        conversations = []
        for conv_file in sorted(self.storage_dir.glob("conv_*.json"), reverse=True)[:limit]:
            with open(conv_file, 'r') as f:
                data = json.load(f)
                conversations.append({
                    "id": data["id"], "title": data["title"],
                    "created_at": data["created_at"], "updated_at": data["updated_at"],
                    "token_count": data["token_count"], "current": False,
                    "message_count": len(data["messages"]),
                })
        return conversations
