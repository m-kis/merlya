"""
Web tools (search, fetch).
"""
from typing import Annotated

from athena_ai.utils.logger import logger


def web_search(
    query: Annotated[str, "Search query"]
) -> str:
    """
    Search the web using DuckDuckGo.

    Args:
        query: Search query

    Returns:
        Search results
    """
    logger.info(f"Tool: web_search '{query}'")

    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))

        if not results:
            return "❌ No results found."

        summary = [f"🔍 Results for '{query}':", ""]
        for i, res in enumerate(results, 1):
            summary.append(f"{i}. {res['title']}")
            summary.append(f"   {res['body']}")
            summary.append(f"   Source: {res['href']}")
            summary.append("")

        return "\n".join(summary)

    except ImportError:
        return "❌ duckduckgo-search not installed."
    except Exception as e:
        return f"❌ Search failed: {e}"


def web_fetch(
    url: Annotated[str, "URL to fetch"]
) -> str:
    """
    Fetch content from a URL.

    Args:
        url: URL to fetch

    Returns:
        Page content (text only)
    """
    logger.info(f"Tool: web_fetch {url}")

    try:
        import requests
        from bs4 import BeautifulSoup

        headers = {'User-Agent': 'Athena/0.2.0 (AI Assistant)'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        for script in soup(["script", "style"]):
            script.extract()

        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)

        if len(text) > 5000:
            text = text[:5000] + "\n...(truncated)"

        return f"✅ Content of {url}:\n\n{text}"

    except Exception as e:
        return f"❌ Fetch failed: {e}"
