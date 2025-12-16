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
        Perform a web search using DuckDuckGo.

        Use this tool to search the web for documentation, error messages,
        or other information not available locally.

        Args:
            query: Search query string (e.g., "nginx 502 bad gateway fix").
            max_results: Maximum results to return (1-10, default: 5).
            region: Region code for localized results (e.g., "fr-fr", "us-en").
            safesearch: Content filter: "off", "moderate" (default), or "strict".

        Returns:
            Search results with titles, URLs, and snippets.
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
        # Only retry on rate limiting - network errors aren't recoverable by retrying
        error_msg = getattr(result, "error", "") or ""
        if "rate limit" in error_msg.lower():
            raise ModelRetry("Rate limited. Try a different query or wait.")
        return {"error": error_msg or "Web search failed", "results": []}


__all__ = ["register_web_tools"]
