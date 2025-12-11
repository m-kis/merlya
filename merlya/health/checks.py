"""
Merlya Health - Health check implementations.

Checks system capabilities at startup with real connectivity tests.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil
from loguru import logger

from merlya.core.types import CheckStatus, HealthCheck
from merlya.i18n import t
from merlya.parser.service import ParserService
from merlya.router.intent_classifier import IntentClassifier
from merlya.session.manager import SessionManager
from merlya.skills.registry import get_registry as get_skills_registry


@dataclass
class StartupHealth:
    """Results of all startup health checks."""

    checks: list[HealthCheck] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    model_tier: str | None = None

    @property
    def can_start(self) -> bool:
        """Check if all critical checks passed."""
        return not any(c.critical and c.status == CheckStatus.ERROR for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        """Check if any warnings were raised."""
        return any(c.status == CheckStatus.WARNING for c in self.checks)

    def get_check(self, name: str) -> HealthCheck | None:
        """Get check by name."""
        for check in self.checks:
            if check.name == name:
                return check
        return None


def check_ram() -> tuple[HealthCheck, str]:
    """
    Check available RAM and determine model tier.

    Returns:
        Tuple of (HealthCheck, tier name).
    """
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024**3)

    if available_gb >= 4.0:
        tier = "performance"
        status = CheckStatus.OK
    elif available_gb >= 2.0:
        tier = "balanced"
        status = CheckStatus.OK
    elif available_gb >= 0.5:
        tier = "lightweight"
        status = CheckStatus.WARNING
    else:
        tier = "llm_fallback"
        status = CheckStatus.WARNING

    message_key = "health.ram.ok" if status == CheckStatus.OK else "health.ram.warning"
    message = t(message_key, available=f"{available_gb:.1f}", tier=tier)

    return (
        HealthCheck(
            name="ram",
            status=status,
            message=message,
            details={"available_gb": available_gb, "tier": tier},
        ),
        tier,
    )


def check_disk_space(min_mb: int = 500) -> HealthCheck:
    """Check available disk space."""
    merlya_dir = Path.home() / ".merlya"
    merlya_dir.mkdir(parents=True, exist_ok=True)

    _total, _used, free = shutil.disk_usage(merlya_dir)
    free_mb = free // (1024 * 1024)

    if free_mb >= min_mb:
        status = CheckStatus.OK
        message = t("health.disk.ok", free=free_mb)
    elif free_mb >= 100:
        status = CheckStatus.WARNING
        message = t("health.disk.warning", free=free_mb)
    else:
        status = CheckStatus.ERROR
        message = t("health.disk.error", free=free_mb)

    return HealthCheck(
        name="disk_space",
        status=status,
        message=message,
        details={"free_mb": free_mb},
    )


async def check_llm_provider(api_key: str | None = None, timeout: float = 10.0) -> HealthCheck:
    """
    Check LLM provider accessibility with real connectivity test.

    Args:
        api_key: API key to use (optional, will be auto-discovered).
        timeout: Timeout for the connectivity test.

    Returns:
        HealthCheck result.
    """
    import os

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
                message="❌ Invalid API key",
                critical=True,
                details={"provider": provider, "error": "invalid_api_key"},
            )
        elif "429" in error_msg or "rate" in error_msg.lower():
            return HealthCheck(
                name="llm_provider",
                status=CheckStatus.WARNING,
                message="⚠️ Rate limited - will retry",
                details={"provider": provider, "error": "rate_limited"},
            )
        else:
            return HealthCheck(
                name="llm_provider",
                status=CheckStatus.WARNING,
                message=t("health.llm.warning", error=error_msg[:50]),
                details={"provider": provider, "error": error_msg},
            )


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


def check_ssh_available() -> HealthCheck:
    """Check SSH availability."""
    details: dict[str, Any] = {}

    # Check asyncssh
    try:
        import asyncssh

        details["asyncssh"] = True
        details["asyncssh_version"] = asyncssh.__version__
    except ImportError:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.DISABLED,
            message=t("health.ssh.disabled"),
            details={"asyncssh": False},
        )

    # Check system SSH client
    ssh_path = shutil.which("ssh")
    details["ssh_client"] = ssh_path is not None
    details["ssh_path"] = ssh_path

    # Check for SSH key
    ssh_key_paths = [
        Path.home() / ".ssh" / "id_rsa",
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_ecdsa",
    ]
    has_key = any(p.exists() for p in ssh_key_paths)
    details["has_ssh_key"] = has_key

    if ssh_path:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.OK,
            message=t("health.ssh.ok"),
            details=details,
        )
    else:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.WARNING,
            message=t("health.ssh.warning"),
            details=details,
        )


def check_keyring() -> HealthCheck:
    """Check keyring accessibility with real write/read test."""
    try:
        import keyring
        from keyring.errors import KeyringError

        # Test write/read/delete
        test_key = "__merlya_health_test__"
        test_value = f"test_{time.time()}"

        try:
            keyring.set_password("merlya", test_key, test_value)
            result = keyring.get_password("merlya", test_key)
            keyring.delete_password("merlya", test_key)

            if result == test_value:
                # Get backend info
                backend = keyring.get_keyring()
                backend_name = type(backend).__name__

                return HealthCheck(
                    name="keyring",
                    status=CheckStatus.OK,
                    message=t("health.keyring.ok") + f" ({backend_name})",
                    details={"backend": backend_name},
                )
            else:
                return HealthCheck(
                    name="keyring",
                    status=CheckStatus.WARNING,
                    message=t("health.keyring.warning", error="value mismatch"),
                    details={"error": "value_mismatch"},
                )

        except KeyringError as e:
            return HealthCheck(
                name="keyring",
                status=CheckStatus.WARNING,
                message=t("health.keyring.warning", error=str(e)),
                details={"error": str(e)},
            )

    except ImportError:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=t("health.keyring.warning", error="not installed"),
            details={"error": "not_installed"},
        )
    except Exception as e:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=t("health.keyring.warning", error=str(e)),
            details={"error": str(e)},
        )


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


def check_onnx_model(tier: str | None = None) -> HealthCheck:
    """Check if ONNX embedding model is available or downloadable."""
    from merlya.config import get_config

    override = os.getenv("MERLYA_ROUTER_MODEL")
    config = get_config()
    cfg_model = getattr(config, "router", None)
    model_id = override or (cfg_model.model if cfg_model else None)

    # Use classifier helpers to resolve paths consistently
    selector = IntentClassifier(use_embeddings=False, model_id=model_id, tier=tier)
    selected_id = selector._select_model_id(model_id, tier)
    model_path = selector._resolve_model_path(selected_id)
    tokenizer_path = model_path.parent / "tokenizer.json"

    try:
        import onnxruntime  # noqa: F401
        from tokenizers import Tokenizer  # noqa: F401
    except ImportError as e:
        return HealthCheck(
            name="onnx_model",
            status=CheckStatus.DISABLED,
            message="⚠️ ONNX runtime not installed (router will use pattern matching)",
            details={"error": str(e), "can_download": False},
        )

    missing: list[str] = []
    if not model_path.exists():
        missing.append(str(model_path))
    if not tokenizer_path.exists():
        missing.append(str(tokenizer_path))

    if missing:
        return HealthCheck(
            name="onnx_model",
            status=CheckStatus.WARNING,
            message="⚠️ ONNX assets missing - will download automatically on first use",
            details={"missing": missing, "can_download": True},
        )

    size_mb = model_path.stat().st_size / (1024 * 1024)

    return HealthCheck(
        name="onnx_model",
        status=CheckStatus.OK,
        message=f"✅ ONNX model available ({size_mb:.1f}MB)",
        details={
            "model_path": str(model_path),
            "tokenizer_path": str(tokenizer_path),
            "size_mb": size_mb,
            "exists": True,
            "can_download": False,
        },
    )


def check_parser_service(tier: str | None = None) -> HealthCheck:
    """Check if Parser service is properly initialized."""
    try:
        parser = ParserService.get_instance()
        backend_name = type(parser._backend).__name__

        return HealthCheck(
            name="parser",
            status=CheckStatus.OK,
            message=f"✅ Parser service ready ({backend_name})",
            details={
                "backend": backend_name,
                "tier": tier or "auto",
            },
        )
    except Exception as e:
        return HealthCheck(
            name="parser",
            status=CheckStatus.WARNING,
            message=f"⚠️ Parser not initialized: {str(e)[:50]}",
            details={"error": str(e)},
        )


def check_session_manager() -> HealthCheck:
    """Check if Session manager is available."""
    try:
        manager = SessionManager.get_instance()
        if manager is None:
            return HealthCheck(
                name="session",
                status=CheckStatus.WARNING,
                message="⚠️ Session manager not initialized",
                details={"error": "No instance created yet"},
            )

        tier = manager.current_tier.value if manager.current_tier else "auto"
        max_tokens = getattr(manager, "max_tokens", None) or manager.limits.max_tokens

        return HealthCheck(
            name="session",
            status=CheckStatus.OK,
            message=f"✅ Session manager ready (tier={tier})",
            details={
                "tier": tier,
                "max_tokens": max_tokens,
            },
        )
    except Exception as e:
        return HealthCheck(
            name="session",
            status=CheckStatus.WARNING,
            message=f"⚠️ Session manager not initialized: {str(e)[:50]}",
            details={"error": str(e)},
        )


def check_skills_registry() -> HealthCheck:
    """Check if Skills registry has loaded skills."""
    try:
        registry = get_skills_registry()
        stats = registry.get_stats()

        if stats["total"] == 0:
            return HealthCheck(
                name="skills",
                status=CheckStatus.WARNING,
                message="⚠️ No skills loaded (use /skill reload)",
                details=stats,
            )

        return HealthCheck(
            name="skills",
            status=CheckStatus.OK,
            message=f"✅ Skills loaded ({stats['builtin']} builtin, {stats['user']} user)",
            details=stats,
        )
    except Exception as e:
        return HealthCheck(
            name="skills",
            status=CheckStatus.WARNING,
            message=f"⚠️ Skills registry error: {str(e)[:50]}",
            details={"error": str(e)},
        )


async def check_mcp_servers() -> HealthCheck:
    """Check if MCP servers are configured and running."""
    try:
        from merlya.mcp.manager import MCPManager

        manager = MCPManager.get_instance()
        if manager is None:
            return HealthCheck(
                name="mcp",
                status=CheckStatus.DISABLED,
                message="ℹ️ MCP manager not initialized",
                details={"error": "No instance created yet"},
            )

        servers = await manager.list_servers()

        if not servers:
            return HealthCheck(
                name="mcp",
                status=CheckStatus.DISABLED,
                message="ℹ️ No MCP servers configured",
                details={"servers": []},
            )

        # Count running vs total
        running = sum(1 for s in servers if s.get("status") == "running")
        total = len(servers)

        if running == 0:
            status = CheckStatus.WARNING
            message = f"⚠️ MCP: 0/{total} servers running"
        elif running < total:
            status = CheckStatus.WARNING
            message = f"⚠️ MCP: {running}/{total} servers running"
        else:
            status = CheckStatus.OK
            message = f"✅ MCP: {running} server(s) running"

        return HealthCheck(
            name="mcp",
            status=status,
            message=message,
            details={"servers": servers, "running": running, "total": total},
        )
    except Exception as e:
        return HealthCheck(
            name="mcp",
            status=CheckStatus.WARNING,
            message=f"⚠️ MCP check failed: {str(e)[:50]}",
            details={"error": str(e)},
        )


async def run_startup_checks(skip_llm_ping: bool = False) -> StartupHealth:
    """
    Run all startup health checks.

    Args:
        skip_llm_ping: Skip the LLM connectivity test (faster startup).

    Returns:
        StartupHealth with all check results.
    """
    health = StartupHealth()

    logger.debug("🔍 Running health checks...")

    # RAM check (determines model tier)
    ram_check, tier = check_ram()
    health.checks.append(ram_check)
    health.model_tier = tier

    # Disk space
    health.checks.append(check_disk_space())

    # LLM provider (with real ping unless skipped)
    if skip_llm_ping:
        # Quick check - just verify API key exists
        import os

        from merlya.config import get_config
        from merlya.secrets import get_secret

        config = get_config()
        key_env = config.model.api_key_env or f"{config.model.provider.upper()}_API_KEY"
        has_key = bool(os.getenv(key_env) or get_secret(key_env))

        health.checks.append(
            HealthCheck(
                name="llm_provider",
                status=CheckStatus.OK
                if has_key or config.model.provider == "ollama"
                else CheckStatus.ERROR,
                message=f"✅ {config.model.provider} (ping skipped)"
                if has_key
                else "❌ No API key",
                critical=not has_key and config.model.provider != "ollama",
            )
        )
    else:
        health.checks.append(await check_llm_provider())

    # SSH
    ssh_check = check_ssh_available()
    health.checks.append(ssh_check)
    health.capabilities["ssh"] = ssh_check.status == CheckStatus.OK

    # Keyring
    keyring_check = check_keyring()
    health.checks.append(keyring_check)
    health.capabilities["keyring"] = keyring_check.status == CheckStatus.OK

    # Web search (with real connectivity test)
    ws_check = await check_web_search()
    health.checks.append(ws_check)
    health.capabilities["web_search"] = ws_check.status == CheckStatus.OK

    # ONNX model
    onnx_check = check_onnx_model(tier=tier)
    health.checks.append(onnx_check)
    details = onnx_check.details or {}
    can_use_onnx = onnx_check.status == CheckStatus.OK or (
        onnx_check.status == CheckStatus.WARNING and details.get("can_download", False)
    )
    health.capabilities["onnx_router"] = can_use_onnx

    # Parser service
    parser_check = check_parser_service(tier=tier)
    health.checks.append(parser_check)
    health.capabilities["parser"] = parser_check.status == CheckStatus.OK

    # Session manager
    session_check = check_session_manager()
    health.checks.append(session_check)
    health.capabilities["session"] = session_check.status == CheckStatus.OK

    # Skills registry
    skills_check = check_skills_registry()
    health.checks.append(skills_check)
    health.capabilities["skills"] = skills_check.status == CheckStatus.OK

    # MCP servers
    mcp_check = await check_mcp_servers()
    health.checks.append(mcp_check)
    health.capabilities["mcp"] = mcp_check.status == CheckStatus.OK

    logger.debug(
        f"✅ Health checks complete: {len(health.checks)} checks, can_start={health.can_start}"
    )

    return health
