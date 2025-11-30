import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from athena_ai.memory.conversation_manager.models import Conversation, Message
from athena_ai.utils.logger import logger

# Export format version for forward compatibility
EXPORT_VERSION = "1.0"


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

    @abstractmethod
    def export_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Export conversation to portable format for backup/transfer."""
        pass

    @abstractmethod
    def import_conversation(self, data: Dict[str, Any]) -> Optional[str]:
        """Import conversation from portable format. Returns conversation ID or None on failure."""
        pass

    @abstractmethod
    def export_all(self) -> Dict[str, Any]:
        """Export all conversations to portable format."""
        pass


class SQLiteStore(ConversationStore):
    """SQLite-based conversation storage."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections with proper cleanup."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")  # Enable FK enforcement
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        """Ensure database schema exists."""
        with self._connection() as conn:
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

    def save_conversation(self, conversation: Conversation) -> None:
        with self._connection() as conn:
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

    def save_message(self, conversation_id: str, message: Message) -> None:
        with self._connection() as conn:
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

    def load_conversation(self, conversation_id: str) -> Optional[Conversation]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, created_at, updated_at, token_count, compacted
                FROM conversations WHERE id = ?
            """, (conversation_id,))

            row = cursor.fetchone()
            if not row:
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

            return conversation

    def load_current(self) -> Optional[Conversation]:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM conversations WHERE is_current = 1 LIMIT 1")
            row = cursor.fetchone()

        if row:
            return self.load_conversation(row[0])
        return None

    def set_current(self, conversation_id: str) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE conversations SET is_current = 0")
            cursor.execute("UPDATE conversations SET is_current = 1 WHERE id = ?", (conversation_id,))
            conn.commit()

    def archive(self, conversation_id: str) -> None:
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE conversations SET is_current = 0 WHERE id = ?", (conversation_id,))
            conn.commit()

    def delete(self, conversation_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.cursor()
            # Delete conversation first - messages are deleted by CASCADE
            cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def list_all(self, limit: int = 20) -> List[dict[str, Any]]:
        with self._connection() as conn:
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

            return [
                {
                    "id": row[0], "title": row[1], "created_at": row[2], "updated_at": row[3],
                    "token_count": row[4], "current": bool(row[5]), "message_count": row[6],
                }
                for row in cursor.fetchall()
            ]

    def export_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Export a single conversation to portable format."""
        conv = self.load_conversation(conversation_id)
        if not conv:
            return None

        return {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(),
            "conversation": conv.to_dict(),
        }

    def import_conversation(self, data: Dict[str, Any]) -> Optional[str]:
        """Import conversation from portable format.

        Args:
            data: Exported conversation data with version and conversation fields.

        Returns:
            Conversation ID if successful, None otherwise.
        """
        if "conversation" not in data:
            logger.warning("Import failed: missing 'conversation' field in data")
            return None

        conv_data = data["conversation"]

        # Handle version migrations if needed
        version = data.get("version", "1.0")
        if version != EXPORT_VERSION:
            # Future: add migration logic here
            logger.debug(f"Importing conversation from version {version}")

        try:
            conversation = Conversation.from_dict(conv_data)

            # Check if conversation with same ID exists
            existing = self.load_conversation(conversation.id)
            if existing:
                # Generate new ID using UUID to avoid collisions
                conversation.id = f"conv_{uuid.uuid4().hex[:12]}_imported"

            # Save conversation with proper connection management
            with self._connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO conversations (id, title, created_at, updated_at, token_count, compacted, is_current)
                    VALUES (?, ?, ?, ?, ?, ?, 0)
                """, (
                    conversation.id,
                    conversation.title,
                    conversation.created_at.isoformat(),
                    conversation.updated_at.isoformat(),
                    conversation.token_count,
                    1 if conversation.compacted else 0,
                ))

                # Save all messages
                for msg in conversation.messages:
                    cursor.execute("""
                        INSERT INTO messages (conversation_id, role, content, timestamp, tokens)
                        VALUES (?, ?, ?, ?, ?)
                    """, (conversation.id, msg.role, msg.content, msg.timestamp.isoformat(), msg.tokens))

                conn.commit()
            return conversation.id

        except Exception as e:
            logger.error(f"Failed to import conversation: {e}")
            return None

    def export_all(self) -> Dict[str, Any]:
        """Export all conversations to portable format."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM conversations ORDER BY updated_at DESC")
            conv_ids = [row[0] for row in cursor.fetchall()]

        conversations = []
        for conv_id in conv_ids:
            conv = self.load_conversation(conv_id)
            if conv:
                conversations.append(conv.to_dict())

        return {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(),
            "conversations": conversations,
            "count": len(conversations),
        }


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

    def export_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Export a single conversation to portable format."""
        conv = self.load_conversation(conversation_id)
        if not conv:
            return None

        return {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(),
            "conversation": conv.to_dict(),
        }

    def import_conversation(self, data: Dict[str, Any]) -> Optional[str]:
        """Import conversation from portable format."""
        if "conversation" not in data:
            return None

        try:
            conversation = Conversation.from_dict(data["conversation"])

            # Check if conversation with same ID exists
            existing_file = self.storage_dir / f"{conversation.id}.json"
            if existing_file.exists():
                import time
                conversation.id = f"conv_{int(time.time())}_imported"

            # Save to file
            conv_file = self.storage_dir / f"{conversation.id}.json"
            with open(conv_file, 'w') as f:
                json.dump(conversation.to_dict(), f, indent=2)

            return conversation.id
        except Exception:
            return None

    def export_all(self) -> Dict[str, Any]:
        """Export all conversations to portable format."""
        conversations = []
        for conv_file in self.storage_dir.glob("conv_*.json"):
            with open(conv_file, 'r') as f:
                conversations.append(json.load(f))

        return {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(),
            "conversations": conversations,
            "count": len(conversations),
        }
