"""
Unit tests for metrics module.

Tests:
- Counter operations and thread safety
- Histogram with sliding window
- Gauge operations
- MetricsRegistry
- Metrics tracking functions
"""

from __future__ import annotations

import time
from threading import Thread

import pytest

from merlya.core.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    get_metrics_summary,
    get_registry,
    reset_metrics,
    timing,
    track_command,
    track_llm_call,
    track_pipeline_execution,
    track_ssh_duration,
)


def test_counter_increment() -> None:
    """Test counter increment operations."""
    counter = Counter(name="test_counter")

    assert counter.get() == 0

    counter.inc()
    assert counter.get() == 1

    counter.inc(amount=5)
    assert counter.get() == 6


def test_counter_with_labels() -> None:
    """Test counter with labels."""
    counter = Counter(name="test_counter")

    counter.inc(status="success")
    counter.inc(status="success")
    counter.inc(status="error")

    assert counter.get(status="success") == 2
    assert counter.get(status="error") == 1
    assert counter.value == 0  # Unlabeled value remains 0


def test_counter_reset() -> None:
    """Test counter reset."""
    counter = Counter(name="test_counter")

    counter.inc(amount=10)
    counter.inc(status="test")
    assert counter.get() == 10

    counter.reset()
    assert counter.get() == 0
    assert counter.get(status="test") == 0


def test_histogram_observe() -> None:
    """Test histogram observation recording."""
    histogram = Histogram(name="test_histogram")

    histogram.observe(0.5)
    histogram.observe(1.0)
    histogram.observe(2.0)

    stats = histogram.get_stats()
    assert stats["count"] == 3
    assert stats["sum"] == 3.5
    assert stats["min"] == 0.5
    assert stats["max"] == 2.0
    assert stats["avg"] == pytest.approx(1.1666, rel=0.01)


def test_histogram_buckets() -> None:
    """Test histogram bucket counting."""
    histogram = Histogram(name="test_histogram")

    # Add observations in different bucket ranges
    histogram.observe(0.05)  # Falls in 0.05 bucket
    histogram.observe(0.5)  # Falls in 0.5 bucket
    histogram.observe(1.5)  # Falls in 5.0 bucket
    histogram.observe(10.0)  # Falls in 10.0 bucket

    stats = histogram.get_stats()
    buckets = stats["buckets"]

    # Check cumulative bucket counts (le = less than or equal)
    assert buckets["0.05"] == 1
    assert buckets["0.5"] == 2
    assert buckets["5.0"] == 3
    assert buckets["10.0"] == 4


def test_histogram_sliding_window() -> None:
    """Test histogram sliding window prevents memory leak."""
    histogram = Histogram(name="test_histogram", max_observations=100)

    # Add 200 observations
    for i in range(200):
        histogram.observe(float(i))

    # Should only keep last 100
    assert len(histogram.observations) == 100
    assert histogram.observations[0] == 100.0  # First kept observation
    assert histogram.observations[-1] == 199.0  # Last observation


def test_histogram_reset() -> None:
    """Test histogram reset."""
    histogram = Histogram(name="test_histogram")

    histogram.observe(1.0)
    histogram.observe(2.0)
    assert len(histogram.observations) == 2

    histogram.reset()
    assert len(histogram.observations) == 0


def test_gauge_operations() -> None:
    """Test gauge set, inc, dec operations."""
    gauge = Gauge(name="test_gauge")

    assert gauge.get() == 0.0

    gauge.set(10.0)
    assert gauge.get() == 10.0

    gauge.inc(5.0)
    assert gauge.get() == 15.0

    gauge.dec(3.0)
    assert gauge.get() == 12.0


def test_gauge_reset() -> None:
    """Test gauge reset."""
    gauge = Gauge(name="test_gauge")

    gauge.set(42.0)
    assert gauge.get() == 42.0

    gauge.reset()
    assert gauge.get() == 0.0


def test_metrics_registry_counter() -> None:
    """Test MetricsRegistry counter creation and retrieval."""
    registry = MetricsRegistry()

    counter1 = registry.counter("test_counter")
    assert isinstance(counter1, Counter)
    assert counter1.name == "test_counter"

    # Should return same instance
    counter2 = registry.counter("test_counter")
    assert counter1 is counter2


def test_metrics_registry_histogram() -> None:
    """Test MetricsRegistry histogram creation and retrieval."""
    registry = MetricsRegistry()

    histogram1 = registry.histogram("test_histogram")
    assert isinstance(histogram1, Histogram)
    assert histogram1.name == "test_histogram"

    # Should return same instance
    histogram2 = registry.histogram("test_histogram")
    assert histogram1 is histogram2


def test_metrics_registry_gauge() -> None:
    """Test MetricsRegistry gauge creation and retrieval."""
    registry = MetricsRegistry()

    gauge1 = registry.gauge("test_gauge")
    assert isinstance(gauge1, Gauge)
    assert gauge1.name == "test_gauge"

    # Should return same instance
    gauge2 = registry.gauge("test_gauge")
    assert gauge1 is gauge2


def test_metrics_registry_get_all() -> None:
    """Test MetricsRegistry get_all returns all metrics."""
    registry = MetricsRegistry()

    counter = registry.counter("test_counter")
    histogram = registry.histogram("test_histogram")
    gauge = registry.gauge("test_gauge")

    counter.inc(5)
    histogram.observe(1.0)
    gauge.set(10.0)

    all_metrics = registry.get_all()

    assert "counters" in all_metrics
    assert "histograms" in all_metrics
    assert "gauges" in all_metrics

    assert all_metrics["counters"]["test_counter"]["value"] == 5
    assert all_metrics["histograms"]["test_histogram"]["count"] == 1
    assert all_metrics["gauges"]["test_gauge"] == 10.0


def test_metrics_registry_reset() -> None:
    """Test MetricsRegistry reset clears all metrics."""
    registry = MetricsRegistry()

    counter = registry.counter("test_counter")
    histogram = registry.histogram("test_histogram")
    gauge = registry.gauge("test_gauge")

    counter.inc(5)
    histogram.observe(1.0)
    gauge.set(10.0)

    registry.reset()

    # Values should be reset
    assert counter.get() == 0
    assert len(histogram.observations) == 0
    assert gauge.get() == 0.0


def test_global_registry() -> None:
    """Test global registry singleton."""
    registry1 = get_registry()
    registry2 = get_registry()

    assert registry1 is registry2


def test_track_command() -> None:
    """Test track_command function."""
    reset_metrics()  # Clear metrics first

    track_command("ssh", status="success")
    track_command("ssh", status="error")
    track_command("bash", status="success")

    registry = get_registry()
    all_metrics = registry.get_all()

    counters = all_metrics["counters"]
    assert "merlya_commands_total" in counters
    labels = counters["merlya_commands_total"]["labels"]

    # Check labeled counts
    assert "command_type=ssh,status=success" in labels
    assert labels["command_type=ssh,status=success"] == 1
    assert labels["command_type=ssh,status=error"] == 1
    assert labels["command_type=bash,status=success"] == 1


def test_track_ssh_duration() -> None:
    """Test track_ssh_duration function."""
    reset_metrics()

    track_ssh_duration(0.5, "web-01", status="success")
    track_ssh_duration(1.0, "web-01", status="success")
    track_ssh_duration(2.0, "db-01", status="error")

    registry = get_registry()
    all_metrics = registry.get_all()

    # Check histogram
    histograms = all_metrics["histograms"]
    assert "merlya_ssh_duration_seconds" in histograms
    assert histograms["merlya_ssh_duration_seconds"]["count"] == 3

    # Check counter
    counters = all_metrics["counters"]
    assert "merlya_ssh_operations_total" in counters


def test_track_llm_call() -> None:
    """Test track_llm_call function."""
    reset_metrics()

    track_llm_call("openai", "gpt-4", 1.5, 1000, status="success")
    track_llm_call("anthropic", "claude-3-opus", 2.0, 2000, status="success")

    registry = get_registry()
    all_metrics = registry.get_all()

    counters = all_metrics["counters"]
    assert "merlya_llm_calls_total" in counters

    histograms = all_metrics["histograms"]
    assert "merlya_llm_duration_seconds" in histograms
    assert histograms["merlya_llm_duration_seconds"]["count"] == 2


def test_track_pipeline_execution() -> None:
    """Test track_pipeline_execution function."""
    reset_metrics()

    track_pipeline_execution("ansible", 5.0, status="success")
    track_pipeline_execution("bash", 1.0, status="success")
    track_pipeline_execution("terraform", 10.0, status="error")

    registry = get_registry()
    all_metrics = registry.get_all()

    counters = all_metrics["counters"]
    assert "merlya_pipeline_executions" in counters

    histograms = all_metrics["histograms"]
    assert "merlya_pipeline_duration_seconds" in histograms
    assert histograms["merlya_pipeline_duration_seconds"]["count"] == 3


def test_timing_context_manager() -> None:
    """Test timing context manager."""
    reset_metrics()

    with timing("test_operation") as t:
        time.sleep(0.1)

    assert t.duration >= 0.1
    assert t.operation == "test_operation"


def test_timing_ssh_execute() -> None:
    """Test timing context manager auto-tracks SSH operations."""
    reset_metrics()

    with timing("ssh_execute", host="web-01", status="success"):
        time.sleep(0.05)

    registry = get_registry()
    all_metrics = registry.get_all()

    # Should auto-track SSH duration
    histograms = all_metrics["histograms"]
    assert "merlya_ssh_duration_seconds" in histograms
    assert histograms["merlya_ssh_duration_seconds"]["count"] == 1


def test_get_metrics_summary() -> None:
    """Test get_metrics_summary returns formatted string."""
    reset_metrics()

    track_command("ssh", status="success")
    track_ssh_duration(1.0, "web-01", status="success")

    summary = get_metrics_summary()

    assert "Metrics Summary" in summary
    assert "Commands:" in summary or "SSH Operations:" in summary
    assert isinstance(summary, str)


def test_counter_thread_safety() -> None:
    """Test counter thread safety under concurrent access."""
    counter = Counter(name="thread_test")

    def increment_counter() -> None:
        for _ in range(1000):
            counter.inc()

    threads = [Thread(target=increment_counter) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Should be exactly 10,000 (10 threads * 1000 increments each)
    assert counter.get() == 10000
