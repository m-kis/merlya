"""
Merlya Agent - Common tool utilities.

Shared helpers for tool registration modules.
"""

from __future__ import annotations


def check_recoverable_error(error: str | None) -> bool:
    """
    Check if error is recoverable (model can retry with different args).

    Recoverable errors are those where the model made a wrong choice
    (e.g., wrong hostname, wrong path) and can fix it by trying again
    with different arguments.

    Non-recoverable errors are infrastructure issues (network, permissions)
    that won't be fixed by retrying with different args.

    Args:
        error: Error message to check, or None.

    Returns:
        True if the error is recoverable, False otherwise.
    """
    if not error:
        return False
    lower = error.lower()
    return any(
        pattern in lower
        for pattern in (
            "not found",
            "does not exist",
            "no such file",
            "no such host",
            "unknown host",
        )
    )


__all__ = ["check_recoverable_error"]
