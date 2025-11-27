"""
Verification script for security fixes.
"""
import sys
import logging
from athena_ai.utils.security import redact_sensitive_info
from athena_ai.security.credentials import CredentialManager, VariableType

def test_redaction():
    print("\n--- Testing Redaction Utility ---")
    
    cases = [
        ("mysql -u root -p 'secret123'", "mysql -u root -p [REDACTED]"),
        ("mysql -u root -p secret123", "mysql -u root -p [REDACTED]"),
        ("curl --header 'Authorization: Bearer token123'", "curl --header 'Authorization: Bearer token123'"), # Not redacted by default patterns
        ("app --password='super_secret'", "app --password=[REDACTED]"),
        ("app --api-key 123456", "app --api-key [REDACTED]"),
    ]
    
    for input_str, expected in cases:
        result = redact_sensitive_info(input_str)
        if result == expected:
            print(f"✅ Redaction passed: {input_str} -> {result}")
        else:
            print(f"❌ Redaction failed: {input_str} -> {result} (Expected: {expected})")

def test_credential_resolution():
    print("\n--- Testing Credential Resolution ---")
    
    cm = CredentialManager()
    cm.set_variable("db_pass", "secret_password", VariableType.SECRET)
    cm.set_variable("db_host", "localhost", VariableType.CONFIG)
    
    query = "connect to @db_host using @db_pass"
    
    # Test with resolve_secrets=True (default)
    resolved_full = cm.resolve_variables(query, resolve_secrets=True)
    if "secret_password" in resolved_full:
        print(f"✅ Full resolution works: {resolved_full}")
    else:
        print(f"❌ Full resolution failed: {resolved_full}")
        
    # Test with resolve_secrets=False (for LLM)
    resolved_safe = cm.resolve_variables(query, resolve_secrets=False)
    if "@db_pass" in resolved_safe and "secret_password" not in resolved_safe:
        print(f"✅ Safe resolution works: {resolved_safe}")
    else:
        print(f"❌ Safe resolution failed: {resolved_safe}")

if __name__ == "__main__":
    test_redaction()
    test_credential_resolution()
