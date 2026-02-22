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
DEFAULT_MAX_HISTORY_MESSAGES = 50  # Reasonable conversation history
DIAGNOSTIC_MAX_HISTORY_MESSAGES = 80
DEFAULT_REQUEST_LIMIT = 100  # Per-run request ceiling
DEFAULT_TOOL_CALLS_LIMIT = 50  # Aligned with ToolCallTracker.MAX_TOTAL_CALLS_SESSION
MIN_RESPONSE_LENGTH_WITH_ACTIONS = 20  # Minimum response length when actions taken
HARD_MAX_HISTORY_MESSAGES = 200  # Absolute maximum to prevent JSON unbounded growth

# Mode-specific tool call limits
TOOL_CALLS_LIMIT_DIAGNOSTIC = 50
TOOL_CALLS_LIMIT_REMEDIATION = 50
TOOL_CALLS_LIMIT_QUERY = 20
TOOL_CALLS_LIMIT_CHAT = 30

# Mode-specific request limits (should be >= tool_calls_limit)
REQUEST_LIMIT_DIAGNOSTIC = 100
REQUEST_LIMIT_REMEDIATION = 100
REQUEST_LIMIT_QUERY = 40
REQUEST_LIMIT_CHAT = 60

# Skill-specific limits
REQUEST_LIMIT_SKILL = 100

# Tool retry configuration — 3 retries is enough for elevation/credential flows
DEFAULT_TOOL_RETRIES = 3

# LLM Request Timeouts (seconds) - per provider best practices
# These are timeouts for individual API requests, not overall agent run time
# Based on provider recommendations and real-world usage patterns
LLM_TIMEOUT_DEFAULT = 90  # Fallback for unknown providers
LLM_TIMEOUT_OPENAI = 90  # OpenAI recommends 60-120s
LLM_TIMEOUT_ANTHROPIC = 60  # Anthropic: 60s with streaming for long tasks
LLM_TIMEOUT_MISTRAL = 60  # Mistral: 60s default
LLM_TIMEOUT_GROQ = 45  # Groq: Fast inference, 30-60s
LLM_TIMEOUT_OPENROUTER = 120  # OpenRouter: Routes to many providers, needs headroom
LLM_TIMEOUT_OLLAMA = 180  # Ollama: Local inference can be slow on CPU
LLM_TIMEOUT_GOOGLE = 60  # Google/Gemini: 60s default
LLM_TIMEOUT_COHERE = 90  # Cohere: Similar to OpenAI
LLM_TIMEOUT_BEDROCK = 120  # AWS Bedrock: Network + inference time

# Provider timeout mapping (lowercase provider name -> timeout in seconds)
LLM_PROVIDER_TIMEOUTS: dict[str, int] = {
    "openai": LLM_TIMEOUT_OPENAI,
    "anthropic": LLM_TIMEOUT_ANTHROPIC,
    "mistral": LLM_TIMEOUT_MISTRAL,
    "groq": LLM_TIMEOUT_GROQ,
    "openrouter": LLM_TIMEOUT_OPENROUTER,
    "ollama": LLM_TIMEOUT_OLLAMA,
    "google": LLM_TIMEOUT_GOOGLE,
    "gemini": LLM_TIMEOUT_GOOGLE,
    "cohere": LLM_TIMEOUT_COHERE,
    "bedrock": LLM_TIMEOUT_BEDROCK,
}
