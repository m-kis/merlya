"""
Merlya Parser - Log extractor.

High-level log parsing with summarization.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.parser.service import ParserService

if TYPE_CHECKING:
    from merlya.parser.models import LogParsingResult, ParsedLog


async def extract_log_info(
    text: str,
    tier: str | None = None,
) -> tuple[ParsedLog, LogParsingResult]:
    """
    Extract structured information from log text.

    Args:
        text: Raw log text.
        tier: Optional tier override.

    Returns:
        Tuple of (ParsedLog, full result).

    Example:
        log_info, result = await extract_log_info(raw_log_output)
        print(f"Errors: {log_info.error_count}")
        print(f"Key errors: {log_info.key_errors}")
        print(f"Patterns: {log_info.patterns_detected}")
    """
    service = ParserService.get_instance(tier=tier)
    if not service.is_initialized:
        await service.initialize()

    result = await service.parse_log(text)

    logger.debug(
        f"📋 Log parsed: {result.parsed_log.error_count} errors, "
        f"{result.parsed_log.warning_count} warnings, "
        f"patterns={result.parsed_log.patterns_detected}"
    )

    return result.parsed_log, result


async def get_log_summary(text: str, max_errors: int = 5) -> str:
    """
    Get a brief summary of log content.

    Args:
        text: Raw log text.
        max_errors: Maximum number of errors to include.

    Returns:
        Human-readable summary string.
    """
    log_info, _result = await extract_log_info(text)

    summary_parts = []

    # Error/warning counts
    if log_info.error_count or log_info.warning_count:
        summary_parts.append(
            f"Found {log_info.error_count} errors, {log_info.warning_count} warnings"
        )

    # Time range
    if log_info.time_range_start and log_info.time_range_end:
        summary_parts.append(
            f"Time range: {log_info.time_range_start} to {log_info.time_range_end}"
        )

    # Patterns
    if log_info.patterns_detected:
        patterns = ", ".join(log_info.patterns_detected)
        summary_parts.append(f"Detected patterns: {patterns}")

    # Key errors
    if log_info.key_errors:
        errors = log_info.key_errors[:max_errors]
        summary_parts.append("Key errors:")
        for err in errors:
            summary_parts.append(f"  - {err[:80]}")

    return "\n".join(summary_parts) if summary_parts else "No significant log entries found"


async def has_errors(text: str) -> bool:
    """
    Quick check if log text contains errors.

    Args:
        text: Log text to check.

    Returns:
        True if errors were found.
    """
    log_info, _ = await extract_log_info(text)
    return log_info.error_count > 0
