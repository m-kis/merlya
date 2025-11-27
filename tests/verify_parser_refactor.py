"""
Verification script for inventory parser refactoring.
Tests all supported formats with valid input.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from athena_ai.inventory.parser import get_inventory_parser

def verify_parser():
    print("🧪 Verifying InventoryParser...")
    parser = get_inventory_parser()
    
    # 1. Test JSON
    print("1. Testing JSON...")
    json_content = '[{"hostname": "test-json", "ip": "1.2.3.4", "groups": ["g1"]}]'
    result = parser.parse(json_content, format_hint="json")
    assert result.success
    assert result.hosts[0].hostname == "test-json"
    assert result.hosts[0].ip_address == "1.2.3.4"
    assert "g1" in result.hosts[0].groups
    print("   ✅ JSON passed")
    
    # 2. Test CSV
    print("2. Testing CSV...")
    csv_content = "hostname,ip,environment\ntest-csv,1.2.3.5,prod"
    result = parser.parse(csv_content, format_hint="csv")
    assert result.success
    assert result.hosts[0].hostname == "test-csv"
    assert result.hosts[0].ip_address == "1.2.3.5"
    assert result.hosts[0].environment == "prod"
    print("   ✅ CSV passed")
    
    # 3. Test YAML
    print("3. Testing YAML...")
    yaml_content = "---\n- hostname: test-yaml\n  ip: 1.2.3.6\n  ssh_port: 2222"
    result = parser.parse(yaml_content, format_hint="yaml")
    assert result.success
    assert result.hosts[0].hostname == "test-yaml"
    assert result.hosts[0].ip_address == "1.2.3.6"
    assert result.hosts[0].ssh_port == 2222
    print("   ✅ YAML passed")
    
    # 4. Test INI (Ansible)
    print("4. Testing INI...")
    ini_content = """
    [web]
    test-ini ansible_host=1.2.3.7 ansible_user=root
    """
    result = parser.parse(ini_content, format_hint="ini")
    assert result.success
    assert result.hosts[0].hostname == "test-ini"
    assert result.hosts[0].ip_address == "1.2.3.7"
    assert result.hosts[0].groups == ["web"]
    assert result.hosts[0].metadata["ssh_user"] == "root"
    print("   ✅ INI passed")
    
    # 5. Test /etc/hosts
    print("5. Testing /etc/hosts...")
    hosts_content = "1.2.3.8 test-hosts alias1"
    result = parser.parse(hosts_content, format_hint="etc_hosts")
    assert result.success
    assert result.hosts[0].hostname == "test-hosts"
    assert result.hosts[0].ip_address == "1.2.3.8"
    assert "alias1" in result.hosts[0].aliases
    print("   ✅ /etc/hosts passed")
    
    # 6. Test SSH Config
    print("6. Testing SSH Config...")
    ssh_content = """
    Host test-ssh
        HostName 1.2.3.9
        User admin
        Port 2222
    """
    result = parser.parse(ssh_content, format_hint="ssh_config")
    assert result.success
    assert result.hosts[0].hostname == "test-ssh"
    assert result.hosts[0].ip_address == "1.2.3.9"
    assert result.hosts[0].metadata["ssh_user"] == "admin"
    assert result.hosts[0].ssh_port == 2222
    print("   ✅ SSH Config passed")
    
    # 7. Test TXT
    print("7. Testing TXT...")
    txt_content = "test-txt 1.2.3.10"
    result = parser.parse(txt_content, format_hint="txt")
    assert result.success
    assert result.hosts[0].hostname == "test-txt"
    assert result.hosts[0].ip_address == "1.2.3.10"
    print("   ✅ TXT passed")
    
    # 8. Test Auto-detection
    print("8. Testing Auto-detection...")
    result = parser.parse(json_content) # Should detect JSON
    assert result.success
    assert result.source_type == "json"
    
    result = parser.parse(ini_content) # Should detect INI
    assert result.success
    assert result.source_type == "ini"
    print("   ✅ Auto-detection passed")

    print("\n✅ All parser verification steps passed!")

if __name__ == "__main__":
    verify_parser()
