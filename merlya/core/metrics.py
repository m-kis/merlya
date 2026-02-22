"""
Merlya Core - Metrics collection.

In-memory metrics for monitoring core operations.
NO external backends in MVP (Prometheus/Grafana deferred to V2.0).

Metrics:
- merlya_commands_total: Total commands executed
- merlya_ssh_duration_seconds: SSH operation duration
- merlya_llm_calls_total: LLM API calls
- merlya_pipeline_executions: Pipeline executions
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from loguru import logger


@dataclass
class Counter:
    """Simple counter metric."""

    name: str
    value: int = 0
    labels: dict[str, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def inc(self, amount: int = 1, **labels: str) -> None:
        """
        Increment counter.

        Args:
            amount: Amount to increment (default: 1)
            **labels: Optional labels (e.g., status="success", host="web-01")
        """
        with self._lock:
            if labels:
                label_key = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
                self.labels[label_key] = self.labels.get(label_key, 0) + amount
            else:
                self.value += amount

    def get(self, **labels: str) -> int:
        """
        Get counter value.

        Args:
            **labels: Optional labels to filter by

        Returns:
            Counter value
        """
        with self._lock:
            if labels:
                label_key = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
                return self.labels.get(label_key, 0)
            return self.value

    def reset(self) -> None:
        """Reset counter to zero."""
        with self._lock:
            self.value = 0
            self.labels.clear()


@dataclass
class Histogram:
    """Simple histogram metric for duration tracking with sliding window."""

    name: str
    buckets: list[float] = field(
        default_factory=lambda: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0]
    )
    observations: list[float] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock, repr=False)
    max_observations: int = 10000  # Prevent memory leak with sliding window

    def observe(self, value: float, **_labels: str) -> None:
        """
        Record an observation.

        Uses sliding window to limit memory (keeps last max_observations).

        Args:
            value: Value to observe (e.g., duration in seconds)
            **_labels: Optional labels (currently not used in MVP, reserved for V2.0)
        """
        with self._lock:
            self.observations.append(value)
            # Sliding window: keep only last N observations to prevent memory leak
            if len(self.observations) > self.max_observations:
                self.observations = self.observations[-self.max_observations :]

    def get_stats(self) -> dict[str, Any]:
        """
        Get histogram statistics.

        Returns:
            Dict with count, sum, min, max, avg, and bucket counts
        """
        with self._lock:
            if not self.observations:
                return {
                    "count": 0,
                    "sum": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "avg": 0.0,
                    "buckets": {str(b): 0 for b in self.buckets},
                }

            # Calculate basic stats
            count = len(self.observations)
            total = sum(self.observations)
            min_val = min(self.observations)
            max_val = max(self.observations)
            avg_val = total / count

            # Calculate bucket counts (le = less than or equal)
            bucket_counts = {}
            for bucket in self.buckets:
                bucket_counts[str(bucket)] = sum(1 for v in self.observations if v <= bucket)

            return {
                "count": count,
                "sum": total,
                "min": min_val,
                "max": max_val,
                "avg": avg_val,
                "buckets": bucket_counts,
            }

    def reset(self) -> None:
        """Reset histogram observations."""
        with self._lock:
            self.observations.clear()


@dataclass
class Gauge:
    """Simple gauge metric for current values."""

    name: str
    value: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def set(self, value: float) -> None:
        """
        Set gauge value.

        Args:
            value: New value
        """
        with self._lock:
            self.value = value

    def inc(self, amount: float = 1.0) -> None:
        """
        Increment gauge.

        Args:
            amount: Amount to increment
        """
        with self._lock:
            self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        """
        Decrement gauge.

        Args:
            amount: Amount to decrement
        """
        with self._lock:
            self.value -= amount

    def get(self) -> float:
        """Get current gauge value."""
        with self._lock:
            return self.value

    def reset(self) -> None:
        """Reset gauge to zero."""
        with self._lock:
            self.value = 0.0


class MetricsRegistry:
    """
    Registry for all metrics.

    Thread-safe in-memory metrics storage.
    """

    def __init__(self) -> None:
        """Initialize metrics registry."""
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, Gauge] = {}
        self._lock = Lock()

    def counter(self, name: str) -> Counter:
        """
        Get or create a counter metric.

        Args:
            name: Counter name

        Returns:
            Counter instance
        """
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name=name)
            return self._counters[name]

    def histogram(self, name: str, buckets: list[float] | None = None) -> Histogram:
        """
        Get or create a histogram metric.

        Args:
            name: Histogram name
            buckets: Optional custom buckets (default: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0])

        Returns:
            Histogram instance
        """
        with self._lock:
            if name not in self._histograms:
                if buckets:
                    self._histograms[name] = Histogram(name=name, buckets=buckets)
                else:
                    self._histograms[name] = Histogram(name=name)
            return self._histograms[name]

    def gauge(self, name: str) -> Gauge:
        """
        Get or create a gauge metric.

        Args:
            name: Gauge name

        Returns:
            Gauge instance
        """
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name=name)
            return self._gauges[name]

    def get_all(self) -> dict[str, Any]:
        """
        Get all metrics data.

        Returns:
            Dict with all counters, histograms, and gauges
        """
        with self._lock:
            return {
                "counters": {
                    name: {"value": c.value, "labels": c.labels}
                    for name, c in self._counters.items()
                },
                "histograms": {name: h.get_stats() for name, h in self._histograms.items()},
                "gauges": {name: g.value for name, g in self._gauges.items()},
            }

    def reset(self) -> None:
        """Reset all metrics."""
        with self._lock:
            for counter in self._counters.values():
                counter.reset()
            for histogram in self._histograms.values():
                histogram.reset()
            for gauge in self._gauges.values():
                gauge.reset()


# Global metrics registry
_registry = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    """
    Get global metrics registry.

    Returns:
        MetricsRegistry instance
    """
    return _registry


def reset_metrics() -> None:
    """Reset all metrics in global registry."""
    _registry.reset()


# ============================================================================
# Core Metrics (Architecture NFR)
# ============================================================================


def track_command(command_type: str, status: str = "success") -> None:
    """
    Track a command execution.

    Args:
        command_type: Type of command (e.g., "ssh", "bash", "scan")
        status: Status (e.g., "success", "error", "cancelled")
    """
    _registry.counter("merlya_commands_total").inc(command_type=command_type, status=status)


def track_ssh_duration(duration: float, host: str, status: str = "success") -> None:
    """
    Track SSH operation duration.

    Args:
        duration: Duration in seconds
        host: Target host
        status: Status (e.g., "success", "error", "timeout")
    """
    _registry.histogram("merlya_ssh_duration_seconds").observe(duration)
    _registry.counter("merlya_ssh_operations_total").inc(host=host, status=status)


def track_llm_call(
    provider: str, model: str, duration: float, _tokens: int, status: str = "success"
) -> None:
    """
    Track LLM API call.

    Args:
        provider: LLM provider (e.g., "openai", "anthropic")
        model: Model name (e.g., "gpt-4", "claude-3-opus")
        duration: Duration in seconds
        _tokens: Total tokens used (reserved for V2.0 detailed tracking)
        status: Status (e.g., "success", "error", "timeout")
    """
    _registry.counter("merlya_llm_calls_total").inc(provider=provider, model=model, status=status)
    _registry.histogram("merlya_llm_duration_seconds").observe(duration)
    _registry.counter("merlya_llm_tokens_total").inc(provider=provider, model=model)


def track_pipeline_execution(pipeline_type: str, duration: float, status: str = "success") -> None:
    """
    Track pipeline execution.

    Args:
        pipeline_type: Pipeline type (e.g., "bash", "ansible", "terraform")
        duration: Duration in seconds
        status: Status (e.g., "success", "error", "rollback")
    """
    _registry.counter("merlya_pipeline_executions").inc(pipeline_type=pipeline_type, status=status)
    _registry.histogram("merlya_pipeline_duration_seconds").observe(duration)


# ============================================================================
# Timing Context Manager
# ============================================================================


class timing:
    """
    Context manager for timing operations.

    Example:
        with timing("ssh_execute", host="web-01") as t:
            await ssh_pool.execute(host, command)
        logger.debug(f"SSH took {t.duration:.2f}s")
    """

    def __init__(self, operation: str, **labels: str) -> None:
        """
        Initialize timing context.

        Args:
            operation: Operation name
            **labels: Optional labels
        """
        self.operation = operation
        self.labels = labels
        self.start_time: float = 0.0
        self.duration: float = 0.0

    def __enter__(self) -> timing:
        """Start timing."""
        self.start_time = time.time()
        return self

    def __exit__(self, *args: Any) -> None:
        """Stop timing and record metric."""
        self.duration = time.time() - self.start_time

        # Auto-track common operations
        if self.operation == "ssh_execute":
            host = self.labels.get("host", "unknown")
            status = self.labels.get("status", "success")
            track_ssh_duration(self.duration, host, status)
        elif self.operation == "pipeline_execute":
            pipeline_type = self.labels.get("pipeline_type", "unknown")
            status = self.labels.get("status", "success")
            track_pipeline_execution(pipeline_type, self.duration, status)
        elif self.operation == "llm_call":
            provider = self.labels.get("provider", "unknown")
            model = self.labels.get("model", "unknown")
            tokens = int(self.labels.get("tokens", 0))
            status = self.labels.get("status", "success")
            track_llm_call(provider, model, self.duration, tokens, status)
        else:
            # Generic duration tracking
            logger.debug(f"⏱️ {self.operation} took {self.duration:.2f}s")


def get_metrics_summary() -> str:
    """
    Get human-readable metrics summary.

    Returns:
        Formatted metrics summary
    """
    data = _registry.get_all()

    lines = ["📊 **Metrics Summary**", ""]

    # Commands
    if "merlya_commands_total" in data["counters"]:
        cmd_data = data["counters"]["merlya_commands_total"]
        lines.append(f"**Commands:** {cmd_data['value']} total")
        if cmd_data["labels"]:
            for label, count in sorted(cmd_data["labels"].items()):
                lines.append(f"  - {label}: {count}")
        lines.append("")

    # SSH operations
    if "merlya_ssh_duration_seconds" in data["histograms"]:
        ssh_stats = data["histograms"]["merlya_ssh_duration_seconds"]
        if ssh_stats["count"] > 0:
            lines.append(
                f"**SSH Operations:** {ssh_stats['count']} total, "
                f"avg={ssh_stats['avg']:.2f}s, max={ssh_stats['max']:.2f}s"
            )
            lines.append("")

    # LLM calls
    if "merlya_llm_calls_total" in data["counters"]:
        llm_data = data["counters"]["merlya_llm_calls_total"]
        lines.append(f"**LLM Calls:** {llm_data['value']} total")
        if llm_data["labels"]:
            for label, count in sorted(llm_data["labels"].items()):
                lines.append(f"  - {label}: {count}")
        lines.append("")

    # Pipeline executions
    if "merlya_pipeline_executions" in data["counters"]:
        pipe_data = data["counters"]["merlya_pipeline_executions"]
        lines.append(f"**Pipeline Executions:** {pipe_data['value']} total")
        if pipe_data["labels"]:
            for label, count in sorted(pipe_data["labels"].items()):
                lines.append(f"  - {label}: {count}")

    return "\n".join(lines)
