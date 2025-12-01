"""
Web Search Engine for Merlya.

Uses DuckDuckGo for free web searches to:
- Find solutions to infrastructure problems
- Look up documentation
- Research error messages
- Stay updated on security advisories
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from merlya.utils.logger import logger

try:
    from duckduckgo_search import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False
    logger.warning("duckduckgo_search not installed. Run: pip install duckduckgo_search")


@dataclass
class SearchResult:
    """A search result."""
    title: str
    url: str
    snippet: str
    source: str = ""  # Domain of the result
    timestamp: str = ""


@dataclass
class SearchResponse:
    """Response from a search query."""
    query: str
    results: List[SearchResult] = field(default_factory=list)
    total_results: int = 0
    search_time_ms: int = 0
    cached: bool = False
    error: Optional[str] = None


class WebSearchEngine:
    """
    Web search engine using DuckDuckGo.

    Features:
    - Text search with caching
    - Infrastructure-specific query templates
    - Result filtering and ranking
    - Rate limiting to avoid blocks
    """

    def __init__(
        self,
        cache_ttl_hours: int = 24,
        max_results: int = 10,
        region: str = "wt-wt",  # Worldwide
        safesearch: str = "moderate",
    ):
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.max_results = max_results
        self.region = region
        self.safesearch = safesearch
        self._cache: Dict[str, Dict] = {}  # query_hash -> {results, timestamp}
        self._last_search_time: Optional[datetime] = None
        self._min_delay_seconds = 1.0  # Rate limiting

    def _get_cache_key(self, query: str) -> str:
        """Generate cache key for a query."""
        return hashlib.md5(query.lower().encode()).hexdigest()

    def _is_cache_valid(self, key: str) -> bool:
        """Check if cache entry is valid."""
        if key not in self._cache:
            return False
        entry = self._cache[key]
        return datetime.now() - entry["timestamp"] < self.cache_ttl

    def _apply_rate_limit(self):
        """Apply rate limiting between searches."""
        import time
        if self._last_search_time:
            elapsed = (datetime.now() - self._last_search_time).total_seconds()
            if elapsed < self._min_delay_seconds:
                time.sleep(self._min_delay_seconds - elapsed)
        self._last_search_time = datetime.now()

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        time_range: Optional[str] = None,  # d=day, w=week, m=month, y=year
    ) -> SearchResponse:
        """
        Perform a web search.

        Args:
            query: Search query string
            max_results: Maximum number of results (default: self.max_results)
            time_range: Time filter (d, w, m, y or None for all time)

        Returns:
            SearchResponse with results
        """
        if not HAS_DDGS:
            return SearchResponse(
                query=query,
                error="duckduckgo_search not installed",
            )

        max_results = max_results or self.max_results
        cache_key = self._get_cache_key(f"{query}:{time_range}")

        # Check cache
        if self._is_cache_valid(cache_key):
            cached = self._cache[cache_key]
            logger.debug(f"Search cache hit: {query[:50]}")
            return SearchResponse(
                query=query,
                results=cached["results"],
                total_results=len(cached["results"]),
                cached=True,
            )

        # Apply rate limiting
        self._apply_rate_limit()

        # Perform search
        start_time = datetime.now()
        results = []

        try:
            with DDGS() as ddgs:
                search_results = ddgs.text(
                    query,
                    region=self.region,
                    safesearch=self.safesearch,
                    timelimit=time_range,
                    max_results=max_results,
                )

                for r in search_results:
                    # Extract domain from URL
                    source = ""
                    if r.get("href"):
                        match = re.match(r"https?://([^/]+)", r["href"])
                        if match:
                            source = match.group(1)

                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                        source=source,
                    ))

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return SearchResponse(
                query=query,
                error=str(e),
            )

        search_time = int((datetime.now() - start_time).total_seconds() * 1000)

        # Cache results
        self._cache[cache_key] = {
            "results": results,
            "timestamp": datetime.now(),
        }

        return SearchResponse(
            query=query,
            results=results,
            total_results=len(results),
            search_time_ms=search_time,
        )

    def search_error(self, error_message: str, service: Optional[str] = None) -> SearchResponse:
        """
        Search for solutions to an error message.

        Args:
            error_message: The error message to search for
            service: Optional service context (nginx, mongodb, etc.)

        Returns:
            SearchResponse with results
        """
        # Clean and format the error message
        clean_error = self._clean_error_message(error_message)

        # Build query
        query_parts = [clean_error]
        if service:
            query_parts.insert(0, service)
        query_parts.append("solution")

        query = " ".join(query_parts)

        return self.search(query)

    def search_documentation(
        self,
        topic: str,
        service: Optional[str] = None,
        version: Optional[str] = None,
    ) -> SearchResponse:
        """
        Search for documentation.

        Args:
            topic: Documentation topic
            service: Service name (nginx, mongodb, etc.)
            version: Optional version number

        Returns:
            SearchResponse with results
        """
        query_parts = []
        if service:
            query_parts.append(service)
        if version:
            query_parts.append(version)
        query_parts.append(topic)
        query_parts.append("documentation")

        query = " ".join(query_parts)

        # Prefer official documentation sites
        return self.search(f"{query} site:docs OR site:readthedocs OR site:github")

    def search_security(
        self,
        topic: str,
        cve_id: Optional[str] = None,
    ) -> SearchResponse:
        """
        Search for security information.

        Args:
            topic: Security topic or vulnerability
            cve_id: Optional CVE ID

        Returns:
            SearchResponse with results
        """
        if cve_id:
            query = f"{cve_id} vulnerability exploit mitigation"
        else:
            query = f"{topic} security vulnerability advisory"

        return self.search(query, time_range="m")  # Last month

    def search_troubleshooting(
        self,
        symptoms: List[str],
        service: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> SearchResponse:
        """
        Search for troubleshooting guides based on symptoms.

        Args:
            symptoms: List of observed symptoms
            service: Optional service context
            environment: Optional environment (linux, docker, kubernetes)

        Returns:
            SearchResponse with results
        """
        query_parts = []

        if service:
            query_parts.append(service)
        if environment:
            query_parts.append(environment)

        # Add symptoms (limit to 3)
        query_parts.extend(symptoms[:3])
        query_parts.append("troubleshooting")

        query = " ".join(query_parts)

        return self.search(query)

    def _clean_error_message(self, error: str) -> str:
        """Clean an error message for searching."""
        # Remove timestamps
        error = re.sub(r'\d{4}[-/]\d{2}[-/]\d{2}', '', error)
        error = re.sub(r'\d{2}:\d{2}:\d{2}', '', error)

        # Remove file paths (but keep filename)
        error = re.sub(r'/[\w/.-]+/(\w+\.\w+)', r'\1', error)

        # Remove hex addresses
        error = re.sub(r'0x[0-9a-fA-F]+', '', error)

        # Remove IPs (but keep the error context)
        error = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', 'IP_ADDRESS', error)

        # Remove UUIDs
        error = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '', error)

        # Remove excessive whitespace
        error = re.sub(r'\s+', ' ', error).strip()

        # Truncate if too long
        if len(error) > 200:
            error = error[:200]

        return error

    def get_relevant_results(
        self,
        response: SearchResponse,
        prefer_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """
        Filter and rank search results by relevance.

        Args:
            response: SearchResponse to filter
            prefer_domains: Domains to prioritize
            exclude_domains: Domains to exclude

        Returns:
            Filtered and ranked list of SearchResult
        """
        if not response.results:
            return []

        # Default preferred domains for infrastructure
        prefer_domains = prefer_domains or [
            "stackoverflow.com",
            "github.com",
            "serverfault.com",
            "digitalocean.com",
            "aws.amazon.com",
            "docs.",
            "wiki.",
            "readthedocs.io",
        ]

        exclude_domains = exclude_domains or [
            "pinterest.com",
            "facebook.com",
            "twitter.com",
            "instagram.com",
        ]

        # Score and filter results
        scored_results = []
        for result in response.results:
            # Skip excluded domains
            if any(d in result.source for d in exclude_domains):
                continue

            score = 0

            # Prefer certain domains
            for domain in prefer_domains:
                if domain in result.source:
                    score += 10
                    break

            # Prefer results with longer snippets (more info)
            score += int(min(len(result.snippet) / 50, 5))

            # Prefer results with relevant keywords in title
            relevant_keywords = ["how to", "fix", "solve", "error", "guide", "tutorial"]
            title_lower = result.title.lower()
            for kw in relevant_keywords:
                if kw in title_lower:
                    score += 2

            scored_results.append((score, result))

        # Sort by score
        scored_results.sort(key=lambda x: x[0], reverse=True)

        return [r for _, r in scored_results]

    def format_results_markdown(self, response: SearchResponse, max_results: int = 5) -> str:
        """
        Format search results as markdown.

        Args:
            response: SearchResponse to format
            max_results: Maximum results to include

        Returns:
            Markdown formatted string
        """
        if response.error:
            return f"**Search Error:** {response.error}"

        if not response.results:
            return f"No results found for: {response.query}"

        lines = [f"**Search Results for:** {response.query}\n"]

        for i, result in enumerate(response.results[:max_results], 1):
            lines.append(f"### {i}. [{result.title}]({result.url})")
            lines.append(f"*{result.source}*")
            lines.append(f"{result.snippet}")
            lines.append("")

        if response.cached:
            lines.append("*Results from cache*")
        else:
            lines.append(f"*Search completed in {response.search_time_ms}ms*")

        return "\n".join(lines)

    def clear_cache(self):
        """Clear the search cache."""
        self._cache.clear()
        logger.debug("Web search cache cleared")


# Singleton instance
_default_engine: Optional[WebSearchEngine] = None


def get_web_search_engine() -> WebSearchEngine:
    """Get the default WebSearchEngine instance."""
    global _default_engine

    if _default_engine is None:
        _default_engine = WebSearchEngine()

    return _default_engine
