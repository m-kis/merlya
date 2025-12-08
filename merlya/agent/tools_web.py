"""
Merlya Agent - Web tool registration.

Registers web search tools (DuckDuckGo via ddgs).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from pydantic_ai import Agent, ModelRetry, RunContext

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any  # type: ignore


def register_web_tools(agent: Agent[Any, Any]) -> None:
    """Register web search tools with the agent."""

    @agent.tool
    async def search_web(
        ctx: RunContext[AgentDependencies],
        query: str,
        max_results: int = 5,
        region: str | None = None,
        safesearch: str = "moderate",
    ) -> dict[str, Any]:
        """
        Perform a web search (DuckDuckGo via ddgs).

        Args:
            ctx: Run context.
            query: Search query string.
            max_results: Maximum results (1-10).
            region: Optional region code (e.g., "fr-fr", "us-en").
            safesearch: DDG safesearch level ("off", "moderate", "strict").

        Returns:
            Dictionary with results, count, and cache flag.
        """
        from merlya.tools.web import search_web as _search_web

        result = await _search_web(
            ctx.deps.context,
            query=query,
            max_results=max_results,
            region=region,
            safesearch=safesearch,
        )
        if result.success:
            return cast("dict[str, Any]", result.data)
        raise ModelRetry(f"Web search failed: {getattr(result, 'error', 'unknown error')}")
