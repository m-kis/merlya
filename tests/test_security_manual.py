"""
Test script for DevSecOps Tools.
"""
import sys
from unittest.mock import MagicMock
from athena_ai.agents import autogen_tools

def test_security_tools():
    print("🧪 Testing DevSecOps Tools...")
    
    # Mock executor
    mock_executor = MagicMock()
    autogen_tools._executor = mock_executor
    
    # 1. Test Audit Host
    print("1. Testing audit_host...")
    
    # Mock responses for audit commands
    def audit_side_effect(target, command, **kwargs):
        if "ss -tuln" in command:
            return {'success': True, 'stdout': "LISTEN 0 128 0.0.0.0:22 0.0.0.0:* \nLISTEN 0 128 0.0.0.0:80 0.0.0.0:*"}
        elif "sshd_config" in command:
            return {'success': True, 'stdout': "PermitRootLogin yes\nPasswordAuthentication yes"}
        elif "sudoers" in command:
            return {'success': True, 'stdout': "root ALL=(ALL:ALL) ALL\nadmin ALL=(ALL) ALL"}
        return {'success': False, 'stderr': "Unknown command"}
        
    mock_executor.execute.side_effect = audit_side_effect
    
    report = autogen_tools.audit_host("test-server")
    print("\n--- Audit Report Preview ---")
    print(report)
    print("----------------------------\n")
    
    if "PermitRootLogin yes" in report and "High Risk" in report:
        print("✅ Audit correctly identified RootLogin risk")
    else:
        print("❌ Audit failed to identify RootLogin risk")
        
    if "0.0.0.0:80" in report:
        print("✅ Audit correctly listed open ports")
    else:
        print("❌ Audit failed to list ports")

    # 2. Test Log Analysis
    print("\n2. Testing analyze_security_logs...")
    
    # Mock responses for log analysis
    def log_side_effect(target, command, **kwargs):
        if "ls /var/log" in command:
            return {'success': True, 'stdout': "/var/log/auth.log"}
        elif "tail -n" in command:
            return {'success': True, 'stdout': """
Nov 24 10:00:01 server sshd[123]: Failed password for root from 192.168.1.50 port 22 ssh2
Nov 24 10:00:02 server sshd[123]: Failed password for root from 192.168.1.50 port 22 ssh2
Nov 24 10:00:03 server sshd[123]: Failed password for root from 192.168.1.50 port 22 ssh2
Nov 24 10:00:04 server sshd[123]: Failed password for root from 192.168.1.50 port 22 ssh2
Nov 24 10:00:05 server sshd[123]: Failed password for root from 192.168.1.50 port 22 ssh2
Nov 24 10:00:06 server sshd[123]: Failed password for root from 192.168.1.50 port 22 ssh2
Nov 24 10:05:00 server sudo: admin : TTY=pts/0 ; PWD=/home/admin ; USER=root ; COMMAND=/bin/bash
            """}
        return {'success': False}
        
    mock_executor.execute.side_effect = log_side_effect
    
    analysis = autogen_tools.analyze_security_logs("test-server")
    print("\n--- Log Analysis Preview ---")
    print(analysis)
    print("----------------------------\n")
    
    if "Failed Logins: 6 ⚠️ HIGH" in analysis:
        print("✅ Analysis correctly flagged high failure rate")
    else:
        print("❌ Analysis failed to flag failures")
        
    if "Sudo Usage: 1" in analysis:
        print("✅ Analysis correctly counted sudo usage")
    else:
        print("❌ Analysis failed to count sudo")

if __name__ == "__main__":
    test_security_tools()
