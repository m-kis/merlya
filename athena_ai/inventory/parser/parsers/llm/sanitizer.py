"""
Sanitization logic for LLM parser.
"""
import json
import re
from typing import List, Tuple


def sanitize_inventory_content(content: str) -> str:
    """
    Sanitize inventory content to remove/redact PII and sensitive infrastructure details.

    This function applies multiple redaction passes to protect:
    - IP addresses (replaced with placeholders)
    - Hostnames (generalized to remove identifying components)
    - Environment indicators (prod/staging/dev kept but specific names redacted)
    - Known sensitive metadata patterns

    Args:
        content: Raw inventory content that may contain sensitive data

    Returns:
        Sanitized content safe for LLM processing
    """
    if not content:
        return content

    sanitized = content

    # 1. Redact MAC addresses FIRST (before IPv6, as patterns can overlap)
    # MAC format: XX:XX:XX:XX:XX:XX or XX-XX-XX-XX-XX-XX
    sanitized = re.sub(
        r'\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b',
        '[MAC_REDACTED]',
        sanitized
    )

    # 2. Redact IPv4 addresses (replace with placeholder preserving structure hints)
    # IPv4 with proper octet range validation (0-255)
    sanitized = re.sub(
        r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b',
        r'[IP_REDACTED]',
        sanitized
    )

    # 3. Redact IPv6 addresses
    # More specific pattern to avoid matching MAC addresses
    # Requires at least one group with 3-4 hex digits or :: notation
    sanitized = re.sub(
        r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b',  # Full IPv6
        '[IPV6_REDACTED]',
        sanitized
    )
    sanitized = re.sub(
        r'\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b',  # IPv6 with trailing ::
        '[IPV6_REDACTED]',
        sanitized
    )
    sanitized = re.sub(
        r'\b::(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}\b',  # IPv6 with leading ::
        '[IPV6_REDACTED]',
        sanitized
    )

    # 4. Generalize hostnames - keep structure but redact identifying parts
    # Pattern matches common hostname formats: server01.prod.company.com
    # Replace company/domain-specific parts while keeping structural info

    # FQDN pattern: redact domain portions after first dot
    sanitized = re.sub(
        r'\b([a-zA-Z][a-zA-Z0-9_-]*)\.((?:[a-zA-Z0-9_-]+\.)+[a-zA-Z]{2,})\b',
        r'\1.[DOMAIN_REDACTED]',
        sanitized
    )

    # 5. Redact AWS-style identifiers (account IDs, instance IDs, etc.)
    # AWS account ID (12 digits)
    sanitized = re.sub(r'\b\d{12}\b', '[AWS_ACCOUNT_REDACTED]', sanitized)
    # EC2 instance IDs: i-xxxxxxxxxxxxxxxxx
    sanitized = re.sub(r'\bi-[0-9a-f]{8,17}\b', '[INSTANCE_ID_REDACTED]', sanitized)
    # AWS ARNs
    sanitized = re.sub(
        r'arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d*:[a-zA-Z0-9_/:-]+',
        '[ARN_REDACTED]',
        sanitized
    )

    # 6. Redact GCP-style project IDs and resource names
    sanitized = re.sub(
        r'projects/[a-z][a-z0-9-]{4,28}[a-z0-9]',
        'projects/[PROJECT_REDACTED]',
        sanitized
    )

    # 7. Redact Azure subscription IDs (UUID format)
    sanitized = re.sub(
        r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',
        '[UUID_REDACTED]',
        sanitized,
        flags=re.IGNORECASE
    )

    # 8. Redact common sensitive metadata keys and their values
    sensitive_keys = [
        'ansible_user', 'ansible_password', 'ansible_ssh_pass',
        'ansible_become_pass', 'ansible_sudo_pass',
        'ssh_user', 'ssh_password', 'ssh_key', 'ssh_key_file',
        'password', 'secret', 'token', 'api_key', 'private_key',
        'access_key', 'secret_key', 'credentials',
        'owner', 'contact', 'email', 'admin', 'maintainer'
    ]

    for key in sensitive_keys:
        # YAML format: key: value
        sanitized = re.sub(
            rf'(\b{key}\s*:\s*)([^\n\r]+)',
            rf'\1[REDACTED]',
            sanitized,
            flags=re.IGNORECASE
        )
        # INI format: key=value
        sanitized = re.sub(
            rf'(\b{key}\s*=\s*)([^\n\r]+)',
            rf'\1[REDACTED]',
            sanitized,
            flags=re.IGNORECASE
        )

    # 9. Redact email addresses
    sanitized = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        '[EMAIL_REDACTED]',
        sanitized
    )

    # 10. Redact specific environment/company identifiers
    # Common patterns in inventory files that might reveal org structure
    env_patterns = [
        (r'\b(corp|internal|private|company)[.-][a-z]+\b', '[INTERNAL_DOMAIN]'),
        (r'\b[a-z]+-(?:prod|production|staging|stg|dev|development|test|qa|uat)\b', '[ENV_HOST]'),
    ]
    for pattern, replacement in env_patterns:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    return sanitized


def sanitize_prompt_injection(content: str) -> Tuple[str, List[str]]:
    """
    Sanitize content to neutralize common prompt injection patterns.

    This function detects and neutralizes text patterns commonly used in prompt
    injection attacks. Detected patterns are replaced with safe placeholders
    and logged for audit purposes.

    Args:
        content: Content that may contain injection attempts

    Returns:
        Tuple of (sanitized_content, list of detected injection patterns)
    """
    if not content:
        return content, []

    detected_patterns = []
    sanitized = content

    # Common prompt injection patterns (case-insensitive)
    injection_patterns = [
        # Instruction override attempts
        (r'(?i)\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?|context)',
         '[INJECTION_BLOCKED:instruction_override]'),
        (r'(?i)\b(do\s+not|don\'t|never)\s+follow\s+(earlier|previous|prior|above)\s+(instructions?|rules?)',
         '[INJECTION_BLOCKED:instruction_override]'),
        (r'(?i)\bnew\s+instructions?\s*:',
         '[INJECTION_BLOCKED:new_instructions]'),
        (r'(?i)\bsystem\s*:\s*you\s+are',
         '[INJECTION_BLOCKED:system_prompt]'),

        # Output manipulation
        (r'(?i)\breturn\s+only\s+["\']',
         '[INJECTION_BLOCKED:output_manipulation]'),
        (r'(?i)\boutput\s+(only|exactly|just)\s*["\':]+',
         '[INJECTION_BLOCKED:output_manipulation]'),
        (r'(?i)\brespond\s+(with|only)\s+(the\s+)?(following|this)',
         '[INJECTION_BLOCKED:output_manipulation]'),
        (r'(?i)\bprint\s+(only|exactly|just)\s*["\':]+',
         '[INJECTION_BLOCKED:output_manipulation]'),

        # Role manipulation
        (r'(?i)\byou\s+are\s+(now\s+)?(a|an|acting\s+as)',
         '[INJECTION_BLOCKED:role_manipulation]'),
        (r'(?i)\bpretend\s+(to\s+be|you\s+are)',
         '[INJECTION_BLOCKED:role_manipulation]'),
        (r'(?i)\bact\s+as\s+(if\s+you\s+are|a|an)',
         '[INJECTION_BLOCKED:role_manipulation]'),

        # Delimiter escape attempts
        (r'```\s*(end|stop|ignore|exit)',
         '[INJECTION_BLOCKED:delimiter_escape]'),
        (r'(?i)\b(end|close)\s+(of\s+)?(content|inventory|data|input)',
         '[INJECTION_BLOCKED:delimiter_escape]'),

        # JSON injection in supposed inventory
        (r'(?i)"(instructions?|system|prompt|role)"\s*:\s*"',
         '[INJECTION_BLOCKED:json_injection]'),
    ]

    for pattern, replacement in injection_patterns:
        matches = re.findall(pattern, sanitized)
        if matches:
            # Log the actual matched text for audit
            for match in matches:
                match_text = match if isinstance(match, str) else match[0] if match else ''
                if match_text:
                    detected_patterns.append(f"Pattern detected: {match_text[:50]}...")
            sanitized = re.sub(pattern, replacement, sanitized)

    return sanitized, detected_patterns


def encode_content_for_prompt(content: str) -> str:
    """
    JSON-encode content for safe embedding in prompts.

    This provides an additional layer of protection by encoding the content
    as a JSON string, which escapes special characters and makes injection
    patterns less likely to be interpreted as instructions.

    Args:
        content: Content to encode

    Returns:
        JSON-encoded string (without outer quotes)
    """
    # json.dumps adds quotes, we strip them for embedding
    encoded = json.dumps(content)
    # Remove the outer quotes since we'll wrap it ourselves
    return encoded[1:-1] if encoded.startswith('"') and encoded.endswith('"') else encoded
