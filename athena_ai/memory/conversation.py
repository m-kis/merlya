"""
Unified Conversation Manager with pluggable storage backends.

Consolidates conversation_manager.py and conversation_manager_sqlite.py
following DRY and Strategy pattern principles.
"""
import json
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from athena_ai.utils.logger import logger

# =============================================================================
# Data Types (shared, DRY)
# =============================================================================

@dataclass
class Message:
    """Single message in conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "timestamp": self.timestamp.isoformat()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        data = data.copy()
        if isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple) -> "Message":
        """Create from DB row (id, conversation_id, role, content, timestamp, tokens)."""
        return cls(role=row[2], content=row[3], timestamp=datetime.fromisoformat(row[4]), tokens=row[5])


@dataclass
class Conversation:
    """A conversation thread."""
    id: str
    title: str
    messages: list[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    token_count: int = 0
    compacted: bool = False

    def add_message(self, role: str, content: str, tokens: int = 0) -> Message:
        """Add message to conversation."""
        if tokens == 0:
            tokens = len(content) // 4  # ~4 chars per token

        msg = Message(role=role, content=content, tokens=tokens)
        self.messages.append(msg)
        self.token_count += tokens
        self.updated_at = datetime.now()
        return msg

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "token_count": self.token_count,
            "compacted": self.compacted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        data = data.copy()
        data["messages"] = [Message.from_dict(m) for m in data["messages"]]
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


# =============================================================================
# Storage Interface (Strategy Pattern)
# =============================================================================

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
    def load_conversation(self, conversation_id: str) -> Conversation | None:
        """Load conversation by ID."""
        pass

    @abstractmethod
    def load_current(self) -> Conversation | None:
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
    def list_all(self, limit: int = 20) -> list[dict[str, Any]]:
        """List all conversations."""
        pass


# =============================================================================
# SQLite Storage (recommended)
# =============================================================================

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

    def load_conversation(self, conversation_id: str) -> Conversation | None:
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

    def load_current(self) -> Conversation | None:
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

    def list_all(self, limit: int = 20) -> list[dict[str, Any]]:
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


# =============================================================================
# JSON Storage (legacy, for migration)
# =============================================================================

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

    def load_conversation(self, conversation_id: str) -> Conversation | None:
        conv_file = self.storage_dir / f"{conversation_id}.json"
        if not conv_file.exists():
            return None
        with open(conv_file, 'r') as f:
            return Conversation.from_dict(json.load(f))

    def load_current(self) -> Conversation | None:
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

    def list_all(self, limit: int = 20) -> list[dict[str, Any]]:
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


# =============================================================================
# Unified Conversation Manager
# =============================================================================

class ConversationManager:
    """
    Manages conversations with automatic compacting.

    Features:
    - Pluggable storage backend (SQLite or JSON)
    - Automatic persistence
    - Token counting and limit enforcement
    - Compacting when approaching limit
    """

    def __init__(
        self,
        env: str = "dev",
        token_limit: int = 100000,
        compact_threshold: float = 0.8,
        store: ConversationStore | None = None,
    ):
        self.env = env
        self.token_limit = token_limit
        self.compact_threshold = compact_threshold

        # Storage (default: SQLite)
        if store:
            self.store = store
        else:
            base_dir = Path.home() / ".athena" / env
            base_dir.mkdir(parents=True, exist_ok=True)
            self.store = SQLiteStore(base_dir / "sessions.db")

        # Load current conversation
        self.current_conversation: Conversation | None = None
        self._load_or_create_current()

    def _load_or_create_current(self) -> None:
        """Load existing or create new conversation."""
        self.current_conversation = self.store.load_current()
        if not self.current_conversation:
            self.create_conversation()

    def create_conversation(self, title: str | None = None) -> Conversation:
        """Create new conversation."""
        if self.current_conversation and self.current_conversation.messages:
            self.store.archive(self.current_conversation.id)

        conv_id = f"conv_{int(time.time())}"
        title = title or f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        self.current_conversation = Conversation(id=conv_id, title=title)
        self.store.save_conversation(self.current_conversation)
        logger.info(f"Created conversation: {conv_id}")

        return self.current_conversation

    # Alias for compatibility
    def start_new_conversation(self, title: str | None = None) -> str:
        return self.create_conversation(title).id

    def add_user_message(self, content: str) -> None:
        """Add user message."""
        if not self.current_conversation:
            self.create_conversation()

        msg = self.current_conversation.add_message("user", content)
        self.store.save_message(self.current_conversation.id, msg)

        if self.should_compact():
            logger.warning(f"Approaching token limit ({self.current_conversation.token_count}/{self.token_limit})")

    def add_assistant_message(self, content: str) -> None:
        """Add assistant message."""
        if not self.current_conversation:
            self.create_conversation()

        msg = self.current_conversation.add_message("assistant", content)
        self.store.save_message(self.current_conversation.id, msg)

    def should_compact(self) -> bool:
        """Check if approaching token limit."""
        if not self.current_conversation:
            return False
        return self.current_conversation.token_count >= self.token_limit * self.compact_threshold

    def must_compact(self) -> bool:
        """Check if at token limit."""
        if not self.current_conversation:
            return False
        return self.current_conversation.token_count >= self.token_limit

    def compact_conversation(self, llm_summarizer: Callable | None = None) -> bool:
        """Compact conversation using summarization."""
        if not self.current_conversation or not self.current_conversation.messages:
            return False

        logger.info(f"Compacting conversation {self.current_conversation.id}")

        try:
            summary = llm_summarizer(self.current_conversation) if llm_summarizer else self._simple_summary()

            old_id = self.current_conversation.id
            self.store.archive(old_id)

            self.create_conversation(title=f"Continuation of {old_id}")
            self.current_conversation.add_message(
                "assistant",
                f"[SUMMARY OF PREVIOUS CONVERSATION]\n\n{summary}\n\n[END SUMMARY]",
            )
            self.current_conversation.compacted = True
            self.store.save_conversation(self.current_conversation)

            logger.info("Conversation compacted")
            return True
        except Exception as e:
            logger.error(f"Compact failed: {e}")
            return False

    def _simple_summary(self) -> str:
        """Generate simple summary without LLM."""
        conv = self.current_conversation
        user_msgs = sum(1 for m in conv.messages if m.role == "user")
        asst_msgs = sum(1 for m in conv.messages if m.role == "assistant")

        summary = f"""Previous conversation summary:
- Interactions: {user_msgs} user, {asst_msgs} assistant
- Tokens: {conv.token_count}
- Duration: {(conv.updated_at - conv.created_at).seconds // 60} minutes
"""
        if len(conv.messages) > 4:
            summary += "\nLast exchanges:\n"
            for msg in conv.messages[-4:]:
                preview = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                summary += f"  {msg.role}: {preview}\n"

        return summary

    def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        """List all conversations."""
        return self.store.list_all(limit)

    def load_conversation(self, conv_id: str) -> bool:
        """Load and switch to conversation."""
        if self.current_conversation and self.current_conversation.id == conv_id:
            return True

        conv = self.store.load_conversation(conv_id)
        if conv:
            if self.current_conversation:
                self.store.archive(self.current_conversation.id)
            self.current_conversation = conv
            self.store.set_current(conv_id)
            logger.info(f"Loaded conversation: {conv_id}")
            return True
        return False

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete conversation."""
        if self.current_conversation and self.current_conversation.id == conv_id:
            logger.warning("Cannot delete current conversation")
            return False
        return self.store.delete(conv_id)

    def get_current_tokens(self) -> int:
        """Get current token count."""
        return self.current_conversation.token_count if self.current_conversation else 0

    def get_token_usage_percent(self) -> float:
        """Get token usage percentage."""
        return (self.get_current_tokens() / self.token_limit) * 100


# =============================================================================
# Backward Compatibility
# =============================================================================

# The class name is the same, so existing imports work
# SQLiteConversationManager is now just an alias
SQLiteConversationManager = ConversationManager
