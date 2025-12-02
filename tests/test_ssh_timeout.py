"""
Tests for SSH channel timeout protection.

Tests the read_channel_with_timeout function that prevents blocking
on Broken Pipe errors in Paramiko.
"""
from unittest.mock import MagicMock, patch

from merlya.executors.ssh_utils import read_channel_with_timeout


class MockChannel:
    """Mock Paramiko channel for testing."""

    def __init__(
        self,
        stdout_data: bytes = b"",
        stderr_data: bytes = b"",
        exit_status: int = 0,
        delay_ready: int = 0,
        simulate_broken_pipe: bool = False,
    ):
        self.stdout_data = stdout_data
        self.stderr_data = stderr_data
        self._exit_status = exit_status
        self._delay_ready = delay_ready
        self._simulate_broken_pipe = simulate_broken_pipe
        self._stdout_read = False
        self._stderr_read = False
        self._blocking = True
        self._closed = False
        self._fileno_value = 999
        self._timeout = None

    def setblocking(self, blocking: bool):
        self._blocking = blocking

    def settimeout(self, timeout: float):
        self._timeout = timeout

    def fileno(self) -> int:
        return self._fileno_value

    def exit_status_ready(self) -> bool:
        if self._delay_ready > 0:
            self._delay_ready -= 1
            return False
        return True

    def recv_ready(self) -> bool:
        return len(self.stdout_data) > 0 and not self._stdout_read

    def recv_stderr_ready(self) -> bool:
        return len(self.stderr_data) > 0 and not self._stderr_read

    def recv(self, max_bytes: int) -> bytes:
        if self._simulate_broken_pipe:
            raise BrokenPipeError("Connection closed")
        self._stdout_read = True
        data = self.stdout_data[:max_bytes]
        self.stdout_data = self.stdout_data[max_bytes:]
        return data

    def recv_stderr(self, max_bytes: int) -> bytes:
        self._stderr_read = True
        data = self.stderr_data[:max_bytes]
        self.stderr_data = self.stderr_data[max_bytes:]
        return data

    def recv_exit_status(self) -> int:
        return self._exit_status

    def exec_command(self, command: str):
        pass

    def close(self):
        self._closed = True


class TestReadChannelWithTimeout:
    """Test read_channel_with_timeout function."""

    def test_basic_stdout_read(self):
        """Test reading stdout from channel."""
        channel = MockChannel(stdout_data=b"Hello World", exit_status=0)

        with patch("merlya.executors.ssh_utils.select.select", return_value=([channel], [], [])):
            stdout, stderr, exit_code = read_channel_with_timeout(channel, timeout=5.0)

        assert stdout == "Hello World"
        assert stderr == ""
        assert exit_code == 0
        assert channel._closed

    def test_stdout_with_exit_code(self):
        """Test reading stdout with non-zero exit code."""
        channel = MockChannel(
            stdout_data=b"output",
            exit_status=1,
        )

        with patch("merlya.executors.ssh_utils.select.select", return_value=([channel], [], [])):
            stdout, stderr, exit_code = read_channel_with_timeout(channel, timeout=5.0)

        assert stdout == "output"
        assert exit_code == 1

    def test_timeout_returns_empty(self):
        """Test that function returns empty on timeout."""
        channel = MockChannel(delay_ready=100)  # Never ready

        # Mock select to return empty (timeout) - simulates timeout
        with patch("merlya.executors.ssh_utils.select.select", return_value=([], [], [])):
            stdout, stderr, exit_code = read_channel_with_timeout(channel, timeout=0.1)

        assert stdout == ""
        assert stderr == ""
        # Exit status may or may not be available depending on timing
        assert channel._closed

    def test_broken_pipe_handled_gracefully(self):
        """Test that Broken Pipe errors don't cause blocking."""
        channel = MockChannel(simulate_broken_pipe=True, stdout_data=b"data")

        with patch("merlya.executors.ssh_utils.select.select", return_value=([channel], [], [])):
            stdout, stderr, exit_code = read_channel_with_timeout(channel, timeout=5.0)

        # Should return empty but not hang
        assert stdout == ""
        assert channel._closed

    def test_channel_always_closed(self):
        """Test that channel is always closed even on error."""
        channel = MockChannel()

        def raise_error(*args, **kwargs):
            raise RuntimeError("Test error")

        with patch("merlya.executors.ssh_utils.select.select", side_effect=raise_error):
            stdout, stderr, exit_code = read_channel_with_timeout(channel, timeout=1.0)

        assert channel._closed

    def test_utf8_decoding_with_errors(self):
        """Test handling of invalid UTF-8 bytes."""
        # Invalid UTF-8 sequence
        channel = MockChannel(stdout_data=b"Hello \xff\xfe World", exit_status=0)

        with patch("merlya.executors.ssh_utils.select.select", return_value=([channel], [], [])):
            stdout, stderr, exit_code = read_channel_with_timeout(channel, timeout=5.0)

        # Should replace invalid bytes, not crash
        assert "Hello" in stdout
        assert "World" in stdout


class TestExecCommandWithTimeout:
    """Test exec_command_with_timeout from ssh_utils."""

    def test_exec_command_with_timeout_import(self):
        """Test that exec_command_with_timeout can be imported."""
        from merlya.executors.ssh_utils import exec_command_with_timeout

        assert callable(exec_command_with_timeout)

    def test_exec_command_with_timeout_mock_client(self):
        """Test exec_command_with_timeout with a mock client."""
        from merlya.executors.ssh_utils import exec_command_with_timeout

        # Use the MockChannel class that has all required methods
        mock_channel = MockChannel(stdout_data=b"test output", exit_status=0)

        mock_transport = MagicMock()
        mock_transport.is_active.return_value = True
        mock_transport.open_session.return_value = mock_channel

        mock_client = MagicMock()
        mock_client.get_transport.return_value = mock_transport

        with patch("merlya.executors.ssh_utils.select.select", return_value=([mock_channel], [], [])):
            result = exec_command_with_timeout(mock_client, "echo test", timeout=5.0)

        assert result == "test output"

    def test_exec_command_with_timeout_inactive_transport(self):
        """Test exec_command_with_timeout with inactive transport returns empty."""
        from merlya.executors.ssh_utils import exec_command_with_timeout

        mock_transport = MagicMock()
        mock_transport.is_active.return_value = False

        mock_client = MagicMock()
        mock_client.get_transport.return_value = mock_transport

        result = exec_command_with_timeout(mock_client, "echo test", timeout=5.0)

        assert result == ""

    def test_exec_command_with_timeout_no_transport(self):
        """Test exec_command_with_timeout with no transport returns empty."""
        from merlya.executors.ssh_utils import exec_command_with_timeout

        mock_client = MagicMock()
        mock_client.get_transport.return_value = None

        result = exec_command_with_timeout(mock_client, "echo test", timeout=5.0)

        assert result == ""

    def test_alias_in_ssh_scanner(self):
        """Test that ssh_scanner has the alias for backward compatibility."""
        from merlya.context.on_demand_scanner.ssh_scanner import _exec_command_safe
        from merlya.executors.ssh_utils import exec_command_with_timeout

        assert _exec_command_safe is exec_command_with_timeout
