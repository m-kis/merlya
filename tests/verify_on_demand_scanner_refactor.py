"""
Verification script for on-demand scanner refactoring.
Mocks external dependencies (SSH, Socket) to test logic in isolation.
"""
import asyncio
import sys
import os
import socket
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena_ai.context.on_demand_scanner import get_on_demand_scanner, ScanConfig

async def verify_scanner():
    print("🧪 Verifying OnDemandScanner...")
    
    # Mock dependencies
    mock_socket = MagicMock()
    mock_socket.getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.2.3.4', 22))]
    
    mock_paramiko = MagicMock()
    mock_ssh = MagicMock()
    mock_paramiko.SSHClient.return_value = mock_ssh
    
    # Mock SSH command execution
    def exec_command_side_effect(cmd, timeout=None):
        stdout = MagicMock()
        if "hostname" in cmd:
            stdout.read.return_value = b"test-host"
        elif "uptime" in cmd:
            stdout.read.return_value = b"up 1 day"
        else:
            stdout.read.return_value = b""
        return None, stdout, None
    
    mock_ssh.exec_command.side_effect = exec_command_side_effect

    # Mock CredentialManager
    mock_creds_module = MagicMock()
    mock_creds_class = MagicMock()
    mock_creds_module.CredentialManager = mock_creds_class
    mock_creds_instance = MagicMock()
    mock_creds_class.return_value = mock_creds_instance
    
    with patch('athena_ai.context.on_demand_scanner.scanner.socket', mock_socket), \
         patch.dict('sys.modules', {
             'paramiko': mock_paramiko,
             'athena_ai.security.credentials': mock_creds_module
         }):
        
        # Get scanner
        scanner = get_on_demand_scanner()
        
        # Test 1: Basic Scan
        print("1. Testing Basic Scan...")
        result = await scanner.scan_host("test-host", scan_type="basic", force=True)
        assert result.success
        assert result.hostname == "test-host"
        assert result.data["ip"] == "1.2.3.4"
        print("   ✅ Basic Scan passed")
        
        # Test 2: System Scan (SSH)
        print("2. Testing System Scan (SSH)...")
        # Mock connectivity check to return True
        with patch.object(scanner, '_check_connectivity', return_value=True):
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

    print("\n✅ All on-demand scanner verification steps passed!")

if __name__ == "__main__":
    asyncio.run(verify_scanner())
