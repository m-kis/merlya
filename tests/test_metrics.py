"""
Tests for the metrics and statistics system.

Tests:
- MetricsRepository: persistence of metrics
- StatsManager: collection and aggregation
- Integration: timing context managers
"""

import os
import tempfile
import time
from datetime import datetime, timedelta

import pytest

from merlya.memory.persistence.metrics_repository import (
    ActionMetric,
    AgentTaskMetric,
    EmbeddingMetric,
    LLMCallMetric,
    MetricsRepository,
    QueryMetric,
)
from merlya.utils.stats_manager import (
    StatsManager,
    Timer,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest.fixture
def metrics_repo(temp_db):
    """Create a fresh MetricsRepository for testing."""
    MetricsRepository.reset_instance()
    repo = MetricsRepository(db_path=temp_db)
    yield repo
    MetricsRepository.reset_instance()


@pytest.fixture
def stats_manager(temp_db):
    """Create a fresh StatsManager for testing."""
    StatsManager.reset_instance()
    MetricsRepository.reset_instance()
    manager = StatsManager(db_path=temp_db)
    yield manager
    StatsManager.reset_instance()
    MetricsRepository.reset_instance()


class TestTimer:
    """Tests for the Timer class."""

    def test_timer_creation(self):
        """Test timer creates with current time."""
        timer = Timer()
        assert timer.start_time > 0
        assert timer.end_time is None

    def test_timer_stop(self):
        """Test timer stop records end time."""
        timer = Timer()
        time.sleep(0.01)  # 10ms
        elapsed = timer.stop()
        assert elapsed >= 10
        assert timer.end_time is not None

    def test_timer_elapsed_ms(self):
        """Test elapsed_ms returns correct duration."""
        timer = Timer()
        time.sleep(0.05)  # 50ms
        elapsed = timer.elapsed_ms()
        assert 40 <= elapsed <= 100  # Allow some tolerance

    def test_timer_elapsed_seconds(self):
        """Test elapsed_seconds returns correct duration."""
        timer = Timer()
        time.sleep(0.1)  # 100ms
        elapsed = timer.elapsed_seconds()
        assert 0.09 <= elapsed <= 0.2


class TestMetricsRepository:
    """Tests for MetricsRepository."""

    def test_singleton_pattern(self, temp_db):
        """Test singleton returns same instance."""
        MetricsRepository.reset_instance()
        repo1 = MetricsRepository(db_path=temp_db)
        repo2 = MetricsRepository()
        assert repo1 is repo2
        MetricsRepository.reset_instance()

    def test_log_llm_call(self, metrics_repo):
        """Test logging LLM call metrics."""
        metric = LLMCallMetric(
            provider="openrouter",
            model="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            response_time_ms=500,
            success=True,
            task_type="synthesis",
        )
        metric_id = metrics_repo.log_llm_call(metric)
        assert metric_id > 0

    def test_get_llm_stats(self, metrics_repo):
        """Test retrieving LLM statistics."""
        # Log some metrics
        for i in range(5):
            prompt_tokens = 100 + i * 10
            completion_tokens = 50
            metric = LLMCallMetric(
                provider="openrouter",
                model="gpt-4",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                response_time_ms=400 + i * 50,
                success=i != 2,  # One failure
            )
            metrics_repo.log_llm_call(metric)

        stats = metrics_repo.get_llm_stats(hours=1)
        assert stats["total_calls"] == 5
        assert stats["successful_calls"] == 4
        assert stats["success_rate"] == 0.8
        assert stats["total_tokens"] > 0
        assert len(stats["by_provider"]) >= 1

    def test_log_query_metric(self, metrics_repo):
        """Test logging query metrics."""
        metric = QueryMetric(
            session_id="test-session",
            query_length=50,
            response_length=200,
            total_time_ms=1500,
            llm_time_ms=1000,
            tool_time_ms=500,
            actions_count=2,
            success=True,
        )
        metric_id = metrics_repo.log_query_metric(metric)
        assert metric_id > 0

    def test_get_query_stats(self, metrics_repo):
        """Test retrieving query statistics."""
        for i in range(10):
            metric = QueryMetric(
                session_id="test-session",
                query_length=50,
                response_length=200,
                total_time_ms=1000 + i * 100,
                success=True,
            )
            metrics_repo.log_query_metric(metric)

        stats = metrics_repo.get_query_stats(hours=1)
        assert stats["total_queries"] == 10
        assert stats["success_rate"] == 1.0
        assert stats["p50_time_ms"] > 0
        assert stats["p95_time_ms"] > stats["p50_time_ms"]

    def test_log_action_metric(self, metrics_repo):
        """Test logging action metrics."""
        metric = ActionMetric(
            target="localhost",
            command_type="local",
            duration_ms=250,
            exit_code=0,
            success=True,
            risk_level="low",
        )
        metric_id = metrics_repo.log_action_metric(metric)
        assert metric_id > 0

    def test_get_action_stats(self, metrics_repo):
        """Test retrieving action statistics."""
        for cmd_type in ["local", "local", "remote"]:
            metric = ActionMetric(
                target="localhost" if cmd_type == "local" else "remote-host",
                command_type=cmd_type,
                duration_ms=100,
                exit_code=0,
                success=True,
                risk_level="low",
            )
            metrics_repo.log_action_metric(metric)

        stats = metrics_repo.get_action_stats(hours=1)
        assert stats["total_actions"] == 3
        assert len(stats["by_command_type"]) == 2

    def test_log_embedding_metric(self, metrics_repo):
        """Test logging embedding metrics."""
        metric = EmbeddingMetric(
            model="all-MiniLM-L6-v2",
            input_tokens=50,
            dimensions=384,
            batch_size=1,
            duration_ms=100,
            success=True,
            purpose="triage",
        )
        metric_id = metrics_repo.log_embedding_metric(metric)
        assert metric_id > 0

    def test_get_embedding_stats(self, metrics_repo):
        """Test retrieving embedding statistics."""
        for purpose in ["triage", "search", "triage"]:
            metric = EmbeddingMetric(
                model="all-MiniLM-L6-v2",
                input_tokens=50,
                dimensions=384,
                duration_ms=80,
                success=True,
                purpose=purpose,
            )
            metrics_repo.log_embedding_metric(metric)

        stats = metrics_repo.get_embedding_stats(hours=1)
        assert stats["total_calls"] == 3
        assert len(stats["by_purpose"]) == 2

    def test_log_agent_task_metric(self, metrics_repo):
        """Test logging agent task metrics."""
        metric = AgentTaskMetric(
            agent_name="DiagnosticAgent",
            task_type="diagnosis",
            duration_ms=5000,
            success=True,
            steps_count=3,
            tools_used='["shell", "ssh"]',
            llm_calls=2,
            session_id="test-session",
        )
        metric_id = metrics_repo.log_agent_task_metric(metric)
        assert metric_id > 0

    def test_get_agent_task_stats(self, metrics_repo):
        """Test retrieving agent task statistics."""
        for agent in ["DiagnosticAgent", "DiagnosticAgent", "RemediationAgent"]:
            metric = AgentTaskMetric(
                agent_name=agent,
                task_type="execution",
                duration_ms=2000,
                success=True,
                llm_calls=2,
            )
            metrics_repo.log_agent_task_metric(metric)

        stats = metrics_repo.get_agent_task_stats(hours=1)
        assert stats["total_tasks"] == 3
        assert stats["total_llm_calls"] == 6
        assert len(stats["by_agent"]) == 2

    def test_get_dashboard_stats(self, metrics_repo):
        """Test dashboard combines all stats."""
        # Add some data
        metrics_repo.log_llm_call(LLMCallMetric(
            provider="test", model="test", response_time_ms=100
        ))
        metrics_repo.log_query_metric(QueryMetric(
            session_id="test", query_length=10, response_length=50, total_time_ms=200
        ))

        dashboard = metrics_repo.get_dashboard_stats(hours=1)
        assert "llm" in dashboard
        assert "queries" in dashboard
        assert "actions" in dashboard
        assert "embeddings" in dashboard
        assert "agent_tasks" in dashboard
        assert "generated_at" in dashboard

    def test_get_session_stats(self, metrics_repo):
        """Test session-specific statistics."""
        session_id = "test-session-123"
        for _ in range(3):
            metrics_repo.log_query_metric(QueryMetric(
                session_id=session_id,
                query_length=10,
                response_length=50,
                total_time_ms=500,
                success=True,
            ))

        stats = metrics_repo.get_session_stats(session_id)
        assert stats["session_id"] == session_id
        assert stats["total_queries"] == 3

    def test_cleanup_old_metrics(self, metrics_repo):
        """Test cleanup removes old metrics."""
        # Log metrics with old timestamps
        old_date = (datetime.now() - timedelta(days=60)).isoformat()
        with metrics_repo._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO llm_calls (provider, model, response_time_ms, success, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, ("test", "test", 100, 1, old_date))

        # Also add a recent one
        metrics_repo.log_llm_call(LLMCallMetric(
            provider="test", model="test", response_time_ms=100
        ))

        deleted = metrics_repo.cleanup_old_metrics(days=30)
        assert deleted >= 1

        # Verify only recent remains
        stats = metrics_repo.get_llm_stats(hours=24 * 365)  # Wide range
        assert stats["total_calls"] == 1

    def test_percentile_calculation(self, metrics_repo):
        """Test percentile calculations."""
        data = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        p50 = metrics_repo._percentile(data, 50)
        p95 = metrics_repo._percentile(data, 95)
        p99 = metrics_repo._percentile(data, 99)

        assert 50 <= p50 <= 60
        assert 90 <= p95 <= 100
        assert p99 >= p95


class TestStatsManager:
    """Tests for StatsManager."""

    def test_singleton_pattern(self, temp_db):
        """Test singleton returns same instance."""
        StatsManager.reset_instance()
        MetricsRepository.reset_instance()
        mgr1 = StatsManager(db_path=temp_db)
        mgr2 = StatsManager()
        assert mgr1 is mgr2
        StatsManager.reset_instance()
        MetricsRepository.reset_instance()

    def test_set_session_id(self, stats_manager):
        """Test setting session ID."""
        stats_manager.set_session_id("test-session")
        assert stats_manager._current_session_id == "test-session"

    def test_time_llm_call_context_manager(self, stats_manager):
        """Test LLM call timing context manager."""
        with stats_manager.time_llm_call("openrouter", "gpt-4") as timer:
            time.sleep(0.05)
            timer.set_tokens(100, 50)

        # Verify metric was recorded
        stats = stats_manager.get_llm_stats(hours=1)
        assert stats["total_calls"] == 1
        assert stats["total_tokens"] == 150

    def test_time_llm_call_error_handling(self, stats_manager):
        """Test LLM call timing records errors."""
        try:
            with stats_manager.time_llm_call("openrouter", "gpt-4"):
                raise ValueError("Test error")
        except ValueError:
            pass

        stats = stats_manager.get_llm_stats(hours=1)
        assert stats["total_calls"] == 1
        assert stats["successful_calls"] == 0

    def test_record_query(self, stats_manager):
        """Test direct query recording."""
        stats_manager.set_session_id("test-session")
        stats_manager.record_query(
            query_length=50,
            response_length=200,
            total_time_ms=1500,
            llm_time_ms=1000,
            success=True,
        )

        stats = stats_manager.get_query_stats(hours=1)
        assert stats["total_queries"] == 1

    def test_record_action(self, stats_manager):
        """Test direct action recording."""
        stats_manager.record_action(
            target="localhost",
            command_type="local",
            duration_ms=250,
            exit_code=0,
            success=True,
            risk_level="low",
        )

        stats = stats_manager.get_action_stats(hours=1)
        assert stats["total_actions"] == 1

    def test_time_embedding_context_manager(self, stats_manager):
        """Test embedding timing context manager."""
        with stats_manager.time_embedding("all-MiniLM-L6-v2", purpose="triage") as ctx:
            time.sleep(0.02)
            ctx.set_metadata(input_tokens=50, dimensions=384, batch_size=1)

        stats = stats_manager.get_embedding_stats(hours=1)
        assert stats["total_calls"] == 1

    def test_time_agent_task_context_manager(self, stats_manager):
        """Test agent task timing context manager."""
        with stats_manager.time_agent_task("DiagnosticAgent", "diagnosis") as ctx:
            time.sleep(0.02)
            ctx.add_step()
            ctx.add_step()
            ctx.add_tool("shell")
            ctx.add_llm_call()

        stats = stats_manager.get_agent_stats(hours=1)
        assert stats["total_tasks"] == 1
        assert stats["total_steps"] == 2

    def test_get_dashboard(self, stats_manager):
        """Test dashboard retrieval."""
        stats_manager.record_action("localhost", "local", 100, 0, True, "low")
        dashboard = stats_manager.get_dashboard(hours=1)
        assert "llm" in dashboard
        assert "queries" in dashboard
        assert "actions" in dashboard

    def test_cleanup(self, stats_manager):
        """Test cleanup through manager."""
        stats_manager.record_action("localhost", "local", 100, 0, True, "low")
        # Cleanup things older than 30 days (nothing should be deleted)
        deleted = stats_manager.cleanup(days=30)
        assert deleted == 0


class TestIntegration:
    """Integration tests for the metrics system."""

    def test_full_workflow(self, stats_manager):
        """Test a complete workflow with all metric types."""
        stats_manager.set_session_id("integration-test")

        # Simulate LLM call
        with stats_manager.time_llm_call("openrouter", "claude-3-sonnet") as llm_ctx:
            time.sleep(0.01)
            llm_ctx.set_tokens(200, 100)

        # Simulate embedding
        with stats_manager.time_embedding("all-MiniLM-L6-v2", "triage") as emb_ctx:
            time.sleep(0.01)
            emb_ctx.set_metadata(input_tokens=50, dimensions=384)

        # Simulate agent task
        with stats_manager.time_agent_task("DiagnosticAgent", "diagnosis") as agent_ctx:
            agent_ctx.add_step()
            agent_ctx.add_tool("shell")
            agent_ctx.add_llm_call()
            time.sleep(0.01)

        # Record query
        stats_manager.record_query(
            query_length=100,
            response_length=500,
            total_time_ms=2000,
            llm_time_ms=1500,
            actions_count=1,
            success=True,
        )

        # Record action
        stats_manager.record_action(
            target="localhost",
            command_type="local",
            duration_ms=150,
            exit_code=0,
            success=True,
            risk_level="low",
        )

        # Get dashboard
        dashboard = stats_manager.get_dashboard(hours=1)

        assert dashboard["llm"]["total_calls"] == 1
        assert dashboard["queries"]["total_queries"] == 1
        assert dashboard["actions"]["total_actions"] == 1
        assert dashboard["embeddings"]["total_calls"] == 1
        assert dashboard["agent_tasks"]["total_tasks"] == 1

        # Get session stats
        session_stats = stats_manager.get_session_stats("integration-test")
        assert session_stats["total_queries"] == 1
