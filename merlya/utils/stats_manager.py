"""
Stats Manager - Centralized metrics collection and reporting service.

Provides a simple API for collecting timing metrics across the application:
- LLM call timing
- Query execution timing
- Action execution timing
- Embedding generation timing
- Agent task timing

Usage:
    from merlya.utils.stats_manager import get_stats_manager

    stats = get_stats_manager()

    # Context manager for automatic timing
    with stats.time_llm_call("openrouter", "gpt-4") as timer:
        response = llm.generate(prompt)
        timer.set_tokens(100, 50)  # prompt, completion

    # Manual timing
    timer = stats.start_timer()
    result = execute_action()
    stats.record_action("localhost", "local", timer.elapsed_ms(), 0, True, "low")
"""

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

from merlya.memory.persistence.metrics_repository import (
    ActionMetric,
    AgentTaskMetric,
    EmbeddingMetric,
    LLMCallMetric,
    QueryMetric,
    get_metrics_repository,
)
from merlya.utils.logger import logger


@dataclass
class Timer:
    """Simple timer for measuring elapsed time."""
    start_time: float = field(default_factory=time.perf_counter)
    end_time: Optional[float] = None

    def stop(self) -> float:
        """Stop the timer and return elapsed time in ms."""
        self.end_time = time.perf_counter()
        return self.elapsed_ms()

    def elapsed_ms(self) -> int:
        """Get elapsed time in milliseconds."""
        end = self.end_time if self.end_time is not None else time.perf_counter()
        return int((end - self.start_time) * 1000)

    def elapsed_seconds(self) -> float:
        """Get elapsed time in seconds."""
        end = self.end_time if self.end_time is not None else time.perf_counter()
        return end - self.start_time


@dataclass
class LLMTimerContext:
    """Context for LLM call timing with token tracking."""
    timer: Timer
    provider: str
    model: str
    task_type: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    success: bool = True
    error: Optional[str] = None

    def set_tokens(self, prompt: int, completion: int) -> None:
        """Set token counts after completion."""
        self.prompt_tokens = prompt
        self.completion_tokens = completion

    def set_error(self, error: str) -> None:
        """Mark as failed with error."""
        self.success = False
        self.error = error


@dataclass
class EmbeddingTimerContext:
    """Context for embedding timing with metadata."""
    timer: Timer
    model: str
    purpose: Optional[str] = None
    input_tokens: int = 0
    dimensions: int = 0
    batch_size: int = 1
    success: bool = True
    error: Optional[str] = None

    def set_metadata(
        self,
        input_tokens: int = 0,
        dimensions: int = 0,
        batch_size: int = 1
    ) -> None:
        """Set embedding metadata."""
        self.input_tokens = input_tokens
        self.dimensions = dimensions
        self.batch_size = batch_size

    def set_error(self, error: str) -> None:
        """Mark as failed."""
        self.success = False
        self.error = error


@dataclass
class AgentTaskTimerContext:
    """Context for agent task timing."""
    timer: Timer
    agent_name: str
    task_type: str
    session_id: Optional[str] = None
    steps_count: int = 0
    tools_used: List[str] = field(default_factory=list)
    llm_calls: int = 0
    success: bool = True
    error: Optional[str] = None

    def add_step(self) -> None:
        """Increment step count."""
        self.steps_count += 1

    def add_tool(self, tool: str) -> None:
        """Add a tool to the used list."""
        if tool not in self.tools_used:
            self.tools_used.append(tool)

    def add_llm_call(self) -> None:
        """Increment LLM call count."""
        self.llm_calls += 1

    def set_error(self, error: str) -> None:
        """Mark as failed."""
        self.success = False
        self.error = error


# Thread-safe singleton lock
_stats_lock = threading.Lock()


class StatsManager:
    """
    Centralized statistics collection and reporting service.

    Provides convenient methods for timing various operations and
    recording metrics to the persistence layer.
    """

    _instance: Optional["StatsManager"] = None
    _initialized: bool = False

    def __new__(cls, db_path: Optional[str] = None):
        """Thread-safe singleton pattern."""
        with _stats_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        """Initialize stats manager."""
        with _stats_lock:
            if StatsManager._initialized:
                return

            self._repository = get_metrics_repository(db_path)
            self._current_session_id: Optional[str] = None
            StatsManager._initialized = True
            logger.debug("📊 StatsManager initialized")

    def set_session_id(self, session_id: str) -> None:
        """Set the current session ID for query metrics."""
        self._current_session_id = session_id

    def start_timer(self) -> Timer:
        """Create and start a new timer."""
        return Timer()

    # =========================================================================
    # LLM Call Metrics
    # =========================================================================

    @contextmanager
    def time_llm_call(
        self,
        provider: str,
        model: str,
        task_type: Optional[str] = None
    ) -> Generator[LLMTimerContext, None, None]:
        """Context manager for timing LLM calls."""
        ctx = LLMTimerContext(
            timer=Timer(),
            provider=provider,
            model=model,
            task_type=task_type,
        )
        try:
            yield ctx
        except Exception as e:
            ctx.set_error(str(e))
            raise
        finally:
            ctx.timer.stop()
            self._record_llm_call(ctx)

    def _record_llm_call(self, ctx: LLMTimerContext) -> None:
        """Record LLM call metric."""
        try:
            metric = LLMCallMetric(
                provider=ctx.provider,
                model=ctx.model,
                prompt_tokens=ctx.prompt_tokens,
                completion_tokens=ctx.completion_tokens,
                total_tokens=ctx.prompt_tokens + ctx.completion_tokens,
                response_time_ms=ctx.timer.elapsed_ms(),
                success=ctx.success,
                error=ctx.error,
                task_type=ctx.task_type,
            )
            self._repository.log_llm_call(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record LLM metric: {e}")

    def record_llm_call(
        self,
        provider: str,
        model: str,
        response_time_ms: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        success: bool = True,
        error: Optional[str] = None,
        task_type: Optional[str] = None
    ) -> None:
        """Directly record an LLM call metric."""
        try:
            metric = LLMCallMetric(
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                response_time_ms=response_time_ms,
                success=success,
                error=error,
                task_type=task_type,
            )
            self._repository.log_llm_call(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record LLM metric: {e}")

    # =========================================================================
    # Query Metrics
    # =========================================================================

    @contextmanager
    def time_query(
        self,
        session_id: Optional[str] = None
    ) -> Generator[Timer, None, None]:
        """Context manager for timing query execution."""
        timer = Timer()
        try:
            yield timer
        finally:
            timer.stop()

    def record_query(
        self,
        query_length: int,
        response_length: int,
        total_time_ms: int,
        llm_time_ms: int = 0,
        tool_time_ms: int = 0,
        actions_count: int = 0,
        success: bool = True,
        error: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> None:
        """Record a query execution metric."""
        try:
            sid = session_id or self._current_session_id or "unknown"
            metric = QueryMetric(
                session_id=sid,
                query_length=query_length,
                response_length=response_length,
                total_time_ms=total_time_ms,
                llm_time_ms=llm_time_ms,
                tool_time_ms=tool_time_ms,
                actions_count=actions_count,
                success=success,
                error=error,
            )
            self._repository.log_query_metric(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record query metric: {e}")

    # =========================================================================
    # Action Metrics
    # =========================================================================

    def record_action(
        self,
        target: str,
        command_type: str,  # "local" or "remote"
        duration_ms: int,
        exit_code: int,
        success: bool,
        risk_level: str
    ) -> None:
        """Record an action execution metric."""
        try:
            metric = ActionMetric(
                target=target,
                command_type=command_type,
                duration_ms=duration_ms,
                exit_code=exit_code,
                success=success,
                risk_level=risk_level,
            )
            self._repository.log_action_metric(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record action metric: {e}")

    # =========================================================================
    # Embedding Metrics
    # =========================================================================

    @contextmanager
    def time_embedding(
        self,
        model: str,
        purpose: Optional[str] = None
    ) -> Generator[EmbeddingTimerContext, None, None]:
        """Context manager for timing embedding generation."""
        ctx = EmbeddingTimerContext(
            timer=Timer(),
            model=model,
            purpose=purpose,
        )
        try:
            yield ctx
        except Exception as e:
            ctx.set_error(str(e))
            raise
        finally:
            ctx.timer.stop()
            self._record_embedding(ctx)

    def _record_embedding(self, ctx: EmbeddingTimerContext) -> None:
        """Record embedding metric."""
        try:
            metric = EmbeddingMetric(
                model=ctx.model,
                input_tokens=ctx.input_tokens,
                dimensions=ctx.dimensions,
                batch_size=ctx.batch_size,
                duration_ms=ctx.timer.elapsed_ms(),
                success=ctx.success,
                error=ctx.error,
                purpose=ctx.purpose,
            )
            self._repository.log_embedding_metric(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record embedding metric: {e}")

    def record_embedding(
        self,
        model: str,
        duration_ms: int,
        input_tokens: int = 0,
        dimensions: int = 0,
        batch_size: int = 1,
        success: bool = True,
        error: Optional[str] = None,
        purpose: Optional[str] = None
    ) -> None:
        """Directly record an embedding metric."""
        try:
            metric = EmbeddingMetric(
                model=model,
                input_tokens=input_tokens,
                dimensions=dimensions,
                batch_size=batch_size,
                duration_ms=duration_ms,
                success=success,
                error=error,
                purpose=purpose,
            )
            self._repository.log_embedding_metric(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record embedding metric: {e}")

    # =========================================================================
    # Agent Task Metrics
    # =========================================================================

    @contextmanager
    def time_agent_task(
        self,
        agent_name: str,
        task_type: str,
        session_id: Optional[str] = None
    ) -> Generator[AgentTaskTimerContext, None, None]:
        """Context manager for timing agent task execution."""
        ctx = AgentTaskTimerContext(
            timer=Timer(),
            agent_name=agent_name,
            task_type=task_type,
            session_id=session_id or self._current_session_id,
        )
        try:
            yield ctx
        except Exception as e:
            ctx.set_error(str(e))
            raise
        finally:
            ctx.timer.stop()
            self._record_agent_task(ctx)

    def _record_agent_task(self, ctx: AgentTaskTimerContext) -> None:
        """Record agent task metric."""
        try:
            metric = AgentTaskMetric(
                agent_name=ctx.agent_name,
                task_type=ctx.task_type,
                duration_ms=ctx.timer.elapsed_ms(),
                success=ctx.success,
                error=ctx.error,
                steps_count=ctx.steps_count,
                tools_used=json.dumps(ctx.tools_used) if ctx.tools_used else None,
                llm_calls=ctx.llm_calls,
                session_id=ctx.session_id,
            )
            self._repository.log_agent_task_metric(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record agent task metric: {e}")

    def record_agent_task(
        self,
        agent_name: str,
        task_type: str,
        duration_ms: int,
        success: bool = True,
        error: Optional[str] = None,
        steps_count: int = 0,
        tools_used: Optional[List[str]] = None,
        llm_calls: int = 0,
        session_id: Optional[str] = None
    ) -> None:
        """Directly record an agent task metric."""
        try:
            metric = AgentTaskMetric(
                agent_name=agent_name,
                task_type=task_type,
                duration_ms=duration_ms,
                success=success,
                error=error,
                steps_count=steps_count,
                tools_used=json.dumps(tools_used) if tools_used else None,
                llm_calls=llm_calls,
                session_id=session_id or self._current_session_id,
            )
            self._repository.log_agent_task_metric(metric)
        except Exception as e:
            logger.warning(f"⚠️ Failed to record agent task metric: {e}")

    # =========================================================================
    # Statistics Retrieval
    # =========================================================================

    def get_dashboard(self, hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics."""
        return self._repository.get_dashboard_stats(hours=hours)

    def get_llm_stats(self, provider: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
        """Get LLM usage statistics."""
        return self._repository.get_llm_stats(provider=provider, hours=hours)

    def get_query_stats(self, session_id: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
        """Get query execution statistics."""
        return self._repository.get_query_stats(session_id=session_id, hours=hours)

    def get_action_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get action execution statistics."""
        return self._repository.get_action_stats(hours=hours)

    def get_embedding_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get embedding generation statistics."""
        return self._repository.get_embedding_stats(hours=hours)

    def get_agent_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get agent task statistics."""
        return self._repository.get_agent_task_stats(hours=hours)

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get statistics for a specific session."""
        return self._repository.get_session_stats(session_id)

    def get_baselines(
        self,
        metric_type: Optional[str] = None,
        period: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get performance baselines."""
        return self._repository.get_baselines(metric_type, period, limit)

    def calculate_baselines(self, metric_type: str, period: str = "daily") -> bool:
        """Calculate and store performance baselines."""
        result = self._repository.calculate_baselines(metric_type, period)
        return result is not None

    def cleanup(self, days: int = 30) -> int:
        """Clean up old metrics."""
        return self._repository.cleanup_old_metrics(days)

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with _stats_lock:
            cls._instance = None
            cls._initialized = False


def get_stats_manager(db_path: Optional[str] = None) -> StatsManager:
    """Get the stats manager singleton."""
    return StatsManager(db_path)
