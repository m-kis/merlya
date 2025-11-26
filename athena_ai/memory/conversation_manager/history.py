import time
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from athena_ai.memory.conversation_manager.models import Conversation, Message
from athena_ai.memory.conversation_manager.storage import ConversationStore, SQLiteStore
from athena_ai.utils.logger import logger


class HistoryManager:
    """Manages conversation history and persistence."""

    def __init__(self, env: str = "dev", store: Optional[ConversationStore] = None):
        self.env = env

        # Storage (default: SQLite)
        if store:
            self.store = store
        else:
            base_dir = Path.home() / ".athena" / env
            base_dir.mkdir(parents=True, exist_ok=True)
            self.store = SQLiteStore(base_dir / "sessions.db")

        # Load current conversation
        self.current_conversation: Optional[Conversation] = None
        self._load_or_create_current()

    def _load_or_create_current(self) -> None:
        """Load existing or create new conversation."""
        self.current_conversation = self.store.load_current()
        if not self.current_conversation:
            self.create_conversation()

    def create_conversation(self, title: Optional[str] = None) -> Conversation:
        """Create new conversation."""
        if self.current_conversation and self.current_conversation.messages:
            self.store.archive(self.current_conversation.id)

        conv_id = f"conv_{int(time.time())}"
        title = title or f"Conversation {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        self.current_conversation = Conversation(id=conv_id, title=title)
        self.store.save_conversation(self.current_conversation)
        logger.info(f"Created conversation: {conv_id}")

        return self.current_conversation

    def add_message(self, role: str, content: str) -> Message:
        """Add message to current conversation."""
        if not self.current_conversation:
            self.create_conversation()

        msg = self.current_conversation.add_message(role, content)
        self.store.save_message(self.current_conversation.id, msg)
        return msg

    def list_conversations(self, limit: int = 20) -> List[dict[str, Any]]:
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

    def save_current(self):
        """Save current conversation state."""
        if self.current_conversation:
            self.store.save_conversation(self.current_conversation)
