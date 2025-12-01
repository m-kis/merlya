"""
Enhanced Conversation History with Persistence.

Tracks conversation context across sessions with disk persistence.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from merlya.utils.logger import logger


class ConversationHistory:
    """
    Enhanced conversation memory that tracks query history and persists to disk.

    Features:
    - Stores last 10 queries with full context
    - Persists to disk for session recovery
    - Provides intelligent context retrieval
    - Tracks entities across conversation
    """

    def __init__(self, env: str = "dev", max_history: int = 10):
        """
        Initialize conversation history.

        Args:
            env: Environment name (for separate history files)
            max_history: Maximum number of queries to remember (default: 10)
        """
        self.env = env
        self.max_history = max_history

        # In-memory history
        self.history: List[Dict[str, Any]] = []

        # Quick access to last mentioned entities
        self.last_target_host: Optional[str] = None
        self.last_service: Optional[str] = None
        self.last_intent: Optional[str] = None
        self.last_file_path: Optional[str] = None

        # Persistence path
        self.history_dir = Path.home() / ".merlya" / "history"
        self.history_file = self.history_dir / f"conversation_{env}.json"

        # Load existing history
        self._load_history()

        logger.debug(f"ConversationHistory initialized with {len(self.history)} entries")

    def add_query(
        self,
        query: str,
        target_host: Optional[str] = None,
        service: Optional[str] = None,
        intent: Optional[str] = None,
        file_path: Optional[str] = None,
        result_summary: Optional[str] = None
    ):
        """
        Add a new query to history.

        Args:
            query: User's query
            target_host: Target host mentioned
            service: Service mentioned
            intent: Detected intent
            file_path: File path mentioned
            result_summary: Brief summary of result (optional)
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "target_host": target_host,
            "service": service,
            "intent": intent,
            "file_path": file_path,
            "result_summary": result_summary
        }

        # Add to history
        self.history.append(entry)

        # Trim to max_history
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # Update quick access
        if target_host:
            self.last_target_host = target_host
        if service:
            self.last_service = service
        if intent:
            self.last_intent = intent
        if file_path:
            self.last_file_path = file_path

        # Persist to disk
        self._save_history()

        logger.debug(f"Added query to history: {query[:50]}...")

    def get_last_target_host(self) -> Optional[str]:
        """Get the last mentioned target host."""
        return self.last_target_host

    def get_last_service(self) -> Optional[str]:
        """Get the last mentioned service."""
        return self.last_service

    def get_last_intent(self) -> Optional[str]:
        """Get the last detected intent."""
        return self.last_intent

    def get_last_file_path(self) -> Optional[str]:
        """Get the last mentioned file path."""
        return self.last_file_path

    def get_recent_queries(self, n: int = 5) -> List[Dict[str, Any]]:
        """
        Get the N most recent queries.

        Args:
            n: Number of queries to retrieve

        Returns:
            List of query entries (most recent first)
        """
        return list(reversed(self.history[-n:]))

    def find_similar_context(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Find a previous query with similar context.

        Args:
            query: Current query

        Returns:
            Most similar historical entry, or None
        """
        query_lower = query.lower()

        # Search for queries mentioning same keywords
        for entry in reversed(self.history):
            prev_query = entry["query"].lower()

            # Check for common keywords
            keywords = ["backup", "disk", "service", "check", "status", "log"]
            matching_keywords = [kw for kw in keywords if kw in query_lower and kw in prev_query]

            if len(matching_keywords) >= 2:
                return entry

        return None

    def get_context_summary(self) -> str:
        """
        Get a human-readable summary of conversation context.

        Returns:
            Summary string for display
        """
        lines = []

        if self.last_target_host:
            lines.append(f"📍 Dernier serveur: {self.last_target_host}")

        if self.last_service:
            lines.append(f"🔧 Dernier service: {self.last_service}")

        if self.last_file_path:
            lines.append(f"📄 Dernier fichier: {self.last_file_path}")

        recent_count = len(self.history)
        if recent_count > 0:
            lines.append(f"💬 Historique: {recent_count} requêtes")

        return "\n".join(lines) if lines else "Aucun contexte conversationnel"

    def get_legacy_dict(self) -> Dict[str, Any]:
        """
        Get legacy dict format for backward compatibility.

        Returns:
            Dict with last_target_host, last_service, last_intent
        """
        return {
            "last_target_host": self.last_target_host,
            "last_service": self.last_service,
            "last_intent": self.last_intent,
            "last_file_path": self.last_file_path
        }

    def clear(self):
        """Clear all history (useful for testing)."""
        self.history = []
        self.last_target_host = None
        self.last_service = None
        self.last_intent = None
        self.last_file_path = None
        self._save_history()
        logger.info("Conversation history cleared")

    def _load_history(self):
        """Load history from disk if it exists."""
        try:
            if self.history_file.exists():
                with open(self.history_file, 'r') as f:
                    data = json.load(f)

                self.history = data.get("history", [])

                # Restore last entities
                if self.history:
                    last_entry = self.history[-1]
                    self.last_target_host = last_entry.get("target_host")
                    self.last_service = last_entry.get("service")
                    self.last_intent = last_entry.get("intent")
                    self.last_file_path = last_entry.get("file_path")

                logger.info(f"Loaded {len(self.history)} conversation entries from disk")
        except Exception as e:
            logger.warning(f"Failed to load conversation history: {e}")
            self.history = []

    def _save_history(self):
        """Save history to disk."""
        try:
            # Ensure directory exists
            self.history_dir.mkdir(parents=True, exist_ok=True)

            # Save to file
            data = {
                "env": self.env,
                "last_updated": datetime.now().isoformat(),
                "history": self.history
            }

            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved {len(self.history)} entries to disk")
        except Exception as e:
            logger.warning(f"Failed to save conversation history: {e}")
