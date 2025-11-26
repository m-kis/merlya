"""
Unified Conversation Manager with pluggable storage backends.

Consolidates conversation_manager.py and conversation_manager_sqlite.py
following DRY and Strategy pattern principles.
"""
from typing import Any, Callable, List, Optional

from athena_ai.memory.conversation_manager.context import ContextManager
from athena_ai.memory.conversation_manager.history import HistoryManager
from athena_ai.memory.conversation_manager.models import Conversation
from athena_ai.memory.conversation_manager.storage import ConversationStore
from athena_ai.utils.logger import logger


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
        store: Optional[ConversationStore] = None,
    ):
        self.env = env

        # Initialize History Manager
        self.history = HistoryManager(env, store)

        # Initialize Context Manager
        self.context = ContextManager(self.history, token_limit, compact_threshold)

    @property
    def current_conversation(self) -> Optional[Conversation]:
        return self.history.current_conversation

    def create_conversation(self, title: Optional[str] = None) -> Conversation:
        """Create new conversation."""
        return self.history.create_conversation(title)

    # Alias for compatibility
    def start_new_conversation(self, title: Optional[str] = None) -> str:
        return self.create_conversation(title).id

    def add_user_message(self, content: str) -> None:
        """Add user message."""
        self.history.add_message("user", content)

        if self.context.should_compact():
            logger.warning(f"Approaching token limit ({self.context.get_current_tokens()}/{self.context.token_limit})")

    def add_assistant_message(self, content: str) -> None:
        """Add assistant message."""
        self.history.add_message("assistant", content)

    def should_compact(self) -> bool:
        """Check if approaching token limit."""
        return self.context.should_compact()

    def must_compact(self) -> bool:
        """Check if at token limit."""
        return self.context.must_compact()

    def compact_conversation(self, llm_summarizer: Optional[Callable] = None) -> bool:
        """Compact conversation using summarization."""
        return self.context.compact_conversation(llm_summarizer)

    def list_conversations(self, limit: int = 20) -> List[dict[str, Any]]:
        """List all conversations."""
        return self.history.list_conversations(limit)

    def load_conversation(self, conv_id: str) -> bool:
        """Load and switch to conversation."""
        return self.history.load_conversation(conv_id)

    def delete_conversation(self, conv_id: str) -> bool:
        """Delete conversation."""
        return self.history.delete_conversation(conv_id)

    def get_current_tokens(self) -> int:
        """Get current token count."""
        return self.context.get_current_tokens()

    def get_token_usage_percent(self) -> float:
        """Get token usage percentage."""
        return self.context.get_token_usage_percent()


# =============================================================================
# Backward Compatibility
# =============================================================================

# The class name is the same, so existing imports work
# SQLiteConversationManager is now just an alias
SQLiteConversationManager = ConversationManager
