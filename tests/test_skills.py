"""
Tests for Skills system.

Tests SkillConfig, SkillRegistry, SkillLoader, SkillExecutor.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from merlya.skills.executor import SkillExecutor
from merlya.skills.loader import SkillLoader
from merlya.skills.models import HostResult, SkillConfig, SkillResult, SkillStatus
from merlya.skills.registry import SkillRegistry, reset_registry
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
        assert config.timeout_seconds == 300  # New default with activity-based timeout
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

        # Min is now 30s (was 10s)
        with pytest.raises(ValidationError):
            SkillConfig(name="test", timeout_seconds=5)

        # Max is now 1800s (was 600s) to allow longer activity-tracked executions
        with pytest.raises(ValidationError):
            SkillConfig(name="test", timeout_seconds=2000)

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
            started_at=datetime.now(UTC),
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
            started_at=datetime.now(UTC),
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
            started_at=datetime.now(UTC),
        )

        assert result.is_success
        assert not result.is_partial

    def test_to_summary(self):
        """Test summary generation."""
        result = SkillResult(
            skill_name="disk_audit",
            execution_id="abc123",
            status=SkillStatus.SUCCESS,
            started_at=datetime.now(UTC),
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

        new_count, _overwritten = loader.load_builtin()
        assert new_count >= 0  # May be 0 if no files yet

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


class TestSkillExecutorExtended:
    """Extended tests for SkillExecutor covering more edge cases."""

    @pytest.fixture
    def skill(self):
        """Create a test skill."""
        return SkillConfig(
            name="test_skill",
            max_hosts=5,
            timeout_seconds=60,
            tools_allowed=["ssh_execute"],
            require_confirmation_for=["delete", "restart"],
        )

    def test_max_concurrent_default(self):
        """Test max_concurrent default value."""
        executor = SkillExecutor()
        assert executor.max_concurrent == 5  # Default

    def test_max_concurrent_override(self):
        """Test max_concurrent with explicit override."""
        executor = SkillExecutor(max_concurrent=10)
        assert executor.max_concurrent == 10

    def test_max_concurrent_from_policy_manager(self):
        """Test max_concurrent from policy_manager."""
        from unittest.mock import MagicMock

        policy_manager = MagicMock()
        policy_manager.config.max_hosts_per_skill = 15

        executor = SkillExecutor(policy_manager=policy_manager)
        assert executor.max_concurrent == 15

    def test_has_real_execution_without_context(self):
        """Test has_real_execution without context."""
        executor = SkillExecutor()
        assert executor.has_real_execution is False

    def test_has_real_execution_with_context(self):
        """Test has_real_execution with context."""
        from unittest.mock import MagicMock

        context = MagicMock()
        executor = SkillExecutor(context=context)
        assert executor.has_real_execution is True

    def test_orchestrator_lazy_init_without_context(self):
        """Test orchestrator returns None without context."""
        executor = SkillExecutor()
        assert executor.orchestrator is None

    @pytest.mark.asyncio
    async def test_execute_host_count_validation_fail(self, skill):
        """Test execution fails when host count validation fails."""
        from unittest.mock import MagicMock

        policy_manager = MagicMock()
        policy_manager.validate_hosts_count.return_value = (False, "Too many hosts")
        policy_manager.config.max_hosts_per_skill = 5

        executor = SkillExecutor(policy_manager=policy_manager)

        result = await executor.execute(
            skill=skill,
            hosts=["h1", "h2", "h3"],
            task="test",
        )

        assert result.status == SkillStatus.FAILED
        assert "Too many hosts" in (result.summary or "")

    @pytest.mark.asyncio
    async def test_execute_with_exception_in_host(self, skill):
        """Test execution handles exceptions from hosts gracefully."""
        from unittest.mock import patch

        executor = SkillExecutor(max_concurrent=2)

        # Mock _execute_single to raise for one host
        original_execute_single = executor._execute_single

        async def mock_execute_single(skill, host, task, _context=None, _confirm_callback=None):
            if host == "bad-host":
                raise RuntimeError("Connection failed")
            return await original_execute_single(skill, host, task, _context, _confirm_callback)

        with patch.object(executor, "_execute_single", side_effect=mock_execute_single):
            result = await executor.execute(
                skill=skill,
                hosts=["good-host", "bad-host"],
                task="check status",
            )

        assert result.total_hosts == 2
        assert result.failed_hosts == 1
        assert result.succeeded_hosts == 1
        assert result.status == SkillStatus.PARTIAL

    @pytest.mark.asyncio
    async def test_execute_all_hosts_fail(self, skill):
        """Test execution when all hosts fail."""
        from unittest.mock import patch

        executor = SkillExecutor(max_concurrent=2)

        async def mock_execute_single(*args, **kwargs):
            raise RuntimeError("All connections failed")

        with patch.object(executor, "_execute_single", side_effect=mock_execute_single):
            result = await executor.execute(
                skill=skill,
                hosts=["h1", "h2"],
                task="test",
            )

        assert result.status == SkillStatus.FAILED
        assert result.failed_hosts == 2
        assert result.succeeded_hosts == 0

    @pytest.mark.asyncio
    async def test_execute_with_audit_logger(self, skill):
        """Test execution with audit logger."""
        from unittest.mock import AsyncMock, MagicMock

        audit_logger = MagicMock()
        audit_logger.log_skill = AsyncMock()

        executor = SkillExecutor(audit_logger=audit_logger)

        result = await executor.execute(
            skill=skill,
            hosts=["web-01"],
            task="check disk",
        )

        assert result.status == SkillStatus.SUCCESS
        audit_logger.log_skill.assert_called_once()
        call_kwargs = audit_logger.log_skill.call_args.kwargs
        assert call_kwargs["skill_name"] == "test_skill"
        assert call_kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_execute_audit_logger_failure(self, skill):
        """Test execution continues when audit logger fails."""
        from unittest.mock import AsyncMock, MagicMock

        audit_logger = MagicMock()
        audit_logger.log_skill = AsyncMock(side_effect=Exception("Audit DB error"))

        executor = SkillExecutor(audit_logger=audit_logger)

        # Should not raise, execution still succeeds
        result = await executor.execute(
            skill=skill,
            hosts=["web-01"],
            task="check disk",
        )

        assert result.status == SkillStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_execute_single_timeout_error(self, skill):
        """Test _execute_single handles TimeoutError."""
        from unittest.mock import patch

        executor = SkillExecutor(max_concurrent=2)

        async def mock_simulate(*args, **kwargs):
            raise TimeoutError("idle timeout exceeded after 30s")

        with patch.object(executor, "_simulate_execution", side_effect=mock_simulate):
            result = await executor._execute_single(
                skill=skill,
                host="slow-host",
                task="long task",
            )

        assert result.success is False
        assert "Timeout" in result.error
        assert "idle timeout" in result.error

    @pytest.mark.asyncio
    async def test_execute_single_generic_exception(self, skill):
        """Test _execute_single handles generic exceptions."""
        from unittest.mock import patch

        executor = SkillExecutor(max_concurrent=2)

        async def mock_simulate(*args, **kwargs):
            raise ValueError("Unexpected error")

        with patch.object(executor, "_simulate_execution", side_effect=mock_simulate):
            result = await executor._execute_single(
                skill=skill,
                host="error-host",
                task="task",
            )

        assert result.success is False
        assert "Unexpected error" in result.error

    @pytest.mark.asyncio
    async def test_execute_with_orchestrator(self, skill):
        """Test _execute_single with real orchestrator."""
        from unittest.mock import AsyncMock, MagicMock

        context = MagicMock()
        executor = SkillExecutor(context=context, max_concurrent=2)

        # Mock the orchestrator
        mock_orchestrator = MagicMock()
        mock_orchestrator.run_on_host = AsyncMock(
            return_value=MagicMock(
                success=True,
                output="Task completed",
                error=None,
                duration_ms=100,
                tool_calls=3,
            )
        )

        executor._orchestrator = mock_orchestrator

        result = await executor._execute_single(
            skill=skill,
            host="web-01",
            task="check disk",
        )

        assert result.success is True
        assert result.output == "Task completed"
        assert result.tool_calls == 3
        mock_orchestrator.run_on_host.assert_called_once()

    def test_create_failed_result(self, skill):
        """Test _create_failed_result."""
        executor = SkillExecutor()
        started_at = datetime.now(UTC)

        result = executor._create_failed_result(
            skill=skill,
            execution_id="abc123",
            started_at=started_at,
            error="Validation failed",
        )

        assert result.status == SkillStatus.FAILED
        assert result.skill_name == "test_skill"
        assert result.execution_id == "abc123"
        assert "Validation failed" in result.summary
        assert result.total_hosts == 0

    @pytest.mark.asyncio
    async def test_check_confirmation_not_needed(self, skill):
        """Test check_confirmation when not needed."""
        executor = SkillExecutor()

        # "status" doesn't match "delete" or "restart"
        result = await executor.check_confirmation(skill, "status check")
        assert result is True

    @pytest.mark.asyncio
    async def test_check_confirmation_needed_with_callback(self, skill):
        """Test check_confirmation with callback."""
        from unittest.mock import AsyncMock

        executor = SkillExecutor()
        callback = AsyncMock(return_value=True)

        # "delete files" matches "delete"
        result = await executor.check_confirmation(skill, "delete files", confirm_callback=callback)

        assert result is True
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_confirmation_denied(self, skill):
        """Test check_confirmation when user denies."""
        from unittest.mock import AsyncMock

        executor = SkillExecutor()
        callback = AsyncMock(return_value=False)

        result = await executor.check_confirmation(
            skill, "restart service", confirm_callback=callback
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_check_confirmation_no_callback(self, skill):
        """Test check_confirmation without callback returns False."""
        executor = SkillExecutor()

        # Needs confirmation but no callback
        result = await executor.check_confirmation(skill, "delete everything")

        assert result is False

    @pytest.mark.asyncio
    async def test_check_confirmation_policy_manager_overrides(self, skill):
        """Test check_confirmation with policy manager override."""
        from unittest.mock import MagicMock

        policy_manager = MagicMock()
        policy_manager.should_confirm.return_value = False  # Policy says no confirm needed
        policy_manager.config.max_hosts_per_skill = 5

        executor = SkillExecutor(policy_manager=policy_manager)

        # Even though skill requires confirmation for "delete", policy overrides
        result = await executor.check_confirmation(skill, "delete files")

        assert result is True


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
