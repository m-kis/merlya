"""
Metric types for the metrics repository.

Dataclasses representing different types of application metrics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


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
