from dataclasses import dataclass
from typing import Optional


@dataclass
class AuditEntry:
    """An audit log entry."""
    id: Optional[int] = None
    timestamp: str = ""
    action: str = ""
    target: str = ""
    command: str = ""
    user: str = ""
    result: str = ""  # success, failure, error
    details: str = ""
    session_id: str = ""
    priority: str = ""  # P0, P1, P2, P3


@dataclass
class SessionRecord:
    """A session record."""
    id: str = ""
    started_at: str = ""
    ended_at: Optional[str] = None
    env: str = ""
    queries: int = 0
    commands: int = 0
    incidents: int = 0
    metadata: str = "{}"
