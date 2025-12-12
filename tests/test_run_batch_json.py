"""JSON serialization tests for batch run outputs."""

from __future__ import annotations

import json
from pathlib import Path

from merlya.cli.run import BatchResult, TaskResult, _to_json_safe
from merlya.core.types import CheckStatus, HealthCheck
from merlya.health.checks import StartupHealth
from merlya.persistence.models import Host


def test_task_result_serializes_pydantic_models_for_json_output():
    """Ensure Pydantic models in task data are converted to JSON-friendly dicts."""
    host = Host(name="web-01", hostname="web.example.com", port=2201, tags=["prod"])
    task = TaskResult(
        task="/hosts list",
        success=True,
        message="",
        actions=["command_execute"],
        data=[host],
        task_type="command",
    )

    serialized = task.to_dict()

    assert serialized["data"][0]["name"] == "web-01"
    assert serialized["data"][0]["hostname"] == "web.example.com"
    assert isinstance(serialized["data"][0]["created_at"], str)
    json.dumps(serialized)


def test_batch_result_serializes_nested_dataclasses_and_enums():
    """Ensure dataclasses with enums are serializable in batch JSON output."""
    health_check = HealthCheck(name="disk", status=CheckStatus.OK, message="ok")
    startup_health = StartupHealth(
        checks=[health_check],
        capabilities={"ssh": True},
        model_tier="balanced",
    )
    task = TaskResult(
        task="/health",
        success=True,
        message="ok",
        actions=["command_execute"],
        data=startup_health,
        task_type="command",
    )
    batch = BatchResult(success=True, tasks=[task], total=1, passed=1, failed=0)

    payload = batch.to_dict()

    assert payload["tasks"][0]["data"]["checks"][0]["status"] == "ok"
    assert payload["tasks"][0]["data"]["capabilities"]["ssh"] is True
    json.dumps(payload)


def test_json_safe_handles_datetime_and_paths():
    """Validate helper converts common non-serializable types."""
    path = Path("/tmp/example")
    data = {"path": path}

    serialized = _to_json_safe(data)

    assert serialized["path"] == "/tmp/example"
    json.dumps(serialized)
