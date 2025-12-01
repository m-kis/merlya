from typing import Callable, Optional

from merlya.memory.conversation_manager.history import HistoryManager
from merlya.utils.logger import logger


class ContextManager:
    """Manages conversation context, token limits, and compacting."""

    def __init__(
        self,
        history_manager: HistoryManager,
        token_limit: int = 100000,
        compact_threshold: float = 0.8,
    ):
        self.history = history_manager
        self.token_limit = token_limit
        self.compact_threshold = compact_threshold

    def get_current_tokens(self) -> int:
        """Get current token count."""
        conv = self.history.current_conversation
        return conv.token_count if conv else 0

    def get_token_usage_percent(self) -> float:
        """Get token usage percentage."""
        return (self.get_current_tokens() / self.token_limit) * 100

    def should_compact(self) -> bool:
        """Check if approaching token limit."""
        conv = self.history.current_conversation
        if not conv:
            return False
        return conv.token_count >= self.token_limit * self.compact_threshold

    def must_compact(self) -> bool:
        """Check if at token limit."""
        conv = self.history.current_conversation
        if not conv:
            return False
        return conv.token_count >= self.token_limit

    def compact_conversation(self, llm_summarizer: Optional[Callable] = None) -> bool:
        """Compact conversation using summarization."""
        conv = self.history.current_conversation
        if not conv or not conv.messages:
            return False

        logger.info(f"Compacting conversation {conv.id}")

        try:
            summary = llm_summarizer(conv) if llm_summarizer else self._simple_summary()

            old_id = conv.id
            # Archive current is handled by create_conversation in HistoryManager
            # But we want to explicitly link them

            # Create new conversation
            new_conv = self.history.create_conversation(title=f"Continuation of {old_id}")

            # Add summary
            self.history.add_message(
                "assistant",
                f"[SUMMARY OF PREVIOUS CONVERSATION]\n\n{summary}\n\n[END SUMMARY]",
            )

            # Mark as compacted
            new_conv.compacted = True
            self.history.save_current()

            logger.info("Conversation compacted")
            return True
        except Exception as e:
            logger.error(f"Compact failed: {e}")
            return False

    def _simple_summary(self) -> str:
        """Generate simple summary without LLM."""
        conv = self.history.current_conversation
        if not conv:
            return ""

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
