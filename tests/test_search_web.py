import pytest

import merlya.tools.web.search as web_search
from merlya.tools.web import search_web


class DummyCtx:
    """Minimal context stub (web search does not use context yet)."""

    pass


class FakeDDGS:
    """Fake ddgs client for testing."""

    def __enter__(self) -> "FakeDDGS":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def text(
        self,
        query: str,
        max_results: int,
        region: str | None,
        safesearch: str,
    ):
        yield {
            "title": f"Result for {query}",
            "href": "https://example.com",
            "body": "Example snippet content.",
        }


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Ensure cache isolation between tests."""
    web_search._cache.clear()
    yield
    web_search._cache.clear()


@pytest.mark.asyncio
async def test_search_web_success_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should return results and hit cache on second call."""
    monkeypatch.setattr(web_search, "_load_ddgs", lambda: FakeDDGS)

    ctx = DummyCtx()
    first = await search_web(ctx, "test query", max_results=3)
    assert first.success is True
    assert first.data["count"] == 1
    assert first.data["cached"] is False

    second = await search_web(ctx, "test query", max_results=3)
    assert second.success is True
    assert second.data["cached"] is True


@pytest.mark.asyncio
async def test_search_web_handles_missing_ddgs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should fail gracefully when ddgs is not installed."""

    def _raise_import_error() -> None:
        raise ImportError("ddgs missing")

    monkeypatch.setattr(web_search, "_load_ddgs", _raise_import_error)

    result = await search_web(DummyCtx(), "need search")
    assert result.success is False
    assert "ddgs" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_search_web_rejects_empty_query() -> None:
    """Should reject empty queries."""
    result = await search_web(DummyCtx(), "   ")
    assert result.success is False
    assert result.error == "Empty query"
