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

# Cache
COMPLETION_CACHE_TTL_SECONDS = 30  # Time-to-live for completion cache

# UI/Display
TITLE_MAX_LENGTH = 60  # Max characters for conversation title
DEFAULT_LIST_LIMIT = 10  # Default limit for list operations
MAX_LIST_LIMIT = 100  # Maximum allowed list limit

# Agent Limits
DEFAULT_MAX_HISTORY_MESSAGES = 50  # Maximum messages to keep in history (default)
DIAGNOSTIC_MAX_HISTORY_MESSAGES = 100  # For diagnostic tasks with many tool calls
DEFAULT_REQUEST_LIMIT = 100  # Maximum LLM requests per run (fallback)
DEFAULT_TOOL_CALLS_LIMIT = 50  # Maximum tool calls per run (fallback)
MIN_RESPONSE_LENGTH_WITH_ACTIONS = 20  # Minimum response length when actions taken
HARD_MAX_HISTORY_MESSAGES = 200  # Absolute maximum to prevent unbounded growth

# Mode-specific tool call limits (set by router based on task type)
# IMPORTANT: These are FAILSAFE limits only - loop detection handles real safety
# The agent should complete tasks naturally; limits are just emergency stops
# Loop detection (history.py) catches unproductive behavior BEFORE these limits
TOOL_CALLS_LIMIT_DIAGNOSTIC = 200  # Allow complex investigations to complete
TOOL_CALLS_LIMIT_REMEDIATION = 100  # Allow multi-step fixes
TOOL_CALLS_LIMIT_QUERY = 50  # Allow thorough information gathering
TOOL_CALLS_LIMIT_CHAT = 20  # Simple conversations rarely need more

# Mode-specific request limits (should be >= tool_calls_limit)
REQUEST_LIMIT_DIAGNOSTIC = 300  # Headroom for complex investigation
REQUEST_LIMIT_REMEDIATION = 150  # Moderate for fix/deploy tasks
REQUEST_LIMIT_QUERY = 80  # Enough for information gathering
REQUEST_LIMIT_CHAT = 30  # Simple conversations

# Skill-specific limits (skills can involve complex multi-step operations)
REQUEST_LIMIT_SKILL = 100  # Request limit for skill execution

# Tool retry configuration
DEFAULT_TOOL_RETRIES = 3  # Allow tools to retry on ModelRetry (e.g., elevation flow)
