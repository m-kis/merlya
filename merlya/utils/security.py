"""
Security utilities for Merlya.
"""
import re
from typing import List, Optional


def redact_sensitive_info(text: str, extra_secrets: Optional[List[str]] = None) -> Optional[str]:
    """
    Redact sensitive information (passwords, tokens, keys) from text for logging.

    Patterns redacted:
    - CLI flags: -p 'password', --password='value', --token=value, etc.
    - Environment variables: PASSWORD=secret, export TOKEN=value, VAR="secret"
    - URL query params: ?password=secret, &api_key=value, &token=abc
    - JSON key-value pairs: "password": "secret", "token": "value"
    - XML elements: <password>secret</password>, <token>value</token>
    - Connection strings: mysql://user:password@host, //user:pass@host
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
            # Use direct string replacement to reliably redact exact secrets
            redacted = redacted.replace(secret, '[REDACTED]')

    # 2. Redact command line flags

    # Note: Single-letter -p flag is NOT redacted due to ambiguity
    # (port, path, process, pid, etc.). Use --password or add secrets to extra_secrets.
    # Only redact long-form password flags to avoid false positives.

    # --password='value' or --password="value" (long flags with = and quotes)
    password_flags = ['password', 'passwd', 'pass', 'pwd', 'secret', 'token', 'api-key',
                     'apikey', 'auth', 'credential', 'key']

    for flag in password_flags:
        # Quoted values - uses backreference (\2) to match closing quote, allowing embedded opposite quotes and empty values
        redacted = re.sub(rf"(--{flag}[=\s]+)(['\"])(.*?)(\2)", r"\1\2[REDACTED]\4", redacted, flags=re.IGNORECASE)
        # Without quotes - negative lookahead ensures we don't match if a quote follows
        redacted = re.sub(rf"(--{flag}[=\s]+)(?!['\"])(\S+)", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)

    # 3. Redact environment variable assignments
    # Matches: VAR=secret, export VAR=secret, VAR="secret", VAR='secret'
    # Only redacts values for sensitive variable names
    # Requires word boundary before var name to avoid matching URL params like &password=
    env_var_names = ['PASSWORD', 'PASSWD', 'PASS', 'PWD', 'SECRET', 'TOKEN', 'API_KEY',
                     'APIKEY', 'AUTH', 'CREDENTIAL', 'KEY', 'DB_PASSWORD', 'DB_PASS',
                     'MYSQL_PASSWORD', 'POSTGRES_PASSWORD', 'REDIS_PASSWORD',
                     'AWS_SECRET_ACCESS_KEY', 'PRIVATE_KEY', 'ACCESS_TOKEN']

    for var in env_var_names:
        # export VAR="value" or export VAR='value'
        # Use word boundary (\b) or start of line to avoid matching URL params
        redacted = re.sub(
            rf"((?:^|(?<=\s)|(?<=export\s))(?:export\s+)?{var}\s*=\s*)(['\"])(.{{4,}})(\2)",
            r"\1\2[REDACTED]\4",
            redacted,
            flags=re.IGNORECASE | re.MULTILINE
        )
        # export VAR=value (unquoted, min 4 chars to avoid false positives)
        # Require start of line, whitespace, or 'export' before var name
        redacted = re.sub(
            rf"((?:^|(?<=\s))(?:export\s+)?{var}\s*=\s*)([^\s'\"].{{3,}})(?=\s|$)",
            r"\1[REDACTED]",
            redacted,
            flags=re.IGNORECASE | re.MULTILINE
        )

    # 4. Redact URL query parameters with sensitive keys
    # Matches: ?password=secret, &api_key=secret, &token=abc123
    url_param_keys = ['password', 'passwd', 'pass', 'pwd', 'secret', 'token', 'api_key',
                      'apikey', 'api-key', 'auth', 'key', 'access_token', 'refresh_token',
                      'client_secret', 'private_key']

    for key in url_param_keys:
        # Match ?key=value or &key=value, stop at &, #, space, or end
        # Use non-greedy match and explicit delimiter handling
        redacted = re.sub(
            rf"([?&]{key}=)([^&#\s]*?)(?=&|#|\s|$)",
            r"\1[REDACTED]",
            redacted,
            flags=re.IGNORECASE
        )

    # 5. Redact JSON key-value pairs with sensitive keys
    # Matches: "password": "value", "password": 'value', "password":"value"
    json_keys = ['password', 'passwd', 'pass', 'pwd', 'secret', 'token', 'api_key',
                 'apikey', 'api-key', 'auth', 'key', 'access_token', 'refresh_token',
                 'client_secret', 'private_key', 'credential', 'credentials']

    for key in json_keys:
        # "key": "value" or "key": 'value' (with optional whitespace)
        # Use a function to preserve original key case and spacing
        def json_quoted_replacer(match):
            # match.group(1) = key quote char, match.group(2) = key name,
            # match.group(3) = colon+whitespace, match.group(4) = value quote char
            return f'{match.group(1)}{match.group(2)}{match.group(1)}{match.group(3)}{match.group(4)}[REDACTED]{match.group(4)}'

        redacted = re.sub(
            rf'(["\'])({key})\1(:\s*)(["\'])((?:(?!\4).)*)\4',
            json_quoted_replacer,
            redacted,
            flags=re.IGNORECASE
        )
        # "key": value (unquoted value - numbers, booleans, etc.)
        def json_unquoted_replacer(match):
            # match.group(1) = key quote char, match.group(2) = key name,
            # match.group(3) = colon+whitespace
            return f'{match.group(1)}{match.group(2)}{match.group(1)}{match.group(3)}[REDACTED]'

        redacted = re.sub(
            rf'(["\'])({key})\1(:\s*)([^\s,\}}\]"\']+)',
            json_unquoted_replacer,
            redacted,
            flags=re.IGNORECASE
        )

    # 6. Redact XML element content with sensitive tags
    # Matches: <password>secret</password>, <token>abc</token>
    xml_tags = ['password', 'passwd', 'pass', 'pwd', 'secret', 'token', 'apikey',
                'api-key', 'auth', 'key', 'accesstoken', 'credential']

    for tag in xml_tags:
        # <tag>value</tag> or <tag attr="...">value</tag>
        redacted = re.sub(
            rf'(<{tag}(?:\s+[^>]*)?>)([^<]+?)(</{tag}>)',
            r'\1[REDACTED]\3',
            redacted,
            flags=re.IGNORECASE
        )

    # 7. Redact credentials in connection strings (user:pass@host)
    # Only replace password portion, preserve username and host
    # Matches: scheme://user:password@host
    # The pattern requires :// before user:pass@host to avoid matching other formats
    redacted = re.sub(
        r'(://[a-zA-Z0-9_.-]+:)([^@\s]{4,})(@[a-zA-Z0-9_.\[\]:-]+(?:/[^\s]*)?)',
        r'\1[REDACTED]\3',
        redacted
    )
    # Also match //user:pass@host format (no scheme)
    redacted = re.sub(
        r'(//[a-zA-Z0-9_.-]+:)([^@\s]{4,})(@[a-zA-Z0-9_.\[\]:-]+(?:/[^\s]*)?)',
        r'\1[REDACTED]\3',
        redacted
    )

    # 8. Redact Authorization Bearer tokens
    # Matches: Authorization: Bearer <token>, Bearer <token>
    # Bearer tokens are sensitive credentials that grant access
    # Token pattern includes: alphanumeric, dash, underscore, dot (JWT/base64url)
    # plus +, /, = for standard base64 encoding used in some OAuth tokens
    redacted = re.sub(
        r'(Authorization:\s*Bearer\s+)([a-zA-Z0-9_.\-+/=]+)',
        r'\1[REDACTED]',
        redacted,
        flags=re.IGNORECASE
    )
    # Standalone Bearer token (8+ chars to avoid false positives like "Bearer short")
    redacted = re.sub(
        r'(Bearer\s+)([a-zA-Z0-9_.\-+/=]{8,})',
        r'\1[REDACTED]',
        redacted,
        flags=re.IGNORECASE
    )

    return redacted
