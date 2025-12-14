"""
Merlya Health - Connectivity checks module.

Provides network connectivity health checks (LLM providers, web search).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from merlya.core.types import CheckStatus, HealthCheck
from merlya.i18n import t


async def check_llm_provider(api_key: str | None = None, timeout: float = 10.0) -> HealthCheck:
    """
    Check LLM provider accessibility with real connectivity test.

    Args:
        api_key: API key to use (optional, will be auto-discovered).
        timeout: Timeout for the connectivity test.

    Returns:
        HealthCheck result.
    """
    from merlya.config import get_config
    from merlya.secrets import get_secret

    config = get_config()
    provider = config.model.provider
    model = config.model.model

    # Check if API key is configured
    if not api_key:
        key_env = config.model.api_key_env or f"{provider.upper()}_API_KEY"
        api_key = os.getenv(key_env) or get_secret(key_env)

    # Ollama doesn't need API key
    if not api_key and provider != "ollama":
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.ERROR,
            message=t("health.llm.error"),
            critical=True,
            details={"provider": provider, "error": "No API key configured"},
        )

    # Perform real connectivity test
    try:
        time.time()

        # Provider-specific connectivity checks
        if provider == "openai":
            latency = await _ping_openai(api_key, timeout)
        elif provider == "anthropic":
            latency = await _ping_anthropic(api_key, timeout)
        elif provider == "openrouter":
            latency = await _ping_openrouter(api_key, timeout)
        elif provider == "ollama":
            latency = await _ping_ollama(timeout)
        elif provider == "litellm":
            latency = await _ping_litellm(api_key, timeout)
        else:
            # Generic check - try to use pydantic_ai
            latency = await _ping_generic(provider, model, timeout)

        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.OK,
            message=t("health.llm.ok", provider=provider) + f" ({latency:.0f}ms)",
            details={
                "provider": provider,
                "model": model,
                "latency_ms": latency,
            },
        )

    except TimeoutError:
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.WARNING,
            message=t("health.llm.warning", error=f"timeout ({timeout}s)"),
            details={"provider": provider, "error": "timeout"},
        )
    except Exception as e:
        error_msg = str(e)
        # Check for common errors
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            return HealthCheck(
                name="llm_provider",
                status=CheckStatus.ERROR,
                message=t("health.llm.invalid_api_key"),
                critical=True,
                details={"provider": provider, "error": "invalid_api_key"},
            )
        elif "429" in error_msg or "rate" in error_msg.lower():
            return HealthCheck(
                name="llm_provider",
                status=CheckStatus.WARNING,
                message=t("health.llm.rate_limited"),
                details={"provider": provider, "error": "rate_limited"},
            )
        else:
            return HealthCheck(
                name="llm_provider",
                status=CheckStatus.WARNING,
                message=t("health.llm.warning", error=error_msg[:50]),
                details={"provider": provider, "error": error_msg},
            )


async def _ping_google(timeout: float) -> float:
    """Ping Google for general connectivity test."""
    import httpx

    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get("https://www.google.com", timeout=timeout)
        response.raise_for_status()
    return (time.time() - start) * 1000


async def _ping_openai(api_key: str | None, timeout: float) -> float:
    """Ping OpenAI API."""
    import httpx

    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
    return (time.time() - start) * 1000


async def _ping_anthropic(api_key: str | None, timeout: float) -> float:
    """Ping Anthropic API."""
    import httpx

    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Anthropic doesn't have a lightweight endpoint, use models list
        response = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key or "",
                "anthropic-version": "2023-06-01",
            },
        )
        # 200 or 404 both mean the API is reachable
        if response.status_code not in (200, 404):
            response.raise_for_status()
    return (time.time() - start) * 1000


async def _ping_openrouter(api_key: str | None, timeout: float) -> float:
    """Ping OpenRouter API."""
    import httpx

    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
    return (time.time() - start) * 1000


async def _ping_ollama(timeout: float) -> float:
    """Ping Ollama local server."""
    import httpx

    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get("http://localhost:11434/api/tags")
        response.raise_for_status()
    return (time.time() - start) * 1000


async def _ping_claude(api_key: str | None, timeout: float) -> float:
    """Ping Claude API (Anthropic)."""
    return await _ping_anthropic(api_key, timeout)


async def _ping_litellm(api_key: str | None, timeout: float) -> float:
    """Ping LiteLLM proxy."""
    import httpx

    # LiteLLM can proxy to various providers, try common endpoints
    start = time.time()
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Try local proxy first
        try:
            response = await client.get("http://localhost:4000/health")
            if response.status_code == 200:
                return (time.time() - start) * 1000
        except Exception:
            pass

        # Fall back to OpenAI-compatible endpoint
        response = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
    return (time.time() - start) * 1000


async def _ping_generic(provider: str, model: str, timeout: float) -> float:
    """Generic ping using pydantic_ai."""
    from pydantic_ai import Agent

    start = time.time()

    agent = Agent(
        f"{provider}:{model}",
        system_prompt="Reply with exactly one word: OK",
    )

    # Run with timeout
    result = await asyncio.wait_for(
        agent.run("ping"),
        timeout=timeout,
    )

    # Check response is valid
    if not getattr(result, "data", None):
        raise ValueError("Empty response from LLM")

    return (time.time() - start) * 1000


# Public aliases for backward compatibility
ping_google = _ping_google
ping_openai = _ping_openai
ping_ollama = _ping_ollama
ping_claude = _ping_claude
ping_generic = _ping_generic


async def check_web_search(timeout: float = 10.0) -> HealthCheck:
    """
    Check DuckDuckGo search availability with real connectivity test.

    Args:
        timeout: Timeout for the connectivity test.

    Returns:
        HealthCheck result.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return HealthCheck(
            name="web_search",
            status=CheckStatus.DISABLED,
            message=t("health.web_search.disabled"),
            details={"error": "ddgs_not_installed"},
        )

    try:
        start = time.time()

        # Perform a real search query to verify connectivity
        def _do_search() -> list[dict[str, Any]]:
            with DDGS() as ddgs:
                # Simple query that should always return results
                return list(ddgs.text("test", max_results=1))

        # Run in thread pool with timeout to avoid blocking
        results = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _do_search),
            timeout=timeout,
        )

        latency = (time.time() - start) * 1000

        if results:
            return HealthCheck(
                name="web_search",
                status=CheckStatus.OK,
                message=t("health.web_search.ok") + f" ({latency:.0f}ms)",
                details={"latency_ms": latency, "results_count": len(results)},
            )
        else:
            return HealthCheck(
                name="web_search",
                status=CheckStatus.WARNING,
                message=t("health.web_search.warning", error="no results"),
                details={"latency_ms": latency, "results_count": 0},
            )

    except TimeoutError:
        return HealthCheck(
            name="web_search",
            status=CheckStatus.WARNING,
            message=t("health.web_search.warning", error=f"timeout ({timeout}s)"),
            details={"error": "timeout"},
        )
    except Exception as e:
        error_msg = str(e)
        # Check for rate limiting
        if "429" in error_msg or "rate" in error_msg.lower():
            return HealthCheck(
                name="web_search",
                status=CheckStatus.WARNING,
                message=t("health.web_search.warning", error="rate limited"),
                details={"error": "rate_limited"},
            )
        return HealthCheck(
            name="web_search",
            status=CheckStatus.WARNING,
            message=t("health.web_search.warning", error=error_msg[:50]),
            details={"error": error_msg},
        )
