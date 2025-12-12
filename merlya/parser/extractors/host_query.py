"""
Merlya Parser - Host query extractor.

High-level host query extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.parser.service import ParserService

if TYPE_CHECKING:
    from merlya.parser.models import HostQueryInput, HostQueryParsingResult


async def extract_host_query(
    text: str,
    tier: str | None = None,
) -> tuple[HostQueryInput, HostQueryParsingResult]:
    """
    Extract host query information from text.

    Args:
        text: Raw query text.
        tier: Optional tier override.

    Returns:
        Tuple of (HostQueryInput, full result).

    Example:
        query, result = await extract_host_query("list all hosts with tag=web")
        print(f"Type: {query.query_type}")  # 'list'
        print(f"Filters: {query.filters}")  # {'tags': ['web']}
    """
    service = ParserService.get_instance(tier=tier)
    if not service.is_initialized:
        await service.initialize()

    result = await service.parse_host_query(text)

    logger.debug(
        f"🖥️ Host query extracted: type={result.query.query_type}, "
        f"hosts={result.query.target_hosts}, filters={result.query.filters}"
    )

    return result.query, result


def is_host_query(text: str) -> bool:
    """
    Quick check if text appears to be a host query.

    Args:
        text: Text to check.

    Returns:
        True if text looks like a host query.
    """
    keywords = [
        "host",
        "hosts",
        "server",
        "servers",
        "machine",
        "machines",
        "list",
        "show",
        "get",
        "find",
        "search",
        "inventory",
        "fleet",
    ]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
