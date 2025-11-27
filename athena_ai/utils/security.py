"""
Security utilities for Athena.
"""
import re
from typing import List, Optional

def redact_sensitive_info(text: str, extra_secrets: Optional[List[str]] = None) -> str:
    """
    Redact sensitive information (passwords, tokens, keys) from text for logging.

    Patterns redacted:
    - -p 'password' or -p "password" or -p password
    - --password='password' or --password="password" or --password password
    - --pass, --passwd, --secret, --token, --api-key, etc.
    - Known secrets provided in extra_secrets

    Args:
        text: Original text with potential sensitive data
        extra_secrets: Optional list of specific secret values to redact

    Returns:
        Text with sensitive values replaced by [REDACTED]
    """
    if not text:
        return text

    redacted = text

    # 1. Redact specific known secrets first (longest first to avoid partial matches)
    if extra_secrets:
        # Sort by length descending to handle overlapping secrets
        sorted_secrets = sorted([s for s in extra_secrets if s], key=len, reverse=True)
        for secret in sorted_secrets:
            if len(secret) < 3:  # Don't redact very short strings to avoid false positives
                continue
            redacted = redacted.replace(secret, "[REDACTED]")

    # 2. Redact command line flags
    
    # Pattern 1: -p 'value' or -p "value" (single letter flags with quotes)
    # Use backreference to ensure matching quotes (group 2 captures the quote type)
    redacted = re.sub(r"(-p\s+)(['\"])([^'\"]+)\2", r"\1\2[REDACTED]\2", redacted)

    # Pattern 2: -p value (single letter flags without quotes, stops at next flag or space)
    redacted = re.sub(r"(-p\s+)(\S+)", r"\1[REDACTED]", redacted)

    # Pattern 3: --password='value' or --password="value" (long flags with = and quotes)
    password_flags = ['password', 'passwd', 'pass', 'pwd', 'secret', 'token', 'api-key', 
                     'apikey', 'auth', 'credential', 'key']
    
    for flag in password_flags:
        # With quotes - use backreference to ensure matching quotes
        redacted = re.sub(rf"(--{flag}[=\s]+)(['\"])([^'\"]+)\2", r"\1\2[REDACTED]\2", redacted, flags=re.IGNORECASE)
        # Without quotes
        redacted = re.sub(rf"(--{flag}[=\s]+)(\S+)", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)

    return redacted
