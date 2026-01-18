"""
Task completion detection for the orchestrator.

Contains heuristics for determining if a specialist task appears complete.
"""

from __future__ import annotations

import re


def task_seems_complete(output: str) -> bool:
    """
    Heuristic to check if a task appears complete.

    Args:
        output: Specialist output.

    Returns:
        True if task seems complete.
    """
    if not output:
        return False

    # Check for completion indicators
    completion_patterns = [
        r"\b(done|complete|finished|fixed|resolved|success)\b",
        r"\b(resolu|termine|corrige|succes)\b",
    ]

    for pattern in completion_patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return True

    # Check for incompletion indicators
    incomplete_patterns = [
        r"\b(incomplete|partial|pending|todo|still need)\b",
        r"\b(incomplet|en cours|a faire)\b",
    ]

    for pattern in incomplete_patterns:
        if re.search(pattern, output, re.IGNORECASE):
            return False

    # Default: assume complete if output is substantial
    return len(output) > 100
