"""
Verification script for inventory parser refactoring.
Tests all supported formats with valid input.
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from merlya.inventory.parser import get_inventory_parser


def verify_parser():
    print("🧪 Verifying InventoryParser...")
    parser = get_inventory_parser()
    failures = []

    # 1. Test JSON
    try:
        print("1. Testing JSON...")
        json_content = '[{"hostname": "test-json", "ip": "1.2.3.4", "groups": ["g1"]}]'
        result = parser.parse(json_content, format_hint="json")
        assert result.success, "JSON parsing failed"
        assert len(result.hosts) > 0, "JSON parsing returned no hosts"
        assert result.hosts[0].hostname == "test-json", f"Expected hostname 'test-json', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.4", f"Expected IP '1.2.3.4', got {result.hosts[0].ip_address}"
        assert "g1" in result.hosts[0].groups, f"Expected 'g1' in groups, got {result.hosts[0].groups}"
        print("   ✅ JSON passed")
    except (AssertionError, Exception) as e:
        failures.append(f"JSON: {e}")
        print(f"   ❌ JSON failed: {e}")

    # 2. Test CSV
    try:
        print("2. Testing CSV...")
        csv_content = "hostname,ip,environment\ntest-csv,1.2.3.5,prod"
        result = parser.parse(csv_content, format_hint="csv")
        assert result.success, "CSV parsing failed"
        assert len(result.hosts) > 0, "CSV parsing returned no hosts"
        assert result.hosts[0].hostname == "test-csv", f"Expected hostname 'test-csv', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.5", f"Expected IP '1.2.3.5', got {result.hosts[0].ip_address}"
        assert result.hosts[0].environment == "prod", f"Expected environment 'prod', got {result.hosts[0].environment}"
        print("   ✅ CSV passed")
    except (AssertionError, Exception) as e:
        failures.append(f"CSV: {e}")
        print(f"   ❌ CSV failed: {e}")

    # 3. Test YAML
    try:
        print("3. Testing YAML...")
        yaml_content = "---\n- hostname: test-yaml\n  ip: 1.2.3.6\n  ssh_port: 2222"
        result = parser.parse(yaml_content, format_hint="yaml")
        assert result.success, "YAML parsing failed"
        assert len(result.hosts) > 0, "YAML parsing returned no hosts"
        assert result.hosts[0].hostname == "test-yaml", f"Expected hostname 'test-yaml', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.6", f"Expected IP '1.2.3.6', got {result.hosts[0].ip_address}"
        assert result.hosts[0].ssh_port == 2222, f"Expected ssh_port 2222, got {result.hosts[0].ssh_port}"
        print("   ✅ YAML passed")
    except (AssertionError, Exception) as e:
        failures.append(f"YAML: {e}")
        print(f"   ❌ YAML failed: {e}")

    # 4. Test INI (Ansible)
    try:
        print("4. Testing INI...")
        ini_content = """
    [web]
    test-ini ansible_host=1.2.3.7 ansible_user=root
    """
        result = parser.parse(ini_content, format_hint="ini")
        assert result.success, "INI parsing failed"
        assert len(result.hosts) > 0, "INI parsing returned no hosts"
        assert result.hosts[0].hostname == "test-ini", f"Expected hostname 'test-ini', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.7", f"Expected IP '1.2.3.7', got {result.hosts[0].ip_address}"
        assert "web" in result.hosts[0].groups, f"Expected 'web' in groups, got {result.hosts[0].groups}"
        assert result.hosts[0].metadata["ssh_user"] == "root", f"Expected ssh_user 'root', got {result.hosts[0].metadata.get('ssh_user')}"
        print("   ✅ INI passed")
    except (AssertionError, Exception) as e:
        failures.append(f"INI: {e}")
        print(f"   ❌ INI failed: {e}")

    # 5. Test /etc/hosts
    try:
        print("5. Testing /etc/hosts...")
        hosts_content = "1.2.3.8 test-hosts alias1"
        result = parser.parse(hosts_content, format_hint="etc_hosts")
        assert result.success, "/etc/hosts parsing failed"
        assert len(result.hosts) > 0, "/etc/hosts parsing returned no hosts"
        assert result.hosts[0].hostname == "test-hosts", f"Expected hostname 'test-hosts', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.8", f"Expected IP '1.2.3.8', got {result.hosts[0].ip_address}"
        assert "alias1" in result.hosts[0].aliases, f"Expected 'alias1' in aliases, got {result.hosts[0].aliases}"
        print("   ✅ /etc/hosts passed")
    except (AssertionError, Exception) as e:
        failures.append(f"/etc/hosts: {e}")
        print(f"   ❌ /etc/hosts failed: {e}")

    # 6. Test SSH Config
    try:
        print("6. Testing SSH Config...")
        ssh_content = """
    Host test-ssh
        HostName 1.2.3.9
        User admin
        Port 2222
    """
        result = parser.parse(ssh_content, format_hint="ssh_config")
        assert result.success, "SSH Config parsing failed"
        assert len(result.hosts) > 0, "SSH Config parsing returned no hosts"
        assert result.hosts[0].hostname == "test-ssh", f"Expected hostname 'test-ssh', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.9", f"Expected IP '1.2.3.9', got {result.hosts[0].ip_address}"
        assert result.hosts[0].metadata["ssh_user"] == "admin", f"Expected ssh_user 'admin', got {result.hosts[0].metadata.get('ssh_user')}"
        assert result.hosts[0].ssh_port == 2222, f"Expected ssh_port 2222, got {result.hosts[0].ssh_port}"
        print("   ✅ SSH Config passed")
    except (AssertionError, Exception) as e:
        failures.append(f"SSH Config: {e}")
        print(f"   ❌ SSH Config failed: {e}")

    # 7. Test TXT
    try:
        print("7. Testing TXT...")
        txt_content = "test-txt 1.2.3.10"
        result = parser.parse(txt_content, format_hint="txt")
        assert result.success, "TXT parsing failed"
        assert len(result.hosts) > 0, "TXT parsing returned no hosts"
        assert result.hosts[0].hostname == "test-txt", f"Expected hostname 'test-txt', got {result.hosts[0].hostname}"
        assert result.hosts[0].ip_address == "1.2.3.10", f"Expected IP '1.2.3.10', got {result.hosts[0].ip_address}"
        print("   ✅ TXT passed")
    except (AssertionError, Exception) as e:
        failures.append(f"TXT: {e}")
        print(f"   ❌ TXT failed: {e}")

    # 8. Test Auto-detection (self-contained samples for test independence)
    print("8. Testing Auto-detection...")

    # JSON auto-detection
    try:
        auto_json = '[{"hostname": "auto-json", "ip": "10.0.0.1"}]'
        result = parser.parse(auto_json)
        assert result.success, "JSON auto-detection failed"
        assert result.source_type == "json", f"Expected json, got {result.source_type}"
        print("   ✅ JSON auto-detected")
    except (AssertionError, Exception) as e:
        failures.append(f"JSON auto-detection: {e}")
        print(f"   ❌ JSON auto-detection failed: {e}")

    # INI auto-detection
    try:
        auto_ini = "[servers]\nauto-ini ansible_host=10.0.0.2"
        result = parser.parse(auto_ini)
        assert result.success, "INI auto-detection failed"
        assert result.source_type == "ini", f"Expected ini, got {result.source_type}"
        print("   ✅ INI auto-detected")
    except (AssertionError, Exception) as e:
        failures.append(f"INI auto-detection: {e}")
        print(f"   ❌ INI auto-detection failed: {e}")

    # YAML auto-detection
    try:
        auto_yaml = "---\n- hostname: auto-yaml\n  ip: 10.0.0.3"
        result = parser.parse(auto_yaml)
        assert result.success, "YAML auto-detection failed"
        assert result.source_type == "yaml", f"Expected yaml, got {result.source_type}"
        print("   ✅ YAML auto-detected")
    except (AssertionError, Exception) as e:
        failures.append(f"YAML auto-detection: {e}")
        print(f"   ❌ YAML auto-detection failed: {e}")

    # CSV auto-detection
    try:
        auto_csv = "hostname,ip,environment\nauto-csv,10.0.0.4,staging"
        result = parser.parse(auto_csv)
        assert result.success, "CSV auto-detection failed"
        assert result.source_type == "csv", f"Expected csv, got {result.source_type}"
        print("   ✅ CSV auto-detected")
    except (AssertionError, Exception) as e:
        failures.append(f"CSV auto-detection: {e}")
        print(f"   ❌ CSV auto-detection failed: {e}")

    # Summary
    if failures:
        print(f"\n❌ {len(failures)} test(s) failed:")
        for failure in failures:
            print(f"  - {failure}")
        return False
    else:
        print("\n✅ All parser verification steps passed!")
        return True


if __name__ == "__main__":
    try:
        success = verify_parser()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Verification failed with unexpected error: {e}")
        sys.exit(1)
