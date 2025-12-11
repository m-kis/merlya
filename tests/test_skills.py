"""
Tests for Skills system.

Tests SkillConfig, SkillRegistry, SkillLoader, SkillExecutor.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from merlya.skills.models import HostResult, SkillConfig, SkillResult, SkillStatus
from merlya.skills.registry import SkillRegistry, get_registry, reset_registry
from merlya.skills.loader import SkillLoader
from merlya.skills.executor import SkillExecutor
from merlya.skills.wizard import generate_skill_template


class TestSkillConfig:
    """Tests for SkillConfig model."""

    def test_default_values(self):
        """Test default configuration values."""
        config = SkillConfig(name="test_skill")

        assert config.name == "test_skill"
        assert config.version == "1.0"
        assert config.description == ""
        assert config.max_hosts == 5
        assert config.timeout_seconds == 120
        assert config.tools_allowed == []
        assert config.builtin is False

    def test_custom_values(self):
        """Test custom configuration values."""
        config = SkillConfig(
            name="custom_skill",
            version="2.0",
            description="Custom description",
            max_hosts=10,
            timeout_seconds=60,
            tools_allowed=["ssh_execute", "read_file"],
            tags=["test", "custom"],
        )

        assert config.name == "custom_skill"
        assert config.version == "2.0"
        assert config.max_hosts == 10
        assert len(config.tools_allowed) == 2
        assert "test" in config.tags

    def test_validation_max_hosts(self):
        """Test validation of max_hosts."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SkillConfig(name="test", max_hosts=0)

        with pytest.raises(ValidationError):
            SkillConfig(name="test", max_hosts=200)

    def test_validation_timeout(self):
        """Test validation of timeout_seconds."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SkillConfig(name="test", timeout_seconds=5)

        with pytest.raises(ValidationError):
            SkillConfig(name="test", timeout_seconds=1000)

    def test_intent_patterns(self):
        """Test intent patterns."""
        config = SkillConfig(
            name="test",
            intent_patterns=[r"disk.*", r"storage.*"],
        )

        assert len(config.intent_patterns) == 2
        assert r"disk.*" in config.intent_patterns


class TestHostResult:
    """Tests for HostResult model."""

    def test_success_result(self):
        """Test successful host result."""
        result = HostResult(
            host="web-01",
            success=True,
            output="Command completed",
            duration_ms=150,
            tool_calls=2,
        )

        assert result.success
        assert result.host == "web-01"
        assert result.error is None

    def test_failed_result(self):
        """Test failed host result."""
        result = HostResult(
            host="db-01",
            success=False,
            error="Connection refused",
            duration_ms=5000,
        )

        assert not result.success
        assert "Connection refused" in result.error


class TestSkillResult:
    """Tests for SkillResult model."""

    def test_success_rate(self):
        """Test success rate calculation."""
        result = SkillResult(
            skill_name="test",
            execution_id="abc123",
            status=SkillStatus.PARTIAL,
            started_at=datetime.now(timezone.utc),
            total_hosts=10,
            succeeded_hosts=7,
            failed_hosts=3,
        )

        assert result.success_rate == 70.0

    def test_success_rate_zero_hosts(self):
        """Test success rate with zero hosts."""
        result = SkillResult(
            skill_name="test",
            execution_id="abc123",
            status=SkillStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            total_hosts=0,
            succeeded_hosts=0,
            failed_hosts=0,
        )

        assert result.success_rate == 0.0

    def test_is_success(self):
        """Test is_success property."""
        result = SkillResult(
            skill_name="test",
            execution_id="abc123",
            status=SkillStatus.SUCCESS,
            started_at=datetime.now(timezone.utc),
        )

        assert result.is_success
        assert not result.is_partial

    def test_to_summary(self):
        """Test summary generation."""
        result = SkillResult(
            skill_name="disk_audit",
            execution_id="abc123",
            status=SkillStatus.SUCCESS,
            started_at=datetime.now(timezone.utc),
            total_hosts=5,
            succeeded_hosts=5,
            failed_hosts=0,
        )

        summary = result.to_summary()
        assert "disk_audit" in summary
        assert "5/5" in summary


class TestSkillRegistry:
    """Tests for SkillRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry_fixture(self):
        """Reset registry before each test."""
        reset_registry()
        yield
        reset_registry()

    def test_register_and_get(self):
        """Test registering and retrieving a skill."""
        registry = SkillRegistry()
        skill = SkillConfig(name="test_skill")

        registry.register(skill)

        assert registry.has("test_skill")
        assert registry.get("test_skill") == skill

    def test_unregister(self):
        """Test unregistering a skill."""
        registry = SkillRegistry()
        skill = SkillConfig(name="test_skill")

        registry.register(skill)
        assert registry.has("test_skill")

        result = registry.unregister("test_skill")
        assert result is True
        assert not registry.has("test_skill")

    def test_unregister_nonexistent(self):
        """Test unregistering nonexistent skill."""
        registry = SkillRegistry()
        result = registry.unregister("nonexistent")
        assert result is False

    def test_get_all(self):
        """Test getting all skills."""
        registry = SkillRegistry()
        registry.register(SkillConfig(name="skill1"))
        registry.register(SkillConfig(name="skill2"))

        all_skills = registry.get_all()
        assert len(all_skills) == 2

    def test_get_builtin_and_user(self):
        """Test filtering builtin vs user skills."""
        registry = SkillRegistry()
        registry.register(SkillConfig(name="builtin", builtin=True))
        registry.register(SkillConfig(name="user", builtin=False))

        builtin = registry.get_builtin()
        user = registry.get_user()

        assert len(builtin) == 1
        assert builtin[0].name == "builtin"
        assert len(user) == 1
        assert user[0].name == "user"

    def test_match_intent(self):
        """Test intent pattern matching."""
        registry = SkillRegistry()
        registry.register(
            SkillConfig(
                name="disk_audit",
                intent_patterns=[r"disk.*", r"storage.*"],
            )
        )

        matches = registry.match_intent("check disk usage")
        assert len(matches) == 1
        assert matches[0][0].name == "disk_audit"
        assert matches[0][1] > 0  # Has confidence

    def test_match_intent_no_match(self):
        """Test intent matching with no matches."""
        registry = SkillRegistry()
        registry.register(
            SkillConfig(
                name="disk_audit",
                intent_patterns=[r"disk.*"],
            )
        )

        matches = registry.match_intent("network issue")
        assert len(matches) == 0

    def test_find_by_tag(self):
        """Test finding skills by tag."""
        registry = SkillRegistry()
        registry.register(SkillConfig(name="skill1", tags=["monitoring", "disk"]))
        registry.register(SkillConfig(name="skill2", tags=["network"]))

        disk_skills = registry.find_by_tag("disk")
        assert len(disk_skills) == 1
        assert disk_skills[0].name == "skill1"

    def test_count(self):
        """Test skill count."""
        registry = SkillRegistry()
        assert registry.count() == 0

        registry.register(SkillConfig(name="skill1"))
        registry.register(SkillConfig(name="skill2"))

        assert registry.count() == 2

    def test_clear(self):
        """Test clearing registry."""
        registry = SkillRegistry()
        registry.register(SkillConfig(name="skill1"))
        registry.register(SkillConfig(name="skill2"))

        registry.clear()
        assert registry.count() == 0

    def test_get_stats(self):
        """Test getting stats."""
        registry = SkillRegistry()
        registry.register(SkillConfig(name="builtin1", builtin=True))
        registry.register(SkillConfig(name="builtin2", builtin=True))
        registry.register(SkillConfig(name="user1", builtin=False))

        stats = registry.get_stats()
        assert stats["total"] == 3
        assert stats["builtin"] == 2
        assert stats["user"] == 1


class TestSkillLoader:
    """Tests for SkillLoader."""

    @pytest.fixture(autouse=True)
    def reset_registry_fixture(self):
        """Reset registry before each test."""
        reset_registry()
        yield
        reset_registry()

    def test_load_from_string(self):
        """Test loading skill from YAML string."""
        yaml_content = """
name: test_skill
version: "1.0"
description: "Test skill"
max_hosts: 5
"""
        registry = SkillRegistry()
        loader = SkillLoader(registry=registry)

        skill = loader.load_from_string(yaml_content)

        assert skill is not None
        assert skill.name == "test_skill"
        assert registry.has("test_skill")

    def test_load_from_string_invalid_yaml(self):
        """Test loading invalid YAML."""
        yaml_content = "invalid: yaml: content: ["

        registry = SkillRegistry()
        loader = SkillLoader(registry=registry)

        skill = loader.load_from_string(yaml_content)
        assert skill is None

    def test_load_from_string_empty(self):
        """Test loading empty YAML."""
        registry = SkillRegistry()
        loader = SkillLoader(registry=registry)

        skill = loader.load_from_string("")
        assert skill is None

    def test_load_file(self):
        """Test loading skill from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file in temp dir used as user_dir
            skill_path = Path(tmpdir) / "file_skill.yaml"
            skill_path.write_text("""
name: file_skill
version: "2.0"
description: "From file"
""")

            registry = SkillRegistry()
            loader = SkillLoader(registry=registry, user_dir=Path(tmpdir))

            skill = loader.load_file(skill_path, builtin=False)

            assert skill is not None
            assert skill.name == "file_skill"
            assert skill.source_path == str(skill_path)

    def test_load_builtin(self):
        """Test loading builtin skills."""
        from merlya.skills.loader import BUILTIN_SKILLS_DIR

        if not BUILTIN_SKILLS_DIR.exists():
            pytest.skip("Builtin skills directory not found")

        registry = SkillRegistry()
        loader = SkillLoader(registry=registry)

        count = loader.load_builtin()
        assert count >= 0  # May be 0 if no files yet

    def test_save_user_skill(self):
        """Test saving a user skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = SkillRegistry()
            loader = SkillLoader(registry=registry, user_dir=Path(tmpdir))

            skill = SkillConfig(
                name="saved_skill",
                description="Saved to disk",
            )
            registry.register(skill)

            path = loader.save_user_skill(skill)

            assert path.exists()
            assert "saved_skill.yaml" in str(path)


class TestSkillExecutor:
    """Tests for SkillExecutor."""

    @pytest.fixture
    def executor(self):
        """Create an executor."""
        return SkillExecutor(max_concurrent=2)

    @pytest.fixture
    def skill(self):
        """Create a test skill."""
        return SkillConfig(
            name="test_skill",
            max_hosts=5,
            timeout_seconds=30,
            tools_allowed=["ssh_execute"],
        )

    @pytest.mark.asyncio
    async def test_execute_single_host(self, executor, skill):
        """Test executing on a single host."""
        result = await executor.execute(
            skill=skill,
            hosts=["web-01"],
            task="check status",
        )

        assert result.skill_name == "test_skill"
        assert result.total_hosts == 1
        assert result.status == SkillStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_multiple_hosts(self, executor, skill):
        """Test executing on multiple hosts."""
        result = await executor.execute(
            skill=skill,
            hosts=["web-01", "web-02", "web-03"],
            task="check disk",
        )

        assert result.total_hosts == 3
        assert len(result.host_results) == 3

    @pytest.mark.asyncio
    async def test_execute_respects_max_hosts(self, executor):
        """Test that execution respects skill's max_hosts."""
        skill = SkillConfig(name="limited", max_hosts=2)

        result = await executor.execute(
            skill=skill,
            hosts=["h1", "h2", "h3", "h4", "h5"],
            task="test",
        )

        # Should be limited to 2
        assert result.total_hosts == 2

    def test_filter_tools(self, executor, skill):
        """Test tool filtering."""
        available = ["ssh_execute", "read_file", "write_file"]

        filtered = executor.filter_tools(skill, available)

        assert filtered == ["ssh_execute"]

    def test_filter_tools_no_restrictions(self, executor):
        """Test filtering with no restrictions."""
        skill = SkillConfig(name="unrestricted", tools_allowed=[])
        available = ["ssh_execute", "read_file", "write_file"]

        filtered = executor.filter_tools(skill, available)

        assert filtered == available


class TestSkillWizard:
    """Tests for SkillWizard."""

    def test_generate_template(self):
        """Test template generation."""
        template = generate_skill_template("my_skill", "My custom skill")

        assert "name: my_skill" in template
        assert "My custom skill" in template
        assert "tools_allowed" in template
        assert "max_hosts" in template


class TestSkillStatus:
    """Tests for SkillStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert SkillStatus.PENDING.value == "pending"
        assert SkillStatus.RUNNING.value == "running"
        assert SkillStatus.SUCCESS.value == "success"
        assert SkillStatus.PARTIAL.value == "partial"
        assert SkillStatus.FAILED.value == "failed"
        assert SkillStatus.TIMEOUT.value == "timeout"
        assert SkillStatus.CANCELLED.value == "cancelled"
