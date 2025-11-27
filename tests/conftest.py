"""
Pytest configuration and fixtures for Athena tests.
"""
import os
from unittest.mock import MagicMock

import pytest


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "manual: marks tests as manual (require API keys or infrastructure)")
    config.addinivalue_line("markers", "slow: marks tests as slow (>30 seconds)")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "smoke: marks tests as smoke tests (quick sanity checks)")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")


def pytest_collection_modifyitems(config, items):
    """
    Auto-skip manual tests if no API keys are present.
    Auto-mark *_manual.py files as manual.
    """
    for item in items:
        # Auto-mark files ending with _manual.py
        if "_manual" in str(item.fspath):
            item.add_marker(pytest.mark.manual)

        # Skip manual tests in CI (no API keys)
        if "manual" in [marker.name for marker in item.iter_markers()]:
            if not any([
                os.getenv("OPENROUTER_API_KEY"),
                os.getenv("ANTHROPIC_API_KEY"),
                os.getenv("OLLAMA_HOST"),
            ]):
                item.add_marker(pytest.mark.skip(reason="Manual test requires API keys"))


@pytest.fixture
def mock_ssh_manager(mocker):
    """Mock SSH manager for unit tests."""
    mock = mocker.patch("athena_ai.executors.ssh.SSHManager")
    mock.return_value.execute.return_value = (0, "success", "")
    return mock


@pytest.fixture
def mock_context():
    """Provide a mock infrastructure context."""
    return {
        "local": {
            "hostname": "test-host",
            "os": "Linux",
            "services": ["nginx", "mongodb"],
        },
        "inventory": {
            "web-prod-1": "192.0.2.10",
            "db-prod-1": "192.0.2.20",
            "mongo-preprod-1": "198.51.100.10",
        },
        "remote_hosts": {},
    }


@pytest.fixture
def sample_request():
    """Provide sample user requests for testing."""
    return {
        "simple": "check disk space on web-prod-1",
        "complex": "investigate why mongodb is slow on mongo-preprod-1",
        "dangerous": "rm -rf / on all servers",
        "french": "vérifie l'espace disque sur web-prod-1",
    }


@pytest.fixture
def mock_console():
    """Provide a mock Rich console."""
    console = MagicMock()
    console.status.return_value = MagicMock()
    return console


@pytest.fixture
def temp_athena_dir(tmp_path):
    """Create temporary ~/.athena directory."""
    athena_dir = tmp_path / ".athena"
    athena_dir.mkdir()
    return athena_dir


@pytest.fixture
def mock_tool_context(mock_console):
    """Provide a mock ToolContext."""
    from athena_ai.tools.base import ToolContext

    return ToolContext(
        executor=MagicMock(),
        context_manager=MagicMock(),
        permissions=MagicMock(),
        console=mock_console,
    )


@pytest.fixture
def sample_triage_queries():
    """Sample queries for triage testing."""
    return {
        "p0_down": "production is down!",
        "p0_breach": "we've been hacked, unauthorized access detected",
        "p1_slow": "service is degraded and slow",
        "p1_vuln": "CVE-2024-1234 vulnerability found",
        "p2_perf": "need to optimize slow queries",
        "p3_check": "check disk space on web-01",
        "query_list": "what servers are available?",
        "action_restart": "restart nginx on web-01",
        "analysis_why": "why is mongodb slow on prod?",
    }


@pytest.fixture
def mock_llm_router():
    """Provide a mock LLM router."""
    router = MagicMock()
    router.generate.return_value = '{"intent": "action", "priority": "P3", "reasoning": "test"}'
    return router
