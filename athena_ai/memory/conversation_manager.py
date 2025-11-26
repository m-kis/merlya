"""
Conversation Manager - Manages conversations with automatic compacting.

Like Claude Code:
- Each REPL session = one conversation
- Access to previous conversations
- Automatic compacting when approaching token limit
- Start fresh conversation when needed
"""
import json
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
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "token_count": self.token_count,
            "compacted": self.compacted
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        """Create from dict."""
        data = data.copy()
        data["messages"] = [Message.from_dict(m) for m in data["messages"]]
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


class ConversationManager:
    """
    Manages conversations with automatic compacting.

    Features:
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

        # Storage
        self.storage_dir = Path.home() / ".athena" / env / "conversations"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Current conversation
        self.current_conversation: Optional[Conversation] = None

        # Load or create conversation
        self._load_or_create_current()

    def _load_or_create_current(self):
        """Load existing current conversation or create new one."""
        current_file = self.storage_dir / "current.json"

        if current_file.exists():
            try:
                with open(current_file, 'r') as f:
                    data = json.load(f)
                    self.current_conversation = Conversation.from_dict(data)
                    logger.info(f"Loaded conversation: {self.current_conversation.id}")
                    return
            except Exception as e:
                logger.error(f"Failed to load current conversation: {e}")

        # Create new conversation
        self.start_new_conversation()

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

        self._save_current()
        logger.info(f"Started new conversation: {conv_id}")

        return conv_id

    def add_user_message(self, content: str):
        """Add user message to current conversation."""
        if not self.current_conversation:
            self.start_new_conversation()

        self.current_conversation.add_message("user", content)
        self._save_current()

        # Check if we need to compact
        if self.should_compact():
            logger.warning(f"Conversation approaching token limit ({self.current_conversation.token_count}/{self.token_limit})")

    def add_assistant_message(self, content: str):
        """Add assistant message to current conversation."""
        if not self.current_conversation:
            self.start_new_conversation()

        self.current_conversation.add_message("assistant", content)
        self._save_current()

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
            self.current_conversation.compacted = True
            self._save_current()

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
            "ansible", "deploy", "restart", "install", "configure"
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
        conversations = []

        # Add current conversation
        if self.current_conversation and self.current_conversation.messages:
            conversations.append({
                "id": self.current_conversation.id,
                "title": self.current_conversation.title,
                "message_count": len(self.current_conversation.messages),
                "token_count": self.current_conversation.token_count,
                "created_at": self.current_conversation.created_at.isoformat(),
                "updated_at": self.current_conversation.updated_at.isoformat(),
                "current": True
            })

        # Add archived conversations
        for conv_file in sorted(self.storage_dir.glob("conv_*.json"), reverse=True):
            if len(conversations) >= limit:
                break

            try:
                with open(conv_file, 'r') as f:
                    data = json.load(f)
                    conversations.append({
                        "id": data["id"],
                        "title": data["title"],
                        "message_count": len(data["messages"]),
                        "token_count": data["token_count"],
                        "created_at": data["created_at"],
                        "updated_at": data["updated_at"],
                        "current": False
                    })
            except Exception as e:
                logger.error(f"Failed to read conversation {conv_file}: {e}")

        return conversations

    def load_conversation(self, conv_id: str) -> Optional[Conversation]:
        """
        Load a specific conversation.

        Args:
            conv_id: Conversation ID

        Returns:
            Conversation or None if not found
        """
        # Check current
        if self.current_conversation and self.current_conversation.id == conv_id:
            return self.current_conversation

        # Check archived
        conv_file = self.storage_dir / f"{conv_id}.json"
        if not conv_file.exists():
            logger.warning(f"Conversation not found: {conv_id}")
            return None

        try:
            with open(conv_file, 'r') as f:
                data = json.load(f)
                return Conversation.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load conversation {conv_id}: {e}")
            return None

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
            self._save_current()
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

        conv_file = self.storage_dir / f"{conv_id}.json"
        if conv_file.exists():
            try:
                conv_file.unlink()
                logger.info(f"Deleted conversation: {conv_id}")
                return True
            except Exception as e:
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

    def _save_current(self):
        """Save current conversation."""
        if not self.current_conversation:
            return

        current_file = self.storage_dir / "current.json"
        try:
            with open(current_file, 'w') as f:
                json.dump(self.current_conversation.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save current conversation: {e}")

    def _archive_current(self):
        """Archive current conversation."""
        if not self.current_conversation:
            return

        archive_file = self.storage_dir / f"{self.current_conversation.id}.json"
        try:
            with open(archive_file, 'w') as f:
                json.dump(self.current_conversation.to_dict(), f, indent=2)
            logger.info(f"Archived conversation: {self.current_conversation.id}")
        except Exception as e:
            logger.error(f"Failed to archive conversation: {e}")
