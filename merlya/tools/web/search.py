"""
Merlya Tools - Web search (DuckDuckGo via ddgs).

Provides a fast, cached search tool for the agent.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.tools.core import ToolResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Cache tuning (kept small to avoid memory bloat)
CACHE_TTL_SECONDS = 60
CACHE_MAX_ENTRIES = 32

_cache: OrderedDict[str, tuple[float, list[dict[str, str]]]] = OrderedDict()


@dataclass
class WebResult:
    """Structured web search result."""

    title: str
    url: str
    snippet: str
    source: str
    rank: int


def _cache_key(query: str, max_results: int, region: str | None, safesearch: str) -> str:
    """Build a stable cache key."""
    return "|".join(
        [
            query.strip().lower(),
            str(max_results),
            region or "",
            safesearch,
        ]
    )


def _get_cache(key: str) -> list[dict[str, str]] | None:
    """Return cached results if still valid."""
    now = time.time()
    if key in _cache:
        ts, data = _cache[key]
        if now - ts <= CACHE_TTL_SECONDS:
            _cache.move_to_end(key)
            return data
        _cache.pop(key, None)
    return None


def _set_cache(key: str, results: list[dict[str, str]]) -> None:
    """Store results in cache with eviction."""
    _cache[key] = (time.time(), results)
    _cache.move_to_end(key)
    if len(_cache) > CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


def _sanitize_snippet(text: str) -> str:
    """Normalize snippet text for display."""
    cleaned = " ".join(text.split())
    if len(cleaned) > 400:
        cleaned = cleaned[:397] + "..."
    return cleaned


def _coerce_result(item: dict[str, Any], rank: int) -> dict[str, str]:
    """Normalize ddgs result fields."""
    title = str(item.get("title") or "").strip()
    url = str(item.get("href") or item.get("url") or "").strip()
    snippet_raw = str(
        item.get("body") or item.get("snippet") or item.get("description") or ""
    ).strip()
    snippet = _sanitize_snippet(snippet_raw)

    return {
        "title": title or "(no title)",
        "url": url,
        "snippet": snippet,
        "source": "duckduckgo",
        "rank": str(rank),
    }


def _load_ddgs() -> Any:
    """Import ddgs client (isolated for testability)."""
    from ddgs import DDGS

    return DDGS


def _run_search_sync(
    query: str,
    max_results: int,
    region: str | None,
    safesearch: str,
) -> list[dict[str, str]]:
    """Run ddgs search in a sync context (to be offloaded to a thread)."""
    DDGS = _load_ddgs()

    results: list[dict[str, str]] = []
    with DDGS() as client:
        for idx, item in enumerate(
            client.text(query, max_results=max_results, region=region, safesearch=safesearch),
            start=1,
        ):
            try:
                results.append(_coerce_result(item, idx))
            except Exception as e:  # pragma: no cover - defensive
                logger.debug(f"Skipping malformed search result: {e}")
                continue

    return results


async def search_web(
    ctx: SharedContext,
    query: str,
    max_results: int = 5,
    region: str | None = None,
    safesearch: str = "moderate",
    timeout: float = 8.0,
) -> ToolResult:
    """
    Perform a web search using DuckDuckGo (ddgs).

    Args:
        ctx: Shared context (unused for now, kept for future auth/config).
        query: Search query.
        max_results: Maximum results to return (1-10).
        region: Optional region code (e.g., "fr-fr", "us-en").
        safesearch: DDG safesearch level ("off", "moderate", "strict").
        timeout: Max time (seconds) before giving up.

    Returns:
        ToolResult with normalized results.
    """
    _ = ctx  # reserved for future use
    q = (query or "").strip()
    if not q:
        return ToolResult(success=False, data=[], error="Empty query")

    max_results = max(1, min(max_results, 10))
    safesearch = safesearch or "moderate"

    key = _cache_key(q, max_results, region, safesearch)
    cached = _get_cache(key)
    if cached is not None:
        logger.debug("🔍 Returning cached web search results")
        return ToolResult(
            success=True,
            data={"results": cached, "count": len(cached), "cached": True},
        )

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(_run_search_sync, q, max_results, region, safesearch),
            timeout=timeout,
        )
    except ImportError:
        return ToolResult(
            success=False,
            data=[],
            error="ddgs not installed. Install with `pip install ddgs`.",
        )
    except TimeoutError:
        return ToolResult(success=False, data=[], error="Web search timed out")
    except Exception as e:
        logger.warning(f"⚠️ Web search failed: {e}")
        return ToolResult(success=False, data=[], error=str(e))

    _set_cache(key, results)

    logger.debug(f"🔍 Web search completed ({len(results)} results)")
    return ToolResult(
        success=True, data={"results": results, "count": len(results), "cached": False}
    )
