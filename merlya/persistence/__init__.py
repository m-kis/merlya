"""
Merlya Persistence - SQLite storage layer.

Handles hosts, variables, conversations, and cache.
"""

from merlya.persistence.database import Database, get_database
from merlya.persistence.models import (
    Conversation,
    Host,
    OSInfo,
    ScanCache,
    Variable,
)
from merlya.persistence.repositories import (
    ConversationRepository,
    HostRepository,
    VariableRepository,
)

__all__ = [
    "Conversation",
    "ConversationRepository",
    "Database",
    "Host",
    "HostRepository",
    "OSInfo",
    "ScanCache",
    "Variable",
    "VariableRepository",
    "get_database",
]
