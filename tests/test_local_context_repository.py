"""
Tests for LocalContextRepositoryMixin.

Verifies:
- Round-trip consistency (save/get preserves data types)
- Metadata structure (_metadata key)
- Reserved key handling
- Type preservation (bool, int, float, None, dict, list)
"""

import os
import tempfile
from datetime import datetime

import pytest

from merlya.memory.persistence.inventory_repository import (
    InventoryRepository,
    get_inventory_repository,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # Cleanup
    InventoryRepository.reset_instance()
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def repo(temp_db):
    """Get a fresh repository instance."""
    InventoryRepository.reset_instance()
    return get_inventory_repository(temp_db)


class TestLocalContextRepository:
    """Tests for local context repository operations."""

    def test_save_and_get_basic_context(self, repo):
        """Test basic save and get operations."""
        context = {
            "os_info": {"platform": "linux", "version": "5.10"},
            "network": {"hostname": "test-host"},
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result is not None
        assert result["os_info"] == {"platform": "linux", "version": "5.10"}
        assert result["network"] == {"hostname": "test-host"}

    def test_metadata_structure(self, repo):
        """Test that _metadata key is created with scanned_at."""
        context = {"category": {"key": "value"}}

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert "_metadata" in result
        assert "scanned_at" in result["_metadata"]
        # scanned_at should be an ISO timestamp string
        scanned_at = result["_metadata"]["scanned_at"]
        assert isinstance(scanned_at, str)
        # Verify it's a valid ISO format (handle Python <3.11 'Z' suffix issue)
        try:
            datetime.fromisoformat(scanned_at)
        except ValueError:
            # Fallback: replace trailing 'Z' with '+00:00' for Python <3.11
            if scanned_at.endswith("Z"):
                datetime.fromisoformat(scanned_at[:-1] + "+00:00")
            else:
                raise

    def test_metadata_key_is_reserved(self, repo):
        """Test that _metadata key is not saved as user data."""
        context = {
            "_metadata": {"user_data": "should_be_ignored"},
            "real_category": {"key": "value"},
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        # _metadata should only contain scanned_at, not user_data
        assert "_metadata" in result
        assert "scanned_at" in result["_metadata"]
        assert "user_data" not in result["_metadata"]
        assert "real_category" in result

    def test_scanned_at_collision_avoided(self, repo):
        """Test that a user category named 'scanned_at' is preserved."""
        context = {
            "scanned_at": {"my_key": "my_value"},  # User category
            "other": {"data": "here"},
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        # User category "scanned_at" should be preserved
        assert "scanned_at" in result
        assert result["scanned_at"] == {"my_key": "my_value"}
        # Metadata scanned_at should be in _metadata
        assert result["_metadata"]["scanned_at"] is not None

    def test_type_preservation_bool(self, repo):
        """Test that boolean values are preserved."""
        context = {
            "flags": {
                "enabled": True,
                "disabled": False,
            }
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result["flags"]["enabled"] is True
        assert result["flags"]["disabled"] is False
        # Verify they're actual booleans, not strings
        assert isinstance(result["flags"]["enabled"], bool)
        assert isinstance(result["flags"]["disabled"], bool)

    def test_type_preservation_numbers(self, repo):
        """Test that numeric values are preserved."""
        context = {
            "metrics": {
                "count": 42,
                "ratio": 3.14,
                "negative": -10,
                "zero": 0,
            }
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result["metrics"]["count"] == 42
        assert result["metrics"]["ratio"] == 3.14
        assert result["metrics"]["negative"] == -10
        assert result["metrics"]["zero"] == 0
        assert isinstance(result["metrics"]["count"], int)
        assert isinstance(result["metrics"]["ratio"], float)

    def test_type_preservation_none(self, repo):
        """Test that None values are preserved."""
        context = {
            "data": {
                "present": "value",
                "absent": None,
            }
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result["data"]["present"] == "value"
        assert result["data"]["absent"] is None

    def test_type_preservation_nested_structures(self, repo):
        """Test that nested dicts and lists are preserved."""
        context = {
            "complex": {
                "nested_dict": {"a": {"b": {"c": 1}}},
                "nested_list": [[1, 2], [3, 4]],
                "mixed": {"items": [1, "two", None, True]},
            }
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result["complex"]["nested_dict"] == {"a": {"b": {"c": 1}}}
        assert result["complex"]["nested_list"] == [[1, 2], [3, 4]]
        assert result["complex"]["mixed"] == {"items": [1, "two", None, True]}

    def test_non_dict_category_value(self, repo):
        """Test that non-dict category values are stored with _value key."""
        context = {
            "simple_string": "just a string",
            "simple_list": [1, 2, 3],
            "dict_category": {"key": "value"},
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        # Non-dict values become {"_value": original_value}
        assert result["simple_string"] == {"_value": "just a string"}
        assert result["simple_list"] == {"_value": [1, 2, 3]}
        # Dict categories remain unchanged
        assert result["dict_category"] == {"key": "value"}

    def test_has_local_context_empty(self, repo):
        """Test has_local_context returns False when empty."""
        assert repo.has_local_context() is False

    def test_has_local_context_with_data(self, repo):
        """Test has_local_context returns True when data exists."""
        repo.save_local_context({"test": {"key": "value"}})
        assert repo.has_local_context() is True

    def test_get_local_context_empty(self, repo):
        """Test get_local_context returns None when empty."""
        result = repo.get_local_context()
        assert result is None

    def test_save_overwrites_previous(self, repo):
        """Test that save_local_context replaces previous data."""
        repo.save_local_context({"old": {"data": "here"}})
        repo.save_local_context({"new": {"data": "here"}})

        result = repo.get_local_context()

        assert "old" not in result
        assert "new" in result

    def test_empty_context_save(self, repo):
        """Test saving an empty context."""
        repo.save_local_context({})
        result = repo.get_local_context()

        # Empty context should return None (no rows)
        assert result is None

    def test_unicode_values(self, repo):
        """Test that unicode values are preserved."""
        context = {
            "i18n": {
                "japanese": "こんにちは",
                "emoji": "🚀🔥✨",
                "mixed": "Hello 世界 🌍",
            }
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result["i18n"]["japanese"] == "こんにちは"
        assert result["i18n"]["emoji"] == "🚀🔥✨"
        assert result["i18n"]["mixed"] == "Hello 世界 🌍"

    def test_special_json_values(self, repo):
        """Test special JSON values like empty strings and arrays."""
        context = {
            "special": {
                "empty_string": "",
                "empty_list": [],
                "empty_dict": {},
            }
        }

        repo.save_local_context(context)
        result = repo.get_local_context()

        assert result["special"]["empty_string"] == ""
        assert result["special"]["empty_list"] == []
        assert result["special"]["empty_dict"] == {}


class TestLocalContextModelIntegration:
    """Integration tests with LocalContext model."""

    def test_local_context_model_roundtrip(self, repo):
        """Test LocalContext model save/load roundtrip."""
        from merlya.context.local_scanner.models import LocalContext

        original = LocalContext(
            os_info={"platform": "darwin"},
            network={"hostname": "test"},
            services={"running": ["ssh", "nginx"]},
            processes=[{"name": "python", "pid": 123}],
            etc_files={"/etc/hosts": "127.0.0.1 localhost"},
            resources={"cpu_percent": 45.2},
            scanned_at=datetime(2024, 1, 15, 10, 30, 0),
        )

        # Save via repository
        repo.save_local_context(original.to_dict())

        # Load and reconstruct
        loaded_dict = repo.get_local_context()
        loaded = LocalContext.from_dict(loaded_dict)

        assert loaded.os_info == original.os_info
        assert loaded.network == original.network
        assert loaded.services == original.services
        assert loaded.processes == original.processes
        assert loaded.etc_files == original.etc_files
        assert loaded.resources == original.resources
        # scanned_at from model vs metadata scanned_at (updated_at from DB)
        # They won't match exactly but model should parse correctly
        assert isinstance(loaded.scanned_at, datetime)

    def test_from_dict_handles_metadata_structure(self, repo):
        """Test that LocalContext.from_dict handles _metadata structure."""
        from merlya.context.local_scanner.models import LocalContext

        # Simulate data from repository with _metadata
        data_with_metadata = {
            "_metadata": {"scanned_at": "2024-01-15T10:30:00"},
            "os_info": {"platform": "linux"},
            "network": {},
            "services": {},
            "processes": [],
            "etc_files": {},
            "resources": {},
        }

        ctx = LocalContext.from_dict(data_with_metadata)

        assert ctx.os_info == {"platform": "linux"}
        assert ctx.scanned_at == datetime(2024, 1, 15, 10, 30, 0)

    def test_from_dict_handles_legacy_structure(self, repo):
        """Test that LocalContext.from_dict handles legacy scanned_at at root."""
        from merlya.context.local_scanner.models import LocalContext

        # Legacy structure without _metadata
        legacy_data = {
            "scanned_at": "2024-01-15T10:30:00",
            "os_info": {"platform": "linux"},
            "network": {},
            "services": {},
            "processes": [],
            "etc_files": {},
            "resources": {},
        }

        ctx = LocalContext.from_dict(legacy_data)

        assert ctx.os_info == {"platform": "linux"}
        assert ctx.scanned_at == datetime(2024, 1, 15, 10, 30, 0)
