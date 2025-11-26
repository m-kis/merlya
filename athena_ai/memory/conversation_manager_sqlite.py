"""
Conversation Manager - SQLite-based implementation.

Manages conversations with automatic compacting, all stored in SQLite.
Replaces JSON-based storage for better performance and integration.
"""
import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from athena_ai.utils.logger import logger


@dataclass
class Message:
    """Single message in conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    tokens: int = 0  # Estimated tokens

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {
            **asdict(self),
            "timestamp": self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create from dict."""
        data = data.copy()
        if isinstance(data["timestamp"], str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    @classmethod
    def from_db_row(cls, row: tuple) -> "Message":
        """Create from database row (id, conversation_id, role, content, timestamp, tokens)."""
        return cls(
            role=row[2],
            content=row[3],
            timestamp=datetime.fromisoformat(row[4]),
            tokens=row[5]
        )


@dataclass
class Conversation:
    """A conversation thread."""
    id: str
    title: str
    messages: List[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    token_count: int = 0
    compacted: bool = False

    def add_message(self, role: str, content: str, tokens: int = 0):
        """Add message to conversation."""
        if tokens == 0:
            # Rough estimate: 1 token ≈ 4 characters
            tokens = len(content) // 4

        msg = Message(role=role, content=content, tokens=tokens)
        self.messages.append(msg)
        self.token_count += tokens
        self.updated_at = datetime.now()


class ConversationManager:
    """
    Manages conversations with automatic compacting - SQLite version.

    Features:
    - All conversations stored in SQLite (no JSON files)
    - Automatic conversation persistence
    - Token counting and limit enforcement
    - Automatic compacting when approaching limit
    - List/load/delete conversations
    - Generate conversation summaries
    """

    def __init__(
        self,
        env: str = "dev",
        token_limit: int = 100000,  # Compact at 100k tokens
        compact_threshold: float = 0.8  # Compact at 80% of limit
    ):
        """
        Initialize conversation manager.

        Args:
            env: Environment name
            token_limit: Maximum tokens before requiring compact
            compact_threshold: Percentage of limit to trigger compact warning
        """
        self.env = env
        self.token_limit = token_limit
        self.compact_threshold = compact_threshold

        # Storage - use same database as SessionManager
        self.base_dir = Path.home() / ".athena" / env
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / "sessions.db"

        # Current conversation
        self.current_conversation: Optional[Conversation] = None

        # Load or create conversation
        self._load_or_create_current()

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def _load_or_create_current(self):
        """Load existing current conversation or create new one."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Find current conversation
        cursor.execute("""
            SELECT id, title, created_at, updated_at, token_count, compacted
            FROM conversations
            WHERE is_current = 1
            LIMIT 1
        """)

        row = cursor.fetchone()

        if row:
            # Load conversation with messages
            conv_id = row[0]
            conversation = Conversation(
                id=conv_id,
                title=row[1],
                created_at=datetime.fromisoformat(row[2]),
                updated_at=datetime.fromisoformat(row[3]),
                token_count=row[4],
                compacted=bool(row[5])
            )

            # Load messages
            cursor.execute("""
                SELECT id, conversation_id, role, content, timestamp, tokens
                FROM messages
                WHERE conversation_id = ?
                ORDER BY timestamp ASC
            """, (conv_id,))

            for msg_row in cursor.fetchall():
                conversation.messages.append(Message.from_db_row(msg_row))

            self.current_conversation = conversation
            logger.info(f"Loaded conversation: {conv_id}")
        else:
            # Create new conversation
            self.start_new_conversation()

        conn.close()

    def start_new_conversation(self, title: Optional[str] = None) -> str:
        """
        Start a new conversation.

        Args:
            title: Optional conversation title

        Returns:
            Conversation ID
        """
        # Archive current conversation if exists
        if self.current_conversation and self.current_conversation.messages:
            self._archive_current()

        # Create new
        conv_id = f"conv_{int(time.time())}"
        if title is None:
            title = f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        self.current_conversation = Conversation(
            id=conv_id,
            title=title
        )

        # Save to database
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO conversations (id, title, created_at, updated_at, token_count, compacted, is_current)
            VALUES (?, ?, ?, ?, 0, 0, 1)
        """, (
            conv_id,
            title,
            self.current_conversation.created_at.isoformat(),
            self.current_conversation.updated_at.isoformat()
        ))

        conn.commit()
        conn.close()

        logger.info(f"Started new conversation: {conv_id}")
        return conv_id

    def add_user_message(self, content: str):
        """Add user message to current conversation."""
        if not self.current_conversation:
            self.start_new_conversation()

        self.current_conversation.add_message("user", content)
        self._save_message(self.current_conversation.messages[-1])
        self._update_conversation_stats()

        # Check if we need to compact
        if self.should_compact():
            logger.warning(
                f"Conversation approaching token limit "
                f"({self.current_conversation.token_count}/{self.token_limit})"
            )

    def add_assistant_message(self, content: str):
        """Add assistant message to current conversation."""
        if not self.current_conversation:
            self.start_new_conversation()

        self.current_conversation.add_message("assistant", content)
        self._save_message(self.current_conversation.messages[-1])
        self._update_conversation_stats()

    def _save_message(self, message: Message):
        """Save a message to database."""
        if not self.current_conversation:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO messages (conversation_id, role, content, timestamp, tokens)
            VALUES (?, ?, ?, ?, ?)
        """, (
            self.current_conversation.id,
            message.role,
            message.content,
            message.timestamp.isoformat(),
            message.tokens
        ))

        conn.commit()
        conn.close()

    def _update_conversation_stats(self):
        """Update conversation statistics in database."""
        if not self.current_conversation:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE conversations
            SET updated_at = ?, token_count = ?
            WHERE id = ?
        """, (
            self.current_conversation.updated_at.isoformat(),
            self.current_conversation.token_count,
            self.current_conversation.id
        ))

        conn.commit()
        conn.close()

    def should_compact(self) -> bool:
        """
        Check if conversation should be compacted.

        Returns:
            True if approaching token limit
        """
        if not self.current_conversation:
            return False

        threshold = self.token_limit * self.compact_threshold
        return self.current_conversation.token_count >= threshold

    def must_compact(self) -> bool:
        """
        Check if conversation MUST be compacted (at limit).

        Returns:
            True if at or over limit
        """
        if not self.current_conversation:
            return False

        return self.current_conversation.token_count >= self.token_limit

    def compact_conversation(self, llm_summarizer: Optional[callable] = None) -> bool:
        """
        Compact current conversation using summarization.

        Args:
            llm_summarizer: Optional function to generate summary via LLM

        Returns:
            True if compacted successfully
        """
        if not self.current_conversation or not self.current_conversation.messages:
            return False

        logger.info(f"Compacting conversation {self.current_conversation.id}")

        try:
            # Generate summary
            if llm_summarizer:
                summary = llm_summarizer(self.current_conversation)
            else:
                summary = self._generate_simple_summary(self.current_conversation)

            # Archive full conversation
            self._archive_current()

            # Start new conversation with summary
            old_id = self.current_conversation.id
            self.start_new_conversation(
                title=f"Continuation of {old_id}"
            )

            # Add summary as first message
            self.current_conversation.add_message(
                "assistant",
                f"[SUMMARY OF PREVIOUS CONVERSATION]\n\n{summary}\n\n[END SUMMARY]",
                tokens=len(summary) // 4
            )
            self._save_message(self.current_conversation.messages[-1])

            # Mark as compacted
            self.current_conversation.compacted = True

            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE conversations
                SET compacted = 1
                WHERE id = ?
            """, (self.current_conversation.id,))
            conn.commit()
            conn.close()

            self._update_conversation_stats()

            logger.info(f"Conversation compacted successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to compact conversation: {e}")
            return False

    def _generate_simple_summary(self, conversation: Conversation) -> str:
        """
        Generate simple summary without LLM.

        Args:
            conversation: Conversation to summarize

        Returns:
            Summary text
        """
        # Count messages
        user_msgs = [m for m in conversation.messages if m.role == "user"]
        assistant_msgs = [m for m in conversation.messages if m.role == "assistant"]

        # Extract key topics (simple heuristic)
        all_content = " ".join(m.content for m in conversation.messages)
        words = all_content.lower().split()

        # Find common infrastructure keywords
        keywords = {}
        infra_keywords = [
            "server", "nginx", "docker", "kubernetes", "terraform",
            "ansible", "deploy", "restart", "install", "configure",
            "host", "database", "mongodb", "postgresql", "mysql"
        ]

        for kw in infra_keywords:
            count = words.count(kw)
            if count > 0:
                keywords[kw] = count

        # Build summary
        summary = f"""Previous conversation summary:
- Total interactions: {len(user_msgs)} user requests, {len(assistant_msgs)} responses
- Total tokens: {conversation.token_count}
- Started: {conversation.created_at.strftime('%Y-%m-%d %H:%M')}
- Duration: {(conversation.updated_at - conversation.created_at).seconds // 60} minutes
"""

        if keywords:
            top_keywords = sorted(keywords.items(), key=lambda x: x[1], reverse=True)[:5]
            summary += "\nMain topics discussed:\n"
            for kw, count in top_keywords:
                summary += f"  - {kw} (mentioned {count} times)\n"

        # Add last few interactions
        last_n = 3
        if len(conversation.messages) > last_n * 2:
            summary += f"\nLast {last_n} interactions:\n"
            for msg in conversation.messages[-(last_n * 2):]:
                role_label = "User" if msg.role == "user" else "Assistant"
                content_preview = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                summary += f"  {role_label}: {content_preview}\n"

        return summary

    def list_conversations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        List all saved conversations.

        Args:
            limit: Maximum number to return

        Returns:
            List of conversation metadata
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                c.id, c.title, c.created_at, c.updated_at,
                c.token_count, c.is_current, COUNT(m.id) as message_count
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
        """, (limit,))

        conversations = []
        for row in cursor.fetchall():
            conversations.append({
                "id": row[0],
                "title": row[1],
                "created_at": row[2],
                "updated_at": row[3],
                "token_count": row[4],
                "current": bool(row[5]),
                "message_count": row[6]
            })

        conn.close()
        return conversations

    def load_conversation(self, conv_id: str) -> Optional[Conversation]:
        """
        Load a specific conversation.

        Args:
            conv_id: Conversation ID

        Returns:
            Conversation or None if not found
        """
        # Check if it's current
        if self.current_conversation and self.current_conversation.id == conv_id:
            return self.current_conversation

        conn = self._get_connection()
        cursor = conn.cursor()

        # Load conversation
        cursor.execute("""
            SELECT id, title, created_at, updated_at, token_count, compacted
            FROM conversations
            WHERE id = ?
        """, (conv_id,))

        row = cursor.fetchone()
        if not row:
            conn.close()
            logger.warning(f"Conversation not found: {conv_id}")
            return None

        conversation = Conversation(
            id=row[0],
            title=row[1],
            created_at=datetime.fromisoformat(row[2]),
            updated_at=datetime.fromisoformat(row[3]),
            token_count=row[4],
            compacted=bool(row[5])
        )

        # Load messages
        cursor.execute("""
            SELECT id, conversation_id, role, content, timestamp, tokens
            FROM messages
            WHERE conversation_id = ?
            ORDER BY timestamp ASC
        """, (conv_id,))

        for msg_row in cursor.fetchall():
            conversation.messages.append(Message.from_db_row(msg_row))

        conn.close()
        return conversation

    def switch_to_conversation(self, conv_id: str) -> bool:
        """
        Switch to a different conversation.

        Args:
            conv_id: Conversation ID to switch to

        Returns:
            True if successful
        """
        # Archive current
        if self.current_conversation and self.current_conversation.messages:
            self._archive_current()

        # Load target conversation
        conversation = self.load_conversation(conv_id)

        if conversation:
            self.current_conversation = conversation

            # Mark as current in database
            conn = self._get_connection()
            cursor = conn.cursor()

            # Clear all current flags
            cursor.execute("UPDATE conversations SET is_current = 0")

            # Set this one as current
            cursor.execute("""
                UPDATE conversations SET is_current = 1 WHERE id = ?
            """, (conv_id,))

            conn.commit()
            conn.close()

            logger.info(f"Switched to conversation: {conv_id}")
            return True

        return False

    def delete_conversation(self, conv_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            conv_id: Conversation ID

        Returns:
            True if deleted
        """
        # Can't delete current
        if self.current_conversation and self.current_conversation.id == conv_id:
            logger.warning("Cannot delete current conversation")
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # Delete conversation (messages will cascade delete)
            cursor.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

            if cursor.rowcount > 0:
                conn.commit()
                conn.close()
                logger.info(f"Deleted conversation: {conv_id}")
                return True
            else:
                conn.close()
                return False

        except Exception as e:
            conn.close()
            logger.error(f"Failed to delete conversation {conv_id}: {e}")
            return False

    def get_current_tokens(self) -> int:
        """Get token count of current conversation."""
        if not self.current_conversation:
            return 0
        return self.current_conversation.token_count

    def get_token_usage_percent(self) -> float:
        """Get token usage as percentage of limit."""
        if not self.current_conversation:
            return 0.0
        return (self.current_conversation.token_count / self.token_limit) * 100

    def _archive_current(self):
        """Archive current conversation (mark as not current)."""
        if not self.current_conversation:
            return

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE conversations
            SET is_current = 0
            WHERE id = ?
        """, (self.current_conversation.id,))

        conn.commit()
        conn.close()

        logger.info(f"Archived conversation: {self.current_conversation.id}")
