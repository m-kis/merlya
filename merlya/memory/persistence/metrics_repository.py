"""
Metrics Repository - Persistence layer for application statistics.

Tracks LLM calls, query execution times, action durations, and performance baselines.
Provides aggregation methods for dashboard and analysis.
"""

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from merlya.utils.logger import logger


class MetricType(Enum):
    """Types of metrics tracked."""
    LLM_CALL = "llm_call"
    QUERY = "query"
    ACTION = "action"
    CACHE = "cache"
    SCAN = "scan"
    EMBEDDING = "embedding"
    AGENT_TASK = "agent_task"


@dataclass
class EmbeddingMetric:
    """Metric for embedding generation."""
    model: str
    input_tokens: int = 0
    dimensions: int = 0
    batch_size: int = 1
    duration_ms: int = 0
    success: bool = True
    error: Optional[str] = None
    purpose: Optional[str] = None  # triage, search, similarity, etc.
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class AgentTaskMetric:
    """Metric for agent task execution."""
    agent_name: str
    task_type: str
    duration_ms: int
    success: bool = True
    error: Optional[str] = None
    steps_count: int = 0
    tools_used: Optional[str] = None  # JSON list
    llm_calls: int = 0
    session_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class LLMCallMetric:
    """Metric for a single LLM API call."""
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_time_ms: int = 0
    success: bool = True
    error: Optional[str] = None
    task_type: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class QueryMetric:
    """Metric for user query processing."""
    session_id: str
    query_length: int
    response_length: int
    total_time_ms: int
    llm_time_ms: int = 0
    tool_time_ms: int = 0
    actions_count: int = 0
    success: bool = True
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ActionMetric:
    """Metric for command execution."""
    target: str
    command_type: str  # local, remote
    duration_ms: int
    exit_code: int
    success: bool
    risk_level: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PerformanceBaseline:
    """Aggregated performance statistics."""
    metric_type: str
    period: str  # hourly, daily, weekly
    count: int
    avg_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    p99_duration_ms: float
    success_rate: float
    period_start: str
    period_end: str


# Thread-safe singleton lock
_metrics_lock = threading.Lock()


class MetricsRepository:
    """
    Repository for storing and querying application metrics.

    Provides:
    - LLM call tracking (provider, tokens, response time)
    - Query execution metrics (total time, breakdown)
    - Action execution metrics (duration, success rate)
    - Performance baseline calculation (p50, p95, p99)
    - Aggregation and dashboard queries
    """

    _instance: Optional["MetricsRepository"] = None
    _initialized: bool = False

    def __new__(cls, db_path: Optional[str] = None):
        """Thread-safe singleton pattern."""
        with _metrics_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        """Initialize metrics repository."""
        with _metrics_lock:
            if MetricsRepository._initialized:
                return

            if db_path:
                db_path_obj = Path(db_path)
                db_path_obj.parent.mkdir(parents=True, exist_ok=True)
                self.db_path = str(db_path_obj)
            else:
                merlya_dir = Path.home() / ".merlya"
                merlya_dir.mkdir(parents=True, exist_ok=True)
                self.db_path = str(merlya_dir / "metrics.db")

            self._init_tables()
            MetricsRepository._initialized = True
            logger.debug(f"MetricsRepository initialized at {self.db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection with Row factory."""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self, *, commit: bool = False) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = self._get_connection()
        try:
            yield conn
            if commit:
                conn.commit()
        except Exception:
            if commit:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _init_tables(self) -> None:
        """Initialize all metrics tables."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            # LLM calls table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS llm_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    response_time_ms INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error TEXT,
                    task_type TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_calls_created
                ON llm_calls(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_calls_provider
                ON llm_calls(provider, created_at)
            """)

            # Query metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS query_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    query_length INTEGER DEFAULT 0,
                    response_length INTEGER DEFAULT 0,
                    total_time_ms INTEGER DEFAULT 0,
                    llm_time_ms INTEGER DEFAULT 0,
                    tool_time_ms INTEGER DEFAULT 0,
                    actions_count INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_metrics_session
                ON query_metrics(session_id, created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_metrics_created
                ON query_metrics(created_at)
            """)

            # Action metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS action_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
                    command_type TEXT NOT NULL,
                    duration_ms INTEGER DEFAULT 0,
                    exit_code INTEGER,
                    success INTEGER DEFAULT 1,
                    risk_level TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_action_metrics_created
                ON action_metrics(created_at)
            """)

            # Embedding metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS embedding_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    dimensions INTEGER DEFAULT 0,
                    batch_size INTEGER DEFAULT 1,
                    duration_ms INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error TEXT,
                    purpose TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_embedding_metrics_created
                ON embedding_metrics(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_embedding_metrics_model
                ON embedding_metrics(model, created_at)
            """)

            # Agent task metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_task_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    duration_ms INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 1,
                    error TEXT,
                    steps_count INTEGER DEFAULT 0,
                    tools_used TEXT,
                    llm_calls INTEGER DEFAULT 0,
                    session_id TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_task_created
                ON agent_task_metrics(created_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_task_agent
                ON agent_task_metrics(agent_name, created_at)
            """)

            # Performance baselines table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS performance_baselines (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_type TEXT NOT NULL,
                    period TEXT NOT NULL,
                    count INTEGER DEFAULT 0,
                    avg_duration_ms REAL DEFAULT 0,
                    p50_duration_ms REAL DEFAULT 0,
                    p95_duration_ms REAL DEFAULT 0,
                    p99_duration_ms REAL DEFAULT 0,
                    success_rate REAL DEFAULT 0,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(metric_type, period, period_start)
                )
            """)

    # =========================================================================
    # LLM Call Metrics
    # =========================================================================

    def log_llm_call(self, metric: LLMCallMetric) -> int:
        """Log an LLM API call metric."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO llm_calls (
                    provider, model, prompt_tokens, completion_tokens,
                    total_tokens, response_time_ms, success, error,
                    task_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.provider,
                metric.model,
                metric.prompt_tokens,
                metric.completion_tokens,
                metric.total_tokens,
                metric.response_time_ms,
                1 if metric.success else 0,
                metric.error,
                metric.task_type,
                metric.created_at,
            ))
            return cursor.lastrowid or 0

    def get_llm_stats(
        self,
        provider: Optional[str] = None,
        hours: int = 24
    ) -> Dict[str, Any]:
        """Get LLM usage statistics."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            cursor = conn.cursor()

            # Build query
            where_clause = "created_at >= ?"
            params: List[Any] = [cutoff]
            if provider:
                where_clause += " AND provider = ?"
                params.append(provider)

            # Aggregate stats
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_calls,
                    SUM(prompt_tokens) as total_prompt_tokens,
                    SUM(completion_tokens) as total_completion_tokens,
                    SUM(total_tokens) as total_tokens,
                    AVG(response_time_ms) as avg_response_time_ms,
                    MIN(response_time_ms) as min_response_time_ms,
                    MAX(response_time_ms) as max_response_time_ms
                FROM llm_calls
                WHERE {where_clause}
            """, params)

            row = cursor.fetchone()

            # Provider breakdown
            cursor.execute(f"""
                SELECT
                    provider,
                    COUNT(*) as calls,
                    SUM(total_tokens) as tokens,
                    AVG(response_time_ms) as avg_time_ms
                FROM llm_calls
                WHERE {where_clause}
                GROUP BY provider
            """, params)

            by_provider = [dict(r) for r in cursor.fetchall()]

            # Model breakdown
            cursor.execute(f"""
                SELECT
                    model,
                    COUNT(*) as calls,
                    AVG(response_time_ms) as avg_time_ms
                FROM llm_calls
                WHERE {where_clause}
                GROUP BY model
                ORDER BY calls DESC
                LIMIT 10
            """, params)

            by_model = [dict(r) for r in cursor.fetchall()]

            return {
                "period_hours": hours,
                "total_calls": row["total_calls"] or 0,
                "successful_calls": row["successful_calls"] or 0,
                "success_rate": (row["successful_calls"] or 0) / (row["total_calls"] or 1),
                "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                "total_completion_tokens": row["total_completion_tokens"] or 0,
                "total_tokens": row["total_tokens"] or 0,
                "avg_response_time_ms": round(row["avg_response_time_ms"] or 0, 2),
                "min_response_time_ms": row["min_response_time_ms"] or 0,
                "max_response_time_ms": row["max_response_time_ms"] or 0,
                "by_provider": by_provider,
                "by_model": by_model,
            }

    # =========================================================================
    # Query Metrics
    # =========================================================================

    def log_query_metric(self, metric: QueryMetric) -> int:
        """Log a query execution metric."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO query_metrics (
                    session_id, query_length, response_length,
                    total_time_ms, llm_time_ms, tool_time_ms,
                    actions_count, success, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.session_id,
                metric.query_length,
                metric.response_length,
                metric.total_time_ms,
                metric.llm_time_ms,
                metric.tool_time_ms,
                metric.actions_count,
                1 if metric.success else 0,
                metric.error,
                metric.created_at,
            ))
            return cursor.lastrowid or 0

    def get_query_stats(self, session_id: Optional[str] = None, hours: int = 24) -> Dict[str, Any]:
        """Get query execution statistics."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            cursor = conn.cursor()

            where_clause = "created_at >= ?"
            params: List[Any] = [cutoff]
            if session_id:
                where_clause += " AND session_id = ?"
                params.append(session_id)

            cursor.execute(f"""
                SELECT
                    COUNT(*) as total_queries,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(total_time_ms) as avg_total_time_ms,
                    AVG(llm_time_ms) as avg_llm_time_ms,
                    AVG(tool_time_ms) as avg_tool_time_ms,
                    MIN(total_time_ms) as min_time_ms,
                    MAX(total_time_ms) as max_time_ms,
                    SUM(actions_count) as total_actions
                FROM query_metrics
                WHERE {where_clause}
            """, params)

            row = cursor.fetchone()

            # Calculate percentiles
            cursor.execute(f"""
                SELECT total_time_ms
                FROM query_metrics
                WHERE {where_clause}
                ORDER BY total_time_ms
            """, params)

            times = [r["total_time_ms"] for r in cursor.fetchall()]
            p50 = self._percentile(times, 50)
            p95 = self._percentile(times, 95)
            p99 = self._percentile(times, 99)

            return {
                "period_hours": hours,
                "total_queries": row["total_queries"] or 0,
                "successful_queries": row["successful"] or 0,
                "success_rate": (row["successful"] or 0) / (row["total_queries"] or 1),
                "avg_total_time_ms": round(row["avg_total_time_ms"] or 0, 2),
                "avg_llm_time_ms": round(row["avg_llm_time_ms"] or 0, 2),
                "avg_tool_time_ms": round(row["avg_tool_time_ms"] or 0, 2),
                "min_time_ms": row["min_time_ms"] or 0,
                "max_time_ms": row["max_time_ms"] or 0,
                "p50_time_ms": p50,
                "p95_time_ms": p95,
                "p99_time_ms": p99,
                "total_actions": row["total_actions"] or 0,
            }

    # =========================================================================
    # Action Metrics
    # =========================================================================

    def log_action_metric(self, metric: ActionMetric) -> int:
        """Log an action execution metric."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO action_metrics (
                    target, command_type, duration_ms, exit_code,
                    success, risk_level, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.target,
                metric.command_type,
                metric.duration_ms,
                metric.exit_code,
                1 if metric.success else 0,
                metric.risk_level,
                metric.created_at,
            ))
            return cursor.lastrowid or 0

    def get_action_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get action execution statistics."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_actions,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms
                FROM action_metrics
                WHERE created_at >= ?
            """, (cutoff,))

            row = cursor.fetchone()

            # By command type
            cursor.execute("""
                SELECT
                    command_type,
                    COUNT(*) as count,
                    AVG(duration_ms) as avg_duration_ms,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                FROM action_metrics
                WHERE created_at >= ?
                GROUP BY command_type
            """, (cutoff,))

            by_type = [dict(r) for r in cursor.fetchall()]

            # By risk level
            cursor.execute("""
                SELECT
                    risk_level,
                    COUNT(*) as count,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful
                FROM action_metrics
                WHERE created_at >= ?
                GROUP BY risk_level
            """, (cutoff,))

            by_risk = [dict(r) for r in cursor.fetchall()]

            return {
                "period_hours": hours,
                "total_actions": row["total_actions"] or 0,
                "successful_actions": row["successful"] or 0,
                "success_rate": (row["successful"] or 0) / (row["total_actions"] or 1),
                "avg_duration_ms": round(row["avg_duration_ms"] or 0, 2),
                "min_duration_ms": row["min_duration_ms"] or 0,
                "max_duration_ms": row["max_duration_ms"] or 0,
                "by_command_type": by_type,
                "by_risk_level": by_risk,
            }

    # =========================================================================
    # Embedding Metrics
    # =========================================================================

    def log_embedding_metric(self, metric: EmbeddingMetric) -> int:
        """Log an embedding generation metric."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO embedding_metrics (
                    model, input_tokens, dimensions, batch_size,
                    duration_ms, success, error, purpose, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.model,
                metric.input_tokens,
                metric.dimensions,
                metric.batch_size,
                metric.duration_ms,
                1 if metric.success else 0,
                metric.error,
                metric.purpose,
                metric.created_at,
            ))
            return cursor.lastrowid or 0

    def get_embedding_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get embedding generation statistics."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(input_tokens) as total_tokens,
                    SUM(batch_size) as total_embeddings,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms
                FROM embedding_metrics
                WHERE created_at >= ?
            """, (cutoff,))

            row = cursor.fetchone()

            # By model
            cursor.execute("""
                SELECT
                    model,
                    COUNT(*) as calls,
                    SUM(input_tokens) as tokens,
                    AVG(duration_ms) as avg_duration_ms
                FROM embedding_metrics
                WHERE created_at >= ?
                GROUP BY model
                ORDER BY calls DESC
            """, (cutoff,))

            by_model = [dict(r) for r in cursor.fetchall()]

            # By purpose
            cursor.execute("""
                SELECT
                    purpose,
                    COUNT(*) as calls,
                    AVG(duration_ms) as avg_duration_ms
                FROM embedding_metrics
                WHERE created_at >= ? AND purpose IS NOT NULL
                GROUP BY purpose
                ORDER BY calls DESC
            """, (cutoff,))

            by_purpose = [dict(r) for r in cursor.fetchall()]

            return {
                "period_hours": hours,
                "total_calls": row["total_calls"] or 0,
                "successful_calls": row["successful"] or 0,
                "success_rate": (row["successful"] or 0) / (row["total_calls"] or 1),
                "total_tokens": row["total_tokens"] or 0,
                "total_embeddings": row["total_embeddings"] or 0,
                "avg_duration_ms": round(row["avg_duration_ms"] or 0, 2),
                "min_duration_ms": row["min_duration_ms"] or 0,
                "max_duration_ms": row["max_duration_ms"] or 0,
                "by_model": by_model,
                "by_purpose": by_purpose,
            }

    # =========================================================================
    # Agent Task Metrics
    # =========================================================================

    def log_agent_task_metric(self, metric: AgentTaskMetric) -> int:
        """Log an agent task execution metric."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_task_metrics (
                    agent_name, task_type, duration_ms, success, error,
                    steps_count, tools_used, llm_calls, session_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                metric.agent_name,
                metric.task_type,
                metric.duration_ms,
                1 if metric.success else 0,
                metric.error,
                metric.steps_count,
                metric.tools_used,
                metric.llm_calls,
                metric.session_id,
                metric.created_at,
            ))
            return cursor.lastrowid or 0

    def get_agent_task_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get agent task execution statistics."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total_tasks,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(duration_ms) as avg_duration_ms,
                    MIN(duration_ms) as min_duration_ms,
                    MAX(duration_ms) as max_duration_ms,
                    SUM(steps_count) as total_steps,
                    SUM(llm_calls) as total_llm_calls
                FROM agent_task_metrics
                WHERE created_at >= ?
            """, (cutoff,))

            row = cursor.fetchone()

            # By agent
            cursor.execute("""
                SELECT
                    agent_name,
                    COUNT(*) as tasks,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(duration_ms) as avg_duration_ms,
                    SUM(llm_calls) as llm_calls
                FROM agent_task_metrics
                WHERE created_at >= ?
                GROUP BY agent_name
                ORDER BY tasks DESC
            """, (cutoff,))

            by_agent = [dict(r) for r in cursor.fetchall()]

            # By task type
            cursor.execute("""
                SELECT
                    task_type,
                    COUNT(*) as tasks,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(duration_ms) as avg_duration_ms
                FROM agent_task_metrics
                WHERE created_at >= ?
                GROUP BY task_type
                ORDER BY tasks DESC
            """, (cutoff,))

            by_task_type = [dict(r) for r in cursor.fetchall()]

            return {
                "period_hours": hours,
                "total_tasks": row["total_tasks"] or 0,
                "successful_tasks": row["successful"] or 0,
                "success_rate": (row["successful"] or 0) / (row["total_tasks"] or 1),
                "avg_duration_ms": round(row["avg_duration_ms"] or 0, 2),
                "min_duration_ms": row["min_duration_ms"] or 0,
                "max_duration_ms": row["max_duration_ms"] or 0,
                "total_steps": row["total_steps"] or 0,
                "total_llm_calls": row["total_llm_calls"] or 0,
                "by_agent": by_agent,
                "by_task_type": by_task_type,
            }

    # =========================================================================
    # Dashboard and Aggregation
    # =========================================================================

    def get_dashboard_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics."""
        return {
            "generated_at": datetime.now().isoformat(),
            "period_hours": hours,
            "llm": self.get_llm_stats(hours=hours),
            "queries": self.get_query_stats(hours=hours),
            "actions": self.get_action_stats(hours=hours),
            "embeddings": self.get_embedding_stats(hours=hours),
            "agent_tasks": self.get_agent_task_stats(hours=hours),
        }

    def get_session_stats(self, session_id: str) -> Dict[str, Any]:
        """Get statistics for a specific session."""
        with self._connection() as conn:
            cursor = conn.cursor()

            # Query metrics for session
            cursor.execute("""
                SELECT
                    COUNT(*) as total_queries,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    SUM(total_time_ms) as total_time_ms,
                    SUM(llm_time_ms) as total_llm_time_ms,
                    SUM(actions_count) as total_actions,
                    MIN(created_at) as first_query,
                    MAX(created_at) as last_query
                FROM query_metrics
                WHERE session_id = ?
            """, (session_id,))

            row = cursor.fetchone()

            return {
                "session_id": session_id,
                "total_queries": row["total_queries"] or 0,
                "successful_queries": row["successful"] or 0,
                "total_time_ms": row["total_time_ms"] or 0,
                "total_llm_time_ms": row["total_llm_time_ms"] or 0,
                "total_actions": row["total_actions"] or 0,
                "first_query": row["first_query"],
                "last_query": row["last_query"],
            }

    def calculate_baselines(self, metric_type: str, period: str = "daily") -> Optional[PerformanceBaseline]:
        """Calculate and store performance baselines."""
        now = datetime.now()

        if period == "hourly":
            period_start = now.replace(minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(hours=1)
        elif period == "daily":
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(days=1)
        elif period == "weekly":
            period_start = now - timedelta(days=now.weekday())
            period_start = period_start.replace(hour=0, minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(weeks=1)
        else:
            return None

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()

            # Get metrics for the period
            table = f"{metric_type}_metrics" if metric_type != "llm" else "llm_calls"
            duration_col = "response_time_ms" if metric_type == "llm" else "duration_ms"

            if metric_type == "query":
                duration_col = "total_time_ms"

            cursor.execute(f"""
                SELECT {duration_col} as duration, success
                FROM {table}
                WHERE created_at >= ? AND created_at < ?
            """, (period_start.isoformat(), period_end.isoformat()))

            rows = cursor.fetchall()
            if not rows:
                return None

            durations = [r["duration"] for r in rows if r["duration"] is not None]
            successes = sum(1 for r in rows if r["success"])

            if not durations:
                return None

            baseline = PerformanceBaseline(
                metric_type=metric_type,
                period=period,
                count=len(rows),
                avg_duration_ms=sum(durations) / len(durations),
                p50_duration_ms=self._percentile(durations, 50),
                p95_duration_ms=self._percentile(durations, 95),
                p99_duration_ms=self._percentile(durations, 99),
                success_rate=successes / len(rows),
                period_start=period_start.isoformat(),
                period_end=period_end.isoformat(),
            )

            # Store baseline
            cursor.execute("""
                INSERT OR REPLACE INTO performance_baselines (
                    metric_type, period, count, avg_duration_ms,
                    p50_duration_ms, p95_duration_ms, p99_duration_ms,
                    success_rate, period_start, period_end, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                baseline.metric_type,
                baseline.period,
                baseline.count,
                baseline.avg_duration_ms,
                baseline.p50_duration_ms,
                baseline.p95_duration_ms,
                baseline.p99_duration_ms,
                baseline.success_rate,
                baseline.period_start,
                baseline.period_end,
                now.isoformat(),
            ))

            return baseline

    def get_baselines(
        self,
        metric_type: Optional[str] = None,
        period: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get stored performance baselines."""
        with self._connection() as conn:
            cursor = conn.cursor()

            where_parts = []
            params: List[Any] = []

            if metric_type:
                where_parts.append("metric_type = ?")
                params.append(metric_type)
            if period:
                where_parts.append("period = ?")
                params.append(period)

            where_clause = " AND ".join(where_parts) if where_parts else "1=1"

            cursor.execute(f"""
                SELECT *
                FROM performance_baselines
                WHERE {where_clause}
                ORDER BY period_start DESC
                LIMIT ?
            """, params + [limit])

            return [dict(r) for r in cursor.fetchall()]

    # =========================================================================
    # Utility Methods
    # =========================================================================

    @staticmethod
    def _percentile(data: List[float], percentile: int) -> float:
        """Calculate percentile from sorted data."""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = (len(sorted_data) - 1) * percentile / 100
        lower = int(index)
        upper = lower + 1
        if upper >= len(sorted_data):
            return sorted_data[-1]
        weight = index - lower
        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight

    def cleanup_old_metrics(self, days: int = 30) -> int:
        """Remove metrics older than specified days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            total_deleted = 0

            tables = [
                "llm_calls",
                "query_metrics",
                "action_metrics",
                "embedding_metrics",
                "agent_task_metrics",
            ]
            for table in tables:
                cursor.execute(f"""
                    DELETE FROM {table}
                    WHERE created_at < ?
                """, (cutoff,))
                total_deleted += cursor.rowcount

            logger.info(f"🧹 Cleaned up {total_deleted} old metrics (older than {days} days)")
            return total_deleted

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with _metrics_lock:
            cls._instance = None
            cls._initialized = False


def get_metrics_repository(db_path: Optional[str] = None) -> MetricsRepository:
    """Get the metrics repository singleton."""
    return MetricsRepository(db_path)
