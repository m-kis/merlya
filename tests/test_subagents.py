"""
Tests for Subagents system.

Tests SubagentResult, AggregatedResults, SubagentFactory, SubagentOrchestrator.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.subagents.results import (
    AggregatedResults,
    SubagentResult,
    SubagentStatus,
)


class TestSubagentStatus:
    """Tests for SubagentStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert SubagentStatus.PENDING.value == "pending"
        assert SubagentStatus.RUNNING.value == "running"
        assert SubagentStatus.SUCCESS.value == "success"
        assert SubagentStatus.FAILED.value == "failed"
        assert SubagentStatus.TIMEOUT.value == "timeout"
        assert SubagentStatus.CANCELLED.value == "cancelled"


class TestSubagentResult:
    """Tests for SubagentResult model."""

    def test_success_result(self):
        """Test creating a successful result."""
        result = SubagentResult(
            host="web-01",
            success=True,
            status=SubagentStatus.SUCCESS,
            output="Task completed",
            duration_ms=1500,
            tool_calls=3,
        )

        assert result.success is True
        assert result.host == "web-01"
        assert result.status == SubagentStatus.SUCCESS
        assert result.output == "Task completed"
        assert result.duration_ms == 1500
        assert result.tool_calls == 3
        assert result.error is None

    def test_failed_result(self):
        """Test creating a failed result."""
        result = SubagentResult(
            host="db-01",
            success=False,
            status=SubagentStatus.FAILED,
            error="Connection refused",
            duration_ms=5000,
        )

        assert result.success is False
        assert result.status == SubagentStatus.FAILED
        assert "Connection refused" in result.error

    def test_timeout_result(self):
        """Test creating a timeout result."""
        result = SubagentResult(
            host="slow-host",
            success=False,
            status=SubagentStatus.TIMEOUT,
            error="Execution timed out after 60s",
            duration_ms=60000,
        )

        assert result.success is False
        assert result.status == SubagentStatus.TIMEOUT

    def test_to_summary_success(self):
        """Test summary for successful result."""
        result = SubagentResult(
            host="web-01",
            success=True,
            status=SubagentStatus.SUCCESS,
            duration_ms=1500,
            tool_calls=3,
        )

        summary = result.to_summary()
        assert "web-01" in summary
        assert "success" in summary
        assert "1500ms" in summary
        assert "3 tools" in summary

    def test_to_summary_with_error(self):
        """Test summary with error message."""
        result = SubagentResult(
            host="db-01",
            success=False,
            status=SubagentStatus.FAILED,
            error="Connection refused by host",
            duration_ms=5000,
        )

        summary = result.to_summary()
        assert "db-01" in summary
        assert "failed" in summary
        assert "Connection" in summary

    def test_to_summary_truncates_long_error(self):
        """Test that long errors are truncated in summary."""
        long_error = "Error: " + "x" * 100
        result = SubagentResult(
            host="web-01",
            success=False,
            status=SubagentStatus.FAILED,
            error=long_error,
        )

        summary = result.to_summary()
        assert "..." in summary

    def test_default_values(self):
        """Test default values."""
        result = SubagentResult(host="web-01", success=True)

        assert result.status == SubagentStatus.PENDING
        assert result.output is None
        assert result.error is None
        assert result.duration_ms == 0
        assert result.tool_calls == 0
        assert result.tokens_used == 0


class TestAggregatedResults:
    """Tests for AggregatedResults model."""

    @pytest.fixture
    def sample_results(self):
        """Create sample results for testing."""
        return [
            SubagentResult(
                host="web-01",
                success=True,
                status=SubagentStatus.SUCCESS,
                duration_ms=1000,
                tool_calls=2,
                tokens_used=100,
            ),
            SubagentResult(
                host="web-02",
                success=True,
                status=SubagentStatus.SUCCESS,
                duration_ms=1500,
                tool_calls=3,
                tokens_used=150,
            ),
            SubagentResult(
                host="web-03",
                success=False,
                status=SubagentStatus.FAILED,
                error="Connection refused",
                duration_ms=500,
                tool_calls=1,
                tokens_used=50,
            ),
        ]

    def test_computed_fields(self, sample_results):
        """Test computed fields (total_hosts, succeeded, failed)."""
        aggregated = AggregatedResults(results=sample_results)

        assert aggregated.total_hosts == 3
        assert aggregated.succeeded_hosts == 2
        assert aggregated.failed_hosts == 1

    def test_success_rate(self, sample_results):
        """Test success rate calculation."""
        aggregated = AggregatedResults(results=sample_results)

        # 2 out of 3 = 66.67%
        assert 66.0 < aggregated.success_rate < 67.0

    def test_success_rate_all_success(self):
        """Test success rate when all hosts succeed."""
        results = [
            SubagentResult(host=f"web-{i}", success=True, status=SubagentStatus.SUCCESS)
            for i in range(5)
        ]
        aggregated = AggregatedResults(results=results)

        assert aggregated.success_rate == 100.0

    def test_success_rate_all_failed(self):
        """Test success rate when all hosts fail."""
        results = [
            SubagentResult(host=f"web-{i}", success=False, status=SubagentStatus.FAILED)
            for i in range(5)
        ]
        aggregated = AggregatedResults(results=results)

        assert aggregated.success_rate == 0.0

    def test_success_rate_empty(self):
        """Test success rate with no results."""
        aggregated = AggregatedResults(results=[])

        assert aggregated.success_rate == 0.0
        assert aggregated.total_hosts == 0

    def test_is_complete_success(self, sample_results):
        """Test is_complete_success property."""
        # Partial success
        aggregated = AggregatedResults(results=sample_results)
        assert aggregated.is_complete_success is False

        # Complete success
        success_results = [r for r in sample_results if r.success]
        aggregated_success = AggregatedResults(results=success_results)
        assert aggregated_success.is_complete_success is True

    def test_is_partial_success(self, sample_results):
        """Test is_partial_success property."""
        aggregated = AggregatedResults(results=sample_results)
        assert aggregated.is_partial_success is True

    def test_is_complete_failure(self):
        """Test is_complete_failure property."""
        failed_results = [
            SubagentResult(host=f"web-{i}", success=False, status=SubagentStatus.FAILED)
            for i in range(3)
        ]
        aggregated = AggregatedResults(results=failed_results)
        assert aggregated.is_complete_failure is True

    def test_get_successful_results(self, sample_results):
        """Test getting only successful results."""
        aggregated = AggregatedResults(results=sample_results)
        successful = aggregated.get_successful_results()

        assert len(successful) == 2
        assert all(r.success for r in successful)

    def test_get_failed_results(self, sample_results):
        """Test getting only failed results."""
        aggregated = AggregatedResults(results=sample_results)
        failed = aggregated.get_failed_results()

        assert len(failed) == 1
        assert all(not r.success for r in failed)

    def test_get_result_by_host(self, sample_results):
        """Test getting result by host name."""
        aggregated = AggregatedResults(results=sample_results)

        result = aggregated.get_result_by_host("web-02")
        assert result is not None
        assert result.host == "web-02"
        assert result.success is True

        # Non-existent host
        result = aggregated.get_result_by_host("nonexistent")
        assert result is None

    def test_compute_totals(self, sample_results):
        """Test computing aggregated totals."""
        aggregated = AggregatedResults(results=sample_results)
        aggregated.compute_totals()

        assert aggregated.total_tool_calls == 6  # 2 + 3 + 1
        assert aggregated.total_tokens_used == 300  # 100 + 150 + 50

    def test_to_summary_all_success(self):
        """Test summary for all successful results."""
        results = [
            SubagentResult(host=f"web-{i}", success=True, status=SubagentStatus.SUCCESS)
            for i in range(3)
        ]
        aggregated = AggregatedResults(results=results, total_duration_ms=5000)

        summary = aggregated.to_summary()
        assert "All succeeded" in summary
        assert "3/3" in summary
        assert "100.0%" in summary

    def test_to_summary_partial(self, sample_results):
        """Test summary for partial success."""
        aggregated = AggregatedResults(results=sample_results)

        summary = aggregated.to_summary()
        assert "Partial success" in summary
        assert "2/3" in summary
        assert "Failed hosts:" in summary
        assert "web-03" in summary

    def test_to_summary_all_failed(self):
        """Test summary for all failed results."""
        results = [
            SubagentResult(
                host=f"web-{i}",
                success=False,
                status=SubagentStatus.FAILED,
                error="Error",
            )
            for i in range(3)
        ]
        aggregated = AggregatedResults(results=results)

        summary = aggregated.to_summary()
        assert "All failed" in summary
        assert "0/3" in summary

    def test_to_summary_empty(self):
        """Test summary for empty results."""
        aggregated = AggregatedResults(results=[])

        summary = aggregated.to_summary()
        assert "No hosts targeted" in summary

    def test_to_dict(self, sample_results):
        """Test converting to dictionary."""
        aggregated = AggregatedResults(
            results=sample_results,
            execution_id="test-123",
            skill_name="disk_audit",
            task="check disk usage",
        )
        aggregated.compute_totals()

        data = aggregated.to_dict()

        assert data["execution_id"] == "test-123"
        assert data["skill_name"] == "disk_audit"
        assert data["task"] == "check disk usage"
        assert data["total_hosts"] == 3
        assert data["succeeded_hosts"] == 2
        assert data["failed_hosts"] == 1
        assert len(data["results"]) == 3


class TestSubagentFactory:
    """Tests for SubagentFactory."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock SharedContext."""
        context = MagicMock()
        context.config = MagicMock()
        # SubagentFactory.model property looks for config.model.provider and config.model.model
        context.config.model = MagicMock()
        context.config.model.provider = "anthropic"
        context.config.model.model = "claude-3-5-sonnet-latest"
        return context

    def test_factory_initialization(self, mock_context):
        """Test factory initialization."""
        from merlya.subagents.factory import SubagentFactory

        factory = SubagentFactory(mock_context)

        assert factory.context == mock_context
        assert factory.model == "anthropic:claude-3-5-sonnet-latest"

    def test_factory_with_custom_model(self, mock_context):
        """Test factory with custom model."""
        from merlya.subagents.factory import SubagentFactory

        factory = SubagentFactory(mock_context, model="custom:model")

        assert factory.model == "custom:model"

    def test_create_subagent_instance(self, mock_context):
        """Test creating a subagent instance."""
        from merlya.subagents.factory import SubagentFactory

        factory = SubagentFactory(mock_context)

        instance = factory.create(
            host="web-01",
            task="check disk",
        )

        assert instance.host == "web-01"
        assert instance.subagent_id is not None
        assert len(instance.subagent_id) == 8
        assert "web-01" in instance.system_prompt
        assert "check disk" in instance.system_prompt


class TestSubagentOrchestrator:
    """Tests for SubagentOrchestrator."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock SharedContext."""
        context = MagicMock()
        context.config = MagicMock()
        context.config.llm = MagicMock()
        context.config.llm.model_id = "anthropic:claude-3-5-sonnet-latest"
        return context

    def test_orchestrator_initialization(self, mock_context):
        """Test orchestrator initialization."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        orchestrator = SubagentOrchestrator(mock_context, max_concurrent=3)

        assert orchestrator.max_concurrent == 3
        assert orchestrator.context == mock_context

    def test_invalid_max_concurrent(self, mock_context):
        """Test validation of max_concurrent."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        with pytest.raises(ValueError):
            SubagentOrchestrator(mock_context, max_concurrent=0)

        with pytest.raises(ValueError):
            SubagentOrchestrator(mock_context, max_concurrent=100)

    @pytest.mark.asyncio
    async def test_run_on_hosts_empty(self, mock_context):
        """Test running with empty host list."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        orchestrator = SubagentOrchestrator(mock_context)

        results = await orchestrator.run_on_hosts(
            hosts=[],
            task="test task",
        )

        assert results.total_hosts == 0
        assert results.results == []

    @pytest.mark.asyncio
    async def test_run_on_host_single(self, mock_context):
        """Test running on a single host."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        orchestrator = SubagentOrchestrator(mock_context)

        # Mock the factory to avoid real agent creation
        mock_subagent = MagicMock()
        mock_subagent.subagent_id = "test-123"
        mock_run_result = MagicMock()
        mock_run_result.success = True
        mock_run_result.output = "Task completed"
        mock_run_result.error = None
        mock_run_result.to_dict.return_value = {"success": True}
        mock_subagent.run = AsyncMock(return_value=mock_run_result)

        with patch.object(orchestrator.factory, "create", return_value=mock_subagent):
            result = await orchestrator.run_on_host(
                host="web-01",
                task="test task",
                timeout=30,
            )

        assert result.host == "web-01"
        assert result.success is True
        assert result.output == "Task completed"

    @pytest.mark.asyncio
    async def test_progress_callback(self, mock_context):
        """Test progress callback is called."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        orchestrator = SubagentOrchestrator(mock_context)

        progress_calls = []

        async def on_progress(host, status, _result):
            progress_calls.append((host, status))

        # Mock the factory
        mock_subagent = MagicMock()
        mock_subagent.subagent_id = "test-123"
        mock_run_result = MagicMock()
        mock_run_result.success = True
        mock_run_result.output = "Done"
        mock_run_result.error = None
        mock_run_result.to_dict.return_value = {}
        mock_subagent.run = AsyncMock(return_value=mock_run_result)

        with patch.object(orchestrator.factory, "create", return_value=mock_subagent):
            await orchestrator.run_on_hosts(
                hosts=["web-01"],
                task="test",
                on_progress=on_progress,
            )

        assert len(progress_calls) >= 2  # starting + completed
        assert progress_calls[0] == ("web-01", "starting")
        assert progress_calls[1] == ("web-01", "completed")

    @pytest.mark.asyncio
    async def test_get_active_executions(self, mock_context):
        """Test getting active executions."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        orchestrator = SubagentOrchestrator(mock_context)

        # Initially empty
        assert await orchestrator.get_active_executions() == {}

        # Simulate some executions
        orchestrator._active_executions["exec-1"] = "running"
        orchestrator._active_executions["exec-2"] = "completed"

        active = await orchestrator.get_active_executions()
        assert "exec-1" in active
        assert active["exec-1"] == "running"

    @pytest.mark.asyncio
    async def test_clear_execution_history(self, mock_context):
        """Test clearing execution history."""
        from merlya.subagents.orchestrator import SubagentOrchestrator

        orchestrator = SubagentOrchestrator(mock_context)

        orchestrator._active_executions["exec-1"] = "running"
        await orchestrator.clear_execution_history()

        assert await orchestrator.get_active_executions() == {}
