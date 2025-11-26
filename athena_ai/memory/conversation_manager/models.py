from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, List


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
    messages: List[Message] = field(default_factory=list)
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
