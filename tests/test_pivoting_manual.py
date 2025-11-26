"""
Test script for Smart SSH Pivoting.
"""
import os
import sys
from unittest.mock import MagicMock, patch
from athena_ai.memory.persistent_store import KnowledgeStore
from athena_ai.executors.connectivity import ConnectivityPlanner
from athena_ai.executors.ssh import SSHManager

def test_pivoting():
    print("🧪 Testing Smart SSH Pivoting...")
    
    # Use a temporary file for testing
    test_path = "/tmp/athena_test_pivoting.json"
    if os.path.exists(test_path):
        os.remove(test_path)
        
    # 1. Setup Knowledge with a route
    print("1. Setting up routing rules...")
    store = KnowledgeStore(storage_path=test_path)
    store.add_route("10.0.0.0/8", "bastion-prod")
    
    # 2. Test Connectivity Planner
    print("2. Testing Connectivity Planner...")
    planner = ConnectivityPlanner(knowledge_store=store)
    
    # Case A: Public host (no route)
    strategy_public = planner.get_connection_strategy("8.8.8.8", "8.8.8.8")
    print(f"   Strategy for 8.8.8.8: {strategy_public.method}")
    if strategy_public.method == 'direct':
        print("   ✅ Correctly chose direct for public IP")
    else:
        print("   ❌ Failed: Should be direct")
        
    # Case B: Private host (matches route)
    strategy_private = planner.get_connection_strategy("db-prod", "10.0.5.2")
    print(f"   Strategy for 10.0.5.2: {strategy_private.method} via {strategy_private.jump_host}")
    if strategy_private.method == 'jump' and strategy_private.jump_host == "bastion-prod":
        print("   ✅ Correctly chose jump host for private IP")
    else:
        print("   ❌ Failed: Should use bastion-prod")

    # 3. Test SSH Manager Integration (Mocked)
    print("3. Testing SSH Manager Integration...")
    
    with patch('athena_ai.executors.ssh.paramiko.SSHClient') as MockClient:
        ssh_manager = SSHManager(use_connection_pool=False)
        ssh_manager.connectivity = planner # Inject our test planner
        
        # Mock successful connection
        mock_client_instance = MockClient.return_value
        mock_stdout = MagicMock()
        mock_stdout.channel.recv_exit_status.return_value = 0
        mock_stdout.read.return_value = b"Success"
        mock_stdout.channel.settimeout = MagicMock()
        mock_client_instance.exec_command.return_value = (None, mock_stdout, MagicMock())
        
        # Execute command on private host
        print("   Executing command on 10.0.5.2...")
        ssh_manager.execute("10.0.5.2", "hostname")
        
        # Verify jump host connection was attempted
        # We expect 2 client instantiations: 1 for jump, 1 for target
        if MockClient.call_count >= 2:
            print("   ✅ SSH Client instantiated multiple times (Jump + Target)")
            
            # Verify connect calls
            calls = mock_client_instance.connect.call_args_list
            # Check if one of the calls was to bastion-prod
            connected_to_bastion = False
            for call in calls:
                if call[0][0] == "bastion-prod":
                    connected_to_bastion = True
                    break
            
            if connected_to_bastion:
                print("   ✅ Verified connection attempt to bastion-prod")
            else:
                print("   ❌ Did not see connection to bastion-prod")
        else:
            print(f"   ❌ Expected multiple client creations, got {MockClient.call_count}")

    # Cleanup
    if os.path.exists(test_path):
        os.remove(test_path)

if __name__ == "__main__":
    test_pivoting()
