"""
End-to-end tests for Merlya CLI commands.

These tests run actual CLI commands via `merlya run -y` to validate
real-world use cases. They require:
- A working Merlya installation
- Configured API keys (for LLM tests)
- Optional: SSH access to test hosts

Run with: pytest tests/test_e2e_commands.py -v --e2e
Skip with: pytest tests/test_e2e_commands.py -v (skips by default)
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest

# Mark all tests in this module as e2e (skipped by default)
pytestmark = pytest.mark.e2e


def run_merlya(command: str, timeout: int = 30) -> tuple[int, str, str]:
    """
    Run a merlya command and return (exit_code, stdout, stderr).

    Args:
        command: The slash command to run (e.g., "/help")
        timeout: Timeout in seconds

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    result = subprocess.run(
        ["merlya", "run", "-y", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "NO_COLOR": "1"},  # Disable colors for easier parsing
    )
    return result.returncode, result.stdout, result.stderr


class TestHelpCommands:
    """E2E tests for help commands."""

    def test_help_shows_all_commands(self):
        """Test /help lists all available commands."""
        code, stdout, _ = run_merlya("/help")
        assert code == 0
        # Check for key commands
        assert "/hosts" in stdout
        assert "/model" in stdout
        assert "/ssh" in stdout
        assert "/scan" in stdout
        assert "/health" in stdout

    def test_help_model_shows_subcommands(self):
        """Test /help model shows brain/fast subcommands."""
        code, stdout, _ = run_merlya("/help model")
        assert code == 0
        assert "brain" in stdout
        assert "fast" in stdout
        assert "provider" in stdout
        assert "test" in stdout

    def test_help_hosts_shows_subcommands(self):
        """Test /help hosts shows all subcommands."""
        code, stdout, _ = run_merlya("/help hosts")
        assert code == 0
        assert "list" in stdout
        assert "add" in stdout
        assert "delete" in stdout
        assert "export" in stdout


class TestLanguageCommands:
    """E2E tests for language switching."""

    def test_language_switch_to_french(self):
        """Test /language fr switches to French."""
        code, stdout, _ = run_merlya("/language fr")
        assert code == 0
        assert "fr" in stdout.lower()

    def test_language_switch_to_english(self):
        """Test /language en switches to English."""
        code, stdout, _ = run_merlya("/language en")
        assert code == 0
        assert "en" in stdout.lower()


class TestModelCommands:
    """E2E tests for model configuration commands."""

    def test_model_show_displays_brain_fast(self):
        """Test /model show displays brain and fast models."""
        code, stdout, _ = run_merlya("/model show")
        assert code == 0
        assert "brain" in stdout.lower()
        assert "fast" in stdout.lower()
        assert "Provider" in stdout

    def test_model_brain_no_args_shows_current(self):
        """Test /model brain without args shows current brain model."""
        code, stdout, _ = run_merlya("/model brain")
        assert code == 0
        assert "Brain Model" in stdout
        assert "Current" in stdout

    def test_model_fast_no_args_shows_current(self):
        """Test /model fast without args shows current fast model."""
        code, stdout, _ = run_merlya("/model fast")
        assert code == 0
        assert "Fast Model" in stdout
        assert "Current" in stdout

    def test_model_provider_no_args_shows_usage(self):
        """Test /model provider without args shows available providers."""
        _code, stdout, _ = run_merlya("/model provider")
        # Exit code 1 because no provider specified
        assert "Usage" in stdout or "Available" in stdout
        assert "anthropic" in stdout.lower() or "openrouter" in stdout.lower()


class TestHostsCommands:
    """E2E tests for hosts management commands."""

    def test_hosts_list(self):
        """Test /hosts list shows hosts table."""
        code, stdout, _ = run_merlya("/hosts list")
        assert code == 0
        assert "Hosts" in stdout or "hosts" in stdout.lower()

    def test_hosts_export_json(self):
        """Test /hosts export creates valid JSON."""
        # Use /tmp explicitly - security validation requires paths in /tmp, ~, or /etc
        unique_id = uuid.uuid4().hex[:8]
        export_path = f"/tmp/merlya_test_export_{unique_id}.json"

        try:
            code, _stdout, _ = run_merlya(f"/hosts export {export_path}")
            assert code == 0

            # Verify JSON is valid
            with Path(export_path).open() as f:
                data = json.load(f)
            assert isinstance(data, list)
        finally:
            Path(export_path).unlink(missing_ok=True)


class TestVariableCommands:
    """E2E tests for variable management commands."""

    def test_variable_list(self):
        """Test /variable list shows variables."""
        code, _stdout, _ = run_merlya("/variable list")
        assert code == 0

    def test_variable_set_get_delete_cycle(self):
        """Test full variable lifecycle: set, get, delete."""
        var_name = "TEST_E2E_VAR"
        var_value = "test_value_123"

        # Set
        code, stdout, _ = run_merlya(f"/variable set {var_name} {var_value}")
        assert code == 0

        # Get
        code, stdout, _ = run_merlya(f"/variable get {var_name}")
        assert code == 0
        assert var_value in stdout

        # Delete
        code, stdout, _ = run_merlya(f"/variable delete {var_name}")
        assert code == 0


class TestSecretCommands:
    """E2E tests for secret management commands."""

    def test_secret_list(self):
        """Test /secret list shows secret names."""
        code, _stdout, _ = run_merlya("/secret list")
        assert code == 0


class TestHealthCommand:
    """E2E tests for health check command."""

    def test_health_shows_status(self):
        """Test /health shows system health status."""
        code, stdout, _ = run_merlya("/health")
        assert code == 0
        assert "Health" in stdout or "RAM" in stdout or "Disk" in stdout


class TestAuditCommands:
    """E2E tests for audit commands."""

    def test_audit_recent(self):
        """Test /audit recent shows audit events or empty message."""
        code, stdout, _ = run_merlya("/audit recent")
        assert code == 0
        # Either shows events or "No audit events"
        assert "audit" in stdout.lower() or "No" in stdout

    def test_audit_stats(self):
        """Test /audit stats shows statistics."""
        code, _stdout, _ = run_merlya("/audit stats")
        assert code == 0


class TestMCPCommands:
    """E2E tests for MCP commands."""

    def test_mcp_list(self):
        """Test /mcp list shows configured servers or empty message."""
        code, _stdout, _ = run_merlya("/mcp list")
        assert code == 0


@pytest.mark.ssh
class TestSSHCommands:
    """
    E2E tests for SSH commands.

    These tests require a configured SSH host. Set TEST_SSH_HOST env var.
    Run with: pytest tests/test_e2e_commands.py -v --e2e -m ssh
    """

    @pytest.fixture
    def ssh_host(self):
        """Get SSH test host from environment."""
        host = os.environ.get("TEST_SSH_HOST")
        if not host:
            pytest.skip("TEST_SSH_HOST not set")
        return host

    def test_ssh_test_connection(self, ssh_host: str):
        """Test /ssh test validates SSH connection."""
        code, stdout, _ = run_merlya(f"/ssh test {ssh_host}", timeout=60)
        assert code == 0
        assert "Success" in stdout or "OK" in stdout

    def test_ssh_exec_uptime(self, ssh_host: str):
        """Test /ssh exec runs command on remote host."""
        code, stdout, _ = run_merlya(f"/ssh exec {ssh_host} uptime", timeout=60)
        assert code == 0
        assert "up" in stdout.lower() or "load" in stdout.lower()

    def test_ssh_connect_disconnect_cycle(self, ssh_host: str):
        """Test SSH connect/disconnect cycle."""
        # Connect
        code, stdout, _ = run_merlya(f"/ssh connect {ssh_host}", timeout=60)
        assert code == 0
        assert "Connected" in stdout or "connected" in stdout.lower()

        # Disconnect
        code, stdout, _ = run_merlya(f"/ssh disconnect {ssh_host}")
        assert code == 0
        assert "Disconnected" in stdout or "disconnected" in stdout.lower()


@pytest.mark.ssh
class TestScanCommand:
    """
    E2E tests for scan command.

    Requires SSH access to test host. Set TEST_SSH_HOST env var.
    """

    @pytest.fixture
    def ssh_host(self):
        """Get SSH test host from environment."""
        host = os.environ.get("TEST_SSH_HOST")
        if not host:
            pytest.skip("TEST_SSH_HOST not set")
        return host

    def test_scan_system(self, ssh_host: str):
        """Test /scan --system collects system info."""
        code, stdout, _ = run_merlya(f"/scan {ssh_host} --system", timeout=120)
        assert code == 0
        # Should contain system info
        assert any(term in stdout.lower() for term in ["memory", "cpu", "disk", "kernel", "os"])


class TestHostsImportExport:
    """E2E tests for hosts import/export with elevation."""

    def test_export_import_roundtrip_json(self):
        """Test hosts export/import roundtrip with JSON format."""
        # Use /tmp explicitly - security validation requires paths in /tmp, ~, or /etc
        unique_id = uuid.uuid4().hex[:8]
        export_path = f"/tmp/merlya_test_export_{unique_id}.json"
        import_path = f"/tmp/merlya_test_import_{unique_id}.json"

        try:
            # Export
            code, _, _ = run_merlya(f"/hosts export {export_path}")
            assert code == 0

            # Read and verify structure
            with Path(export_path).open() as f:
                data = json.load(f)
            assert isinstance(data, list)

            # Create test import file with elevation
            test_hosts = [
                {
                    "name": "test-e2e-host",
                    "hostname": "192.168.99.99",
                    "user": "testuser",
                    "port": 22,
                    "tags": ["test", "e2e"],
                    "elevation_method": "sudo",
                }
            ]
            with Path(import_path).open("w") as f:
                json.dump(test_hosts, f)

            # Import
            code, stdout, _ = run_merlya(f"/hosts import {import_path}")
            assert code == 0, f"Import failed: {stdout}"
            assert "test-e2e-host" in stdout or "imported" in stdout.lower()

            # Verify host exists
            code, stdout, _ = run_merlya("/hosts show test-e2e-host")
            assert code == 0
            assert "192.168.99.99" in stdout

            # Cleanup
            code, _, _ = run_merlya("/hosts delete test-e2e-host")
            assert code == 0

        finally:
            Path(export_path).unlink(missing_ok=True)
            Path(import_path).unlink(missing_ok=True)


class TestConsistencyChecks:
    """E2E tests for command consistency."""

    def test_all_commands_have_help(self):
        """Test that all main commands have help available."""
        commands = [
            "hosts",
            "ssh",
            "model",
            "variable",
            "secret",
            "health",
            "audit",
            "mcp",
            "scan",
            "log",
        ]
        for cmd in commands:
            code, stdout, _ = run_merlya(f"/help {cmd}")
            assert code == 0, f"/help {cmd} failed"
            assert "Usage" in stdout or "usage" in stdout.lower(), f"/help {cmd} missing usage"

    def test_commands_without_args_dont_crash(self):
        """Test that commands without required args show usage, not crash."""
        commands = [
            "/hosts",
            "/model",
            "/variable",
            "/secret",
            "/audit",
            "/mcp",
        ]
        for cmd in commands:
            _code, _stdout, stderr = run_merlya(cmd)
            # Should either succeed (show current state) or fail gracefully with usage
            assert "error" not in stderr.lower() or "traceback" not in stderr.lower(), (
                f"{cmd} crashed: {stderr}"
            )
