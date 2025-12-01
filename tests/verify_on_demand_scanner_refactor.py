"""
Verification script for on-demand scanner refactoring.
Mocks external dependencies (SSH, Socket) to test logic in isolation.
"""
import asyncio
import os
import socket
import sys
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merlya.context.on_demand_scanner.scanner import OnDemandScanner


def create_connectivity_checker(reachable: bool = True):
    """Create a connectivity checker stub for testing."""
    def checker(hostname: str, port: int) -> bool:
        return reachable
    return checker


async def verify_scanner():
    print("🧪 Verifying OnDemandScanner...")

    # Mock dependencies
    mock_socket = MagicMock()
    mock_socket.getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 22))]

    mock_paramiko = MagicMock()
    mock_ssh = MagicMock()
    mock_paramiko.SSHClient.return_value = mock_ssh

    # Mock SSH command execution - match command patterns used by ssh_scanner
    def exec_command_side_effect(cmd, timeout=None):
        stdin = MagicMock()
        stdout = MagicMock()
        stderr = MagicMock()
        stderr.read.return_value = b""
        # Handle compound commands with fallbacks (cmd1 || cmd2)
        if "hostname" in cmd:
            stdout.read.return_value = b"test-host\n"
        elif "uptime" in cmd:
            stdout.read.return_value = b"up 1 day\n"
        elif "nproc" in cmd or "hw.ncpu" in cmd:
            stdout.read.return_value = b"4\n"
        elif "free -m" in cmd or "hw.memsize" in cmd:
            stdout.read.return_value = b"8192\n"
        elif "uname" in cmd:
            stdout.read.return_value = b"Linux\n"
        elif "cat /etc/os-release" in cmd:
            stdout.read.return_value = b'NAME="Ubuntu"\nVERSION="22.04"\n'
        else:
            stdout.read.return_value = b"\n"
        return stdin, stdout, stderr

    mock_ssh.exec_command.side_effect = exec_command_side_effect

    # Mock CredentialManager
    mock_creds_module = MagicMock()
    mock_creds_class = MagicMock()
    mock_creds_module.CredentialManager = mock_creds_class
    mock_creds_instance = MagicMock()
    mock_creds_class.return_value = mock_creds_instance

    with patch('merlya.context.on_demand_scanner.scanner.socket', mock_socket), \
         patch.dict('sys.modules', {
             'paramiko': mock_paramiko,
             'merlya.security.credentials': mock_creds_module
         }):

        # Create scanner with injected connectivity checker (always returns True)
        scanner = OnDemandScanner(connectivity_checker=create_connectivity_checker(True))

        # Test 1: Basic Scan
        print("1. Testing Basic Scan...")
        result = await scanner.scan_host("test-host", scan_type="basic", force=True)
        assert result.success
        assert result.hostname == "test-host"
        assert result.data["ip"] == "1.2.3.4"
        print("   ✅ Basic Scan passed")

        # Test 2: System Scan (SSH)
        print("2. Testing System Scan (SSH)...")
        # Scanner already has connectivity_checker injected, no need to patch
        result = await scanner.scan_host("test-host", scan_type="system", force=True)
        assert result.success
        assert result.data["ssh_connected"]
        assert result.data["hostname_full"] == "test-host"
        print("   ✅ System Scan passed")

        # Test 3: Batch Scan
        print("3. Testing Batch Scan...")
        results = await scanner.scan_hosts(["host1", "host2"], scan_type="basic", force=True)
        assert len(results) == 2
        assert results[0].success
        assert results[1].success
        print("   ✅ Batch Scan passed")

        # Test 4: Connectivity check failure
        print("4. Testing Connectivity Failure...")
        scanner_unreachable = OnDemandScanner(connectivity_checker=create_connectivity_checker(False))
        result = await scanner_unreachable.scan_host("unreachable-host", scan_type="system", force=True)
        assert result.success  # Scan completes but host is unreachable
        assert "reachable" in result.data and result.data["reachable"] is False
        print("   ✅ Connectivity Failure passed")

    print("\n✅ All on-demand scanner verification steps passed!")

if __name__ == "__main__":
    asyncio.run(verify_scanner())
