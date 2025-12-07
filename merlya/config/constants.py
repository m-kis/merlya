"""
Merlya Configuration Constants.

Centralized constants for timeouts, limits, and other magic values.
"""

# SSH Timeouts (seconds)
SSH_DEFAULT_TIMEOUT = 60
SSH_CONNECT_TIMEOUT = 15
SSH_PROBE_TIMEOUT = 10
SSH_CLOSE_TIMEOUT = 10.0

# User Interaction Timeouts (seconds)
MFA_PROMPT_TIMEOUT = 120
PASSPHRASE_PROMPT_TIMEOUT = 60

# Input Limits
MAX_USER_INPUT_LENGTH = 10_000
MAX_FILE_PATH_LENGTH = 4_096
MAX_PATTERN_LENGTH = 256
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# Security
DEFAULT_SECURITY_SCAN_TIMEOUT = 20
