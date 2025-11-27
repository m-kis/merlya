"""
Verification script for security fixes.
"""
import sys
import logging
from unittest.mock import patch
from athena_ai.utils.security import redact_sensitive_info
from athena_ai.security.credentials import CredentialManager, VariableType

# Sentinel value for testing secret resolution without exposing real secrets
_SECRET_SENTINEL = "<RESOLVED_SECRET_SENTINEL>"

def test_redaction():
    print("\n--- Testing Redaction Utility ---")

    cases = [
        # CLI flag patterns (existing)
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


def test_env_redaction():
    """Test environment variable assignment redaction."""
    print("\n--- Testing Environment Variable Redaction ---")

    cases = [
        # Unquoted assignments
        ("PASSWORD=mysecret123", "PASSWORD=[REDACTED]"),
        ("export TOKEN=abc123xyz", "export TOKEN=[REDACTED]"),
        ("DB_PASSWORD=longpassword", "DB_PASSWORD=[REDACTED]"),
        ("AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE", "AWS_SECRET_ACCESS_KEY=[REDACTED]"),
        # Quoted assignments
        ("PASSWORD='mysecret123'", "PASSWORD='[REDACTED]'"),
        ('TOKEN="abc123xyz"', 'TOKEN="[REDACTED]"'),
        ("export SECRET='very_secret_value'", "export SECRET='[REDACTED]'"),
        # Short values should NOT be redacted (less than 4 chars)
        ("PASSWORD=abc", "PASSWORD=abc"),  # Too short
        # Non-sensitive vars should NOT be redacted
        ("HOME=/usr/local", "HOME=/usr/local"),
        ("PATH=/bin:/usr/bin", "PATH=/bin:/usr/bin"),
        # Case insensitive
        ("password=MySecret", "password=[REDACTED]"),
        ("Password=MySecret", "Password=[REDACTED]"),
    ]

    for input_str, expected in cases:
        result = redact_sensitive_info(input_str)
        if result == expected:
            print(f"✅ Env redaction passed: {input_str} -> {result}")
        else:
            print(f"❌ Env redaction failed: {input_str} -> {result} (Expected: {expected})")


def test_url_param_redaction():
    """Test URL query parameter redaction."""
    print("\n--- Testing URL Query Parameter Redaction ---")

    cases = [
        # Single params
        ("https://api.example.com?password=secret123", "https://api.example.com?password=[REDACTED]"),
        ("https://api.example.com?api_key=abcdef", "https://api.example.com?api_key=[REDACTED]"),
        ("https://api.example.com?token=xyz789", "https://api.example.com?token=[REDACTED]"),
        # Multiple params
        ("https://api.example.com?user=john&password=secret&action=login",
         "https://api.example.com?user=john&password=[REDACTED]&action=login"),
        ("https://api.example.com?api_key=abc&token=def&callback=url",
         "https://api.example.com?api_key=[REDACTED]&token=[REDACTED]&callback=url"),
        # With hash/fragment
        ("https://example.com?password=secret#section", "https://example.com?password=[REDACTED]#section"),
        # Case insensitive
        ("https://api.com?Password=Secret", "https://api.com?Password=[REDACTED]"),
        ("https://api.com?API_KEY=Secret", "https://api.com?API_KEY=[REDACTED]"),
        # Non-sensitive params should NOT be redacted
        ("https://api.com?user=john&page=5", "https://api.com?user=john&page=5"),
    ]

    for input_str, expected in cases:
        result = redact_sensitive_info(input_str)
        if result == expected:
            print(f"✅ URL param redaction passed: {input_str} -> {result}")
        else:
            print(f"❌ URL param redaction failed: {input_str} -> {result} (Expected: {expected})")


def test_json_redaction():
    """Test JSON key-value pair redaction."""
    print("\n--- Testing JSON Redaction ---")

    cases = [
        # Basic JSON patterns
        ('{"password": "secret123"}', '{"password": "[REDACTED]"}'),
        ('{"token": "abc123"}', '{"token": "[REDACTED]"}'),
        ('{"api_key": "xyz789"}', '{"api_key": "[REDACTED]"}'),
        # With single quotes
        ("{'password': 'secret123'}", "{'password': '[REDACTED]'}"),
        # No space after colon
        ('{"password":"secret123"}', '{"password": "[REDACTED]"}'),
        # Multiple keys
        ('{"user": "john", "password": "secret", "role": "admin"}',
         '{"user": "john", "password": "[REDACTED]", "role": "admin"}'),
        # Case insensitive
        ('{"Password": "Secret123"}', '{"Password": "[REDACTED]"}'),
        ('{"TOKEN": "abc"}', '{"TOKEN": "[REDACTED]"}'),
        # Non-sensitive keys should NOT be redacted
        ('{"username": "john", "email": "john@example.com"}',
         '{"username": "john", "email": "john@example.com"}'),
    ]

    for input_str, expected in cases:
        result = redact_sensitive_info(input_str)
        if result == expected:
            print(f"✅ JSON redaction passed: {input_str} -> {result}")
        else:
            print(f"❌ JSON redaction failed: {input_str} -> {result} (Expected: {expected})")


def test_xml_redaction():
    """Test XML element content redaction."""
    print("\n--- Testing XML Redaction ---")

    cases = [
        # Basic XML tags
        ("<password>secret123</password>", "<password>[REDACTED]</password>"),
        ("<token>abc123xyz</token>", "<token>[REDACTED]</token>"),
        ("<secret>mysecretvalue</secret>", "<secret>[REDACTED]</secret>"),
        # With attributes
        ('<password type="hash">secret123</password>', '<password type="hash">[REDACTED]</password>'),
        # Case insensitive
        ("<PASSWORD>Secret</PASSWORD>", "<PASSWORD>[REDACTED]</PASSWORD>"),
        ("<Token>abc123</Token>", "<Token>[REDACTED]</Token>"),
        # Within larger XML
        ("<config><user>john</user><password>secret</password></config>",
         "<config><user>john</user><password>[REDACTED]</password></config>"),
        # Non-sensitive tags should NOT be redacted
        ("<username>john</username>", "<username>john</username>"),
        ("<email>john@example.com</email>", "<email>john@example.com</email>"),
    ]

    for input_str, expected in cases:
        result = redact_sensitive_info(input_str)
        if result == expected:
            print(f"✅ XML redaction passed: {input_str} -> {result}")
        else:
            print(f"❌ XML redaction failed: {input_str} -> {result} (Expected: {expected})")


def test_connection_string_redaction():
    """Test connection string credential redaction."""
    print("\n--- Testing Connection String Redaction ---")

    cases = [
        # Basic connection strings
        ("mysql://user:password123@localhost:3306/db", "mysql://user:[REDACTED]@localhost:3306/db"),
        ("postgresql://admin:supersecret@db.example.com/mydb", "postgresql://admin:[REDACTED]@db.example.com/mydb"),
        ("redis://default:mypassword@redis.example.com:6379", "redis://default:[REDACTED]@redis.example.com:6379"),
        # MongoDB style
        ("mongodb://user:pass1234@mongo.example.com:27017", "mongodb://user:[REDACTED]@mongo.example.com:27017"),
        # With //
        ("//user:secretpass@host.com", "//user:[REDACTED]@host.com"),
        # Short passwords (less than 4 chars) should NOT be redacted
        ("mysql://user:abc@localhost", "mysql://user:abc@localhost"),
        # Email addresses should NOT be redacted (no :// prefix and @ is part of email)
        # Note: email@domain.com won't match because there's no user: prefix
    ]

    for input_str, expected in cases:
        result = redact_sensitive_info(input_str)
        if result == expected:
            print(f"✅ Connection string redaction passed: {input_str} -> {result}")
        else:
            print(f"❌ Connection string redaction failed: {input_str} -> {result} (Expected: {expected})")

def test_credential_resolution():
    print("\n--- Testing Credential Resolution ---")

    cm = CredentialManager()
    # Use sentinel value instead of actual secret to avoid leaking secrets in tests
    cm.set_variable("db_pass", _SECRET_SENTINEL, VariableType.SECRET)
    cm.set_variable("db_host", "localhost", VariableType.CONFIG)

    query = "connect to @db_host using @db_pass"

    # Test with resolve_secrets=True (default)
    resolved_full = cm.resolve_variables(query, resolve_secrets=True)
    # Verify sentinel appears and @db_pass reference is gone (without checking actual secret values)
    if _SECRET_SENTINEL in resolved_full and "@db_pass" not in resolved_full:
        print("✅ Full resolution works: secrets resolved correctly")
    else:
        print("❌ Full resolution failed: secret not resolved")

    # Test with resolve_secrets=False (for LLM)
    resolved_safe = cm.resolve_variables(query, resolve_secrets=False)
    # Verify @db_pass is preserved and sentinel is NOT in the safe output
    if "@db_pass" in resolved_safe and _SECRET_SENTINEL not in resolved_safe:
        print(f"✅ Safe resolution works: {resolved_safe}")
    else:
        print(f"❌ Safe resolution failed: {resolved_safe}")

if __name__ == "__main__":
    test_redaction()
    test_env_redaction()
    test_url_param_redaction()
    test_json_redaction()
    test_xml_redaction()
    test_connection_string_redaction()
    test_credential_resolution()
