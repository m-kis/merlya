"""
Integration tests for SQLite persistence layer.

Tests cover:
- Conversation storage (SQLiteStore)
- Session repository with cross-session linking
- Export/import functionality
- Token counting
- Storage manager with retry mechanism
"""
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

import pytest

from merlya.memory.conversation_manager.models import Conversation, Message
from merlya.memory.conversation_manager.storage import EXPORT_VERSION, SQLiteStore
from merlya.memory.persistence.session_repository import SessionRepository
from merlya.utils.tokenizer import (
    count_tokens,
    get_token_info,
    is_tiktoken_available,
    truncate_to_tokens,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sqlite_store(temp_db):
    """Create SQLiteStore instance with temp database."""
    return SQLiteStore(Path(temp_db))


@pytest.fixture
def session_repo(temp_db):
    """Create SessionRepository instance with temp database."""
    return SessionRepository(temp_db)


class TestSQLiteStore:
    """Tests for conversation storage."""

    def test_create_and_load_conversation(self, sqlite_store):
        """Test creating and loading a conversation."""
        conv = Conversation(
            id="test_conv_1",
            title="Test Conversation",
        )
        conv.add_message("user", "Hello!")
        conv.add_message("assistant", "Hi there!")

        sqlite_store.save_conversation(conv)

        # Load it back
        loaded = sqlite_store.load_conversation("test_conv_1")
        assert loaded is not None
        assert loaded.id == "test_conv_1"
        assert loaded.title == "Test Conversation"
        assert len(loaded.messages) == 0  # Messages are saved separately

    def test_save_and_load_messages(self, sqlite_store):
        """Test saving individual messages."""
        conv = Conversation(id="test_conv_2", title="Test")
        sqlite_store.save_conversation(conv)

        msg1 = Message(role="user", content="Hello!")
        msg2 = Message(role="assistant", content="Hi there!")

        sqlite_store.save_message("test_conv_2", msg1)
        sqlite_store.save_message("test_conv_2", msg2)

        # Load with messages
        loaded = sqlite_store.load_conversation("test_conv_2")
        assert loaded is not None
        assert len(loaded.messages) == 2
        assert loaded.messages[0].role == "user"
        assert loaded.messages[1].role == "assistant"

    def test_current_conversation(self, sqlite_store):
        """Test current conversation tracking."""
        conv1 = Conversation(id="conv_1", title="First")
        conv2 = Conversation(id="conv_2", title="Second")

        sqlite_store.save_conversation(conv1)  # Sets as current
        sqlite_store.set_current("conv_1")

        current = sqlite_store.load_current()
        assert current is not None
        assert current.id == "conv_1"

        # Save second and explicitly set as current
        sqlite_store.save_conversation(conv2)
        sqlite_store.set_current("conv_2")

        current = sqlite_store.load_current()
        assert current.id == "conv_2"

        # Switch back to first
        sqlite_store.set_current("conv_1")
        current = sqlite_store.load_current()
        assert current.id == "conv_1"

    def test_archive_conversation(self, sqlite_store):
        """Test archiving a conversation."""
        conv = Conversation(id="conv_archive", title="To Archive")
        sqlite_store.save_conversation(conv)  # Sets as current

        sqlite_store.archive("conv_archive")

        # Should not be current anymore
        current = sqlite_store.load_current()
        assert current is None or current.id != "conv_archive"

    def test_delete_conversation(self, sqlite_store):
        """Test deleting a conversation."""
        conv = Conversation(id="conv_delete", title="To Delete")
        sqlite_store.save_conversation(conv)

        # Add a message
        sqlite_store.save_message("conv_delete", Message(role="user", content="Test"))

        # Delete
        result = sqlite_store.delete("conv_delete")
        assert result is True

        # Should not exist
        loaded = sqlite_store.load_conversation("conv_delete")
        assert loaded is None

    def test_list_conversations(self, sqlite_store):
        """Test listing conversations."""
        for i in range(5):
            conv = Conversation(id=f"conv_list_{i}", title=f"Conv {i}")
            sqlite_store.save_conversation(conv)
            time.sleep(0.01)  # Ensure different timestamps

        conversations = sqlite_store.list_all(limit=3)
        assert len(conversations) == 3
        # Should be ordered by updated_at DESC
        assert conversations[0]["id"] == "conv_list_4"

    def test_export_conversation(self, sqlite_store):
        """Test exporting a conversation."""
        conv = Conversation(id="conv_export", title="Export Test")
        sqlite_store.save_conversation(conv)
        sqlite_store.save_message("conv_export", Message(role="user", content="Test message"))

        exported = sqlite_store.export_conversation("conv_export")
        assert exported is not None
        assert exported["version"] == EXPORT_VERSION
        assert "exported_at" in exported
        assert exported["conversation"]["id"] == "conv_export"

    def test_import_conversation(self, sqlite_store):
        """Test importing a conversation."""
        export_data = {
            "version": EXPORT_VERSION,
            "exported_at": datetime.now().isoformat(),
            "conversation": {
                "id": "imported_conv",
                "title": "Imported",
                "messages": [
                    {"role": "user", "content": "Hello", "timestamp": datetime.now().isoformat(), "tokens": 1},
                    {"role": "assistant", "content": "Hi", "timestamp": datetime.now().isoformat(), "tokens": 1},
                ],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "token_count": 2,
                "compacted": False,
            },
        }

        conv_id = sqlite_store.import_conversation(export_data)
        assert conv_id is not None

        # Load and verify
        loaded = sqlite_store.load_conversation(conv_id)
        assert loaded is not None
        assert loaded.title == "Imported"
        assert len(loaded.messages) == 2

    def test_import_duplicate_generates_new_id(self, sqlite_store):
        """Test that importing with existing ID generates new ID."""
        conv = Conversation(id="existing_conv", title="Original")
        sqlite_store.save_conversation(conv)

        export_data = {
            "version": EXPORT_VERSION,
            "conversation": {
                "id": "existing_conv",
                "title": "Duplicate",
                "messages": [],
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "token_count": 0,
                "compacted": False,
            },
        }

        new_id = sqlite_store.import_conversation(export_data)
        assert new_id is not None
        assert new_id != "existing_conv"
        assert "_imported" in new_id

    def test_export_all(self, sqlite_store):
        """Test exporting all conversations."""
        for i in range(3):
            conv = Conversation(id=f"conv_all_{i}", title=f"Conv {i}")
            sqlite_store.save_conversation(conv)

        exported = sqlite_store.export_all()
        assert exported["version"] == EXPORT_VERSION
        assert exported["count"] == 3
        assert len(exported["conversations"]) == 3


class TestSessionRepository:
    """Tests for session repository with cross-session features."""

    def test_start_and_end_session(self, session_repo):
        """Test session lifecycle."""
        session_repo.start_session("session_1", {"env": "test"})

        # Get history
        history = session_repo.get_session_history("session_1")
        assert history["session"]["id"] == "session_1"
        assert history["session"]["status"] == "active"

        # End session
        session_repo.end_session("session_1")
        history = session_repo.get_session_history("session_1")
        assert history["session"]["status"] == "completed"

    def test_log_query_and_action(self, session_repo):
        """Test logging queries and actions."""
        session_repo.start_session("session_2")

        query_id = session_repo.log_query(
            "session_2",
            "check disk space",
            "Disk usage: 50%",
            actions_count=1,
            execution_time_ms=100,
        )
        assert query_id > 0

        session_repo.log_action(
            "session_2",
            query_id,
            "localhost",
            "df -h",
            exit_code=0,
            stdout="50% used",
            stderr="",
            risk_level="low",
            duration_ms=50,
        )

        history = session_repo.get_session_history("session_2")
        assert len(history["queries"]) == 1
        assert len(history["actions"]) == 1

    def test_link_conversation_to_session(self, session_repo):
        """Test linking conversation to session."""
        session_repo.start_session("session_3")

        result = session_repo.link_conversation("session_3", "conv_xyz")
        assert result is True

        # Link again should return False (already linked)
        result = session_repo.link_conversation("session_3", "conv_xyz")
        assert result is False

        convs = session_repo.get_session_conversations("session_3")
        assert "conv_xyz" in convs

    def test_get_conversation_sessions(self, session_repo):
        """Test getting sessions for a conversation."""
        session_repo.start_session("session_4")
        session_repo.start_session("session_5")

        session_repo.link_conversation("session_4", "conv_shared")
        session_repo.link_conversation("session_5", "conv_shared")

        sessions = session_repo.get_conversation_sessions("conv_shared")
        assert len(sessions) == 2
        session_ids = [s["id"] for s in sessions]
        assert "session_4" in session_ids
        assert "session_5" in session_ids

    def test_link_sessions(self, session_repo):
        """Test linking sessions (parent-child)."""
        session_repo.start_session("parent_session")
        session_repo.start_session("child_session")

        result = session_repo.link_sessions("parent_session", "child_session", "continuation")
        assert result is True

    def test_get_session_chain(self, session_repo):
        """Test getting session chain."""
        session_repo.start_session("chain_1")
        session_repo.start_session("chain_2")
        session_repo.start_session("chain_3")

        session_repo.link_sessions("chain_1", "chain_2")
        session_repo.link_sessions("chain_2", "chain_3")

        chain = session_repo.get_session_chain("chain_2")
        assert len(chain) == 3
        assert chain[0]["id"] == "chain_1"
        assert chain[1]["id"] == "chain_2"
        assert chain[1]["is_current"] is True
        assert chain[2]["id"] == "chain_3"

    def test_export_session(self, session_repo):
        """Test exporting a session."""
        session_repo.start_session("export_session")
        query_id = session_repo.log_query(
            "export_session", "test query", "test response"
        )
        session_repo.log_action(
            "export_session", query_id, "local", "ls", 0, "files", "", "low"
        )
        session_repo.save_context_snapshot("export_session", {"key": "value"})
        session_repo.link_conversation("export_session", "conv_linked")

        exported = session_repo.export_session("export_session")
        assert exported["version"] == "1.0"
        assert exported["session"]["id"] == "export_session"
        assert len(exported["queries"]) == 1
        assert len(exported["actions"]) == 1
        assert len(exported["context_snapshots"]) == 1
        assert "conv_linked" in exported["linked_conversations"]

    def test_import_session(self, session_repo):
        """Test importing a session."""
        export_data = {
            "version": "1.0",
            "session": {
                "id": "imported_session",
                "started_at": datetime.now().isoformat(),
                "ended_at": None,
                "status": "active",
                "total_queries": 1,
                "total_actions": 1,
            },
            "queries": [
                {
                    "id": 1,
                    "timestamp": datetime.now().isoformat(),
                    "query": "test",
                    "response": "result",
                    "actions_count": 0,
                    "execution_time_ms": 100,
                }
            ],
            "actions": [],
            "context_snapshots": [],
        }

        new_id = session_repo.import_session(export_data)
        assert new_id is not None
        assert "imported" in new_id

        # Verify it exists
        sessions = session_repo.list_sessions()
        session_ids = [s["id"] for s in sessions]
        assert new_id in session_ids

    def test_resume_session(self, session_repo):
        """Test resuming a session."""
        session_repo.start_session("resume_session")
        session_repo.end_session("resume_session")

        result = session_repo.resume_session("resume_session")
        assert result is True

        history = session_repo.get_session_history("resume_session")
        assert history["session"]["status"] == "active"


class TestTokenizer:
    """Tests for token counting utilities."""

    def test_count_tokens_empty(self):
        """Test counting tokens in empty string."""
        assert count_tokens("") == 0
        assert count_tokens(None) == 0  # type: ignore

    def test_count_tokens_simple(self):
        """Test counting tokens in simple text."""
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 10  # Should be a few tokens

    def test_count_tokens_code(self):
        """Test counting tokens in code."""
        code = """
        def hello_world():
            print("Hello, World!")
        """
        tokens = count_tokens(code)
        assert tokens > 5  # Code should have multiple tokens

    def test_truncate_to_tokens(self):
        """Test truncating text to token limit."""
        long_text = "Hello world! " * 100
        truncated = truncate_to_tokens(long_text, max_tokens=10)

        result_tokens = count_tokens(truncated)
        assert result_tokens <= 10
        assert len(truncated) < len(long_text)

    def test_truncate_short_text(self):
        """Test truncating text that's already short."""
        short_text = "Hi"
        truncated = truncate_to_tokens(short_text, max_tokens=100)
        assert truncated == short_text

    def test_get_token_info(self):
        """Test getting tokenizer info."""
        info = get_token_info()
        assert "tiktoken_available" in info
        assert "encoding" in info
        assert "accuracy" in info

    def test_tiktoken_availability(self):
        """Test tiktoken availability check."""
        available = is_tiktoken_available()
        assert isinstance(available, bool)


class TestConversationModels:
    """Tests for conversation model token integration."""

    def test_message_auto_token_count(self):
        """Test that Message calculates tokens automatically."""
        msg = Message(role="user", content="Hello, how are you?")
        assert msg.tokens > 0

    def test_conversation_add_message_counts_tokens(self):
        """Test that Conversation.add_message counts tokens."""
        conv = Conversation(id="test", title="Test")
        msg = conv.add_message("user", "This is a test message.")

        assert msg.tokens > 0
        assert conv.token_count > 0

    def test_conversation_recalculate_tokens(self):
        """Test recalculating all tokens."""
        conv = Conversation(id="test", title="Test")
        conv.add_message("user", "Hello")
        conv.add_message("assistant", "Hi there!")

        # Manually corrupt the count
        conv.token_count = 0
        conv.messages[0].tokens = 0

        # Recalculate
        new_count = conv.recalculate_tokens()

        assert new_count > 0
        assert conv.messages[0].tokens > 0
        # Should be similar to original (may differ slightly based on implementation)


class TestStorageManagerRetry:
    """Tests for StorageManager retry mechanism."""

    def test_retry_config_exponential_delay(self):
        """Test exponential backoff calculation."""
        from merlya.knowledge.storage_manager import RetryConfig

        config = RetryConfig(
            max_retries=3,
            initial_delay=1.0,
            max_delay=10.0,
            exponential_base=2.0,
        )

        assert config.get_delay(0) == 1.0
        assert config.get_delay(1) == 2.0
        assert config.get_delay(2) == 4.0
        assert config.get_delay(3) == 8.0
        assert config.get_delay(10) == 10.0  # Capped at max_delay

    def test_storage_manager_creation(self, temp_db):
        """Test StorageManager creation."""
        from merlya.knowledge.storage_manager import StorageManager

        manager = StorageManager(
            sqlite_path=temp_db,
            enable_falkordb=False,  # Don't require FalkorDB for test
        )

        assert manager.sqlite is not None
        assert manager.falkordb is not None

    def test_storage_manager_sync_status(self, temp_db):
        """Test sync status reporting."""
        from merlya.knowledge.storage_manager import StorageManager

        manager = StorageManager(
            sqlite_path=temp_db,
            enable_falkordb=False,
        )

        status = manager.get_sync_status()
        assert "background_sync_enabled" in status
        assert "unsynced_incidents" in status
        assert status["background_sync_enabled"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
