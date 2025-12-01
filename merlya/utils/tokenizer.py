"""
Token counting utilities for Merlya.

Provides accurate token counting with tiktoken when available,
falling back to a reasonable approximation otherwise.
"""
from typing import Optional

from merlya.utils.logger import logger

# Try to import tiktoken for accurate token counting
_tiktoken_available = False
_encoder = None

try:
    import tiktoken
    _tiktoken_available = True
except ImportError:
    pass


def _get_encoder():
    """Get or create the tiktoken encoder (lazy initialization)."""
    global _encoder
    if _encoder is None and _tiktoken_available:
        try:
            # Use cl100k_base which is used by GPT-4 and Claude
            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.debug(f"Failed to load tiktoken encoder: {e}")
    return _encoder


def count_tokens(text: str, model: Optional[str] = None) -> int:
    """Count tokens in text.

    Uses tiktoken for accurate counting when available,
    falls back to character-based approximation otherwise.

    Args:
        text: Text to count tokens for.
        model: Optional model name (for future model-specific encoding).

    Returns:
        Estimated token count.
    """
    if not text:
        return 0

    encoder = _get_encoder()
    if encoder:
        try:
            return len(encoder.encode(text))
        except Exception:
            pass

    # Fallback: approximate tokens
    # Average is ~4 characters per token for English text
    # But code and special characters can be more tokens per char
    return _approximate_tokens(text)


def _approximate_tokens(text: str) -> int:
    """Approximate token count without tiktoken.

    Uses heuristics based on text characteristics:
    - English text: ~4 chars per token
    - Code: ~3 chars per token (more special chars)
    - Mixed: ~3.5 chars per token
    """
    if not text:
        return 0

    # Count special characters and code-like patterns
    special_chars = sum(1 for c in text if not c.isalnum() and not c.isspace())
    code_indicators = text.count('```') + text.count('def ') + text.count('class ')
    code_indicators += text.count('{') + text.count('}') + text.count(';')

    # Determine chars per token based on content type
    total_chars = len(text)
    special_ratio = special_chars / max(total_chars, 1)

    if code_indicators > 5 or special_ratio > 0.15:
        # Likely code - use lower ratio
        chars_per_token = 3.0
    elif special_ratio > 0.05:
        # Mixed content
        chars_per_token = 3.5
    else:
        # Mostly natural language
        chars_per_token = 4.0

    return max(1, int(total_chars / chars_per_token))


def count_message_tokens(messages: list) -> int:
    """Count tokens for a list of chat messages.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.

    Returns:
        Total token count including message overhead.
    """
    total = 0

    for msg in messages:
        content = msg.get("content", "")

        # Count content tokens
        total += count_tokens(content)

        # Add overhead for message structure (~4 tokens per message)
        total += 4

        # Role names add ~1 token
        total += 1

    # Add overhead for conversation structure (~3 tokens)
    total += 3

    return total


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token limit.

    Args:
        text: Text to truncate.
        max_tokens: Maximum tokens allowed.

    Returns:
        Truncated text that fits within the limit.
    """
    if not text:
        return text

    current_tokens = count_tokens(text)
    if current_tokens <= max_tokens:
        return text

    # Binary search for the right length
    low, high = 0, len(text)
    result = ""

    while low < high:
        mid = (low + high + 1) // 2
        candidate = text[:mid]
        if count_tokens(candidate) <= max_tokens:
            result = candidate
            low = mid
        else:
            high = mid - 1

    # Try to truncate at a word boundary
    if result and not result[-1].isspace():
        last_space = result.rfind(' ')
        if last_space > len(result) * 0.8:  # Only if not losing too much
            result = result[:last_space]

    return result


def is_tiktoken_available() -> bool:
    """Check if tiktoken is available for accurate token counting."""
    return _tiktoken_available


def get_token_info() -> dict:
    """Get information about the token counting implementation."""
    return {
        "tiktoken_available": _tiktoken_available,
        "encoding": "cl100k_base" if _tiktoken_available else "approximation",
        "accuracy": "exact" if _tiktoken_available else "approximate (~85%)",
    }
