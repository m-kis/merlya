"""
Merlya Commands - Model management handlers.

Implements /model command with subcommands: show, provider, model, test, router.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.config.provider_env import (
    ensure_openrouter_headers,
    ensure_provider_env,
    ollama_requires_api_key,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("model", "Manage LLM provider and router", "/model <subcommand>")
async def cmd_model(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage LLM provider and model configuration."""
    if not args:
        return await cmd_model_show(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help model` for available commands.",
        show_help=True,
    )


@subcommand("model", "show", "Show current model config", "/model show")
async def cmd_model_show(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Show current model configuration."""
    config = ctx.config.model
    router_config = ctx.config.router
    key_env = config.api_key_env or f"{config.provider.upper()}_API_KEY"
    has_key = key_env and ctx.secrets.has(key_env)

    lines = [
        "**Model Configuration**\n",
        "**LLM Provider:**",
        f"  - Provider: `{config.provider}`",
        f"  - Model: `{config.model}`",
        f"  - API Key: `{'configured' if has_key else 'not set'}` ({key_env})",
        "",
        "**Router:**",
        f"  - Type: `{router_config.type}`",
        f"  - Tier: `{router_config.tier or 'auto'}`",
        f"  - LLM Fallback: `{router_config.llm_fallback or 'none'}`",
    ]

    return CommandResult(success=True, message="\n".join(lines))


@subcommand("model", "provider", "Change LLM provider", "/model provider <name>")
async def cmd_model_provider(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Change the LLM provider."""
    providers = ["openrouter", "anthropic", "openai", "mistral", "groq", "ollama", "litellm"]
    default_models = {
        "openrouter": "amazon/nova-2-lite-v1:free",
        "anthropic": "claude-3-5-sonnet-20241022",
        "openai": "gpt-4o",
        "mistral": "mistral-large-latest",
        "groq": "llama-3.1-70b-versatile",
        "ollama": "llama3.2",
        "litellm": "gpt-4o",
    }
    router_fallbacks = {
        "openrouter": "openrouter:openrouter/auto",
        "anthropic": "anthropic:claude-3-haiku-20240307",
        "openai": "openai:gpt-4o-mini",
        "mistral": "mistral:mistral-small-latest",
        "groq": "groq:llama-3.1-8b-instant",
        "litellm": "litellm:gpt-4o-mini",
        "ollama": "ollama:llama3.2",
    }

    if not args:
        return CommandResult(
            success=False,
            message=f"Usage: `/model provider <name>`\n\nAvailable: {', '.join(providers)}",
        )

    provider = args[0].lower()
    if provider not in providers:
        return CommandResult(
            success=False,
            message=f"Unknown provider: `{provider}`\nAvailable: {', '.join(providers)}",
        )

    api_key_envs = {
        "openrouter": "OPENROUTER_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "groq": "GROQ_API_KEY",
        "litellm": "LITELLM_API_KEY",
        "ollama": None,
    }

    api_key_env = api_key_envs.get(provider)

    if api_key_env and not ctx.secrets.has(api_key_env):
        api_key = await ctx.ui.prompt_secret(f"🔑 Enter {api_key_env}")
        if api_key:
            ctx.secrets.set(api_key_env, api_key)
            ctx.ui.success("✅ API key saved to keyring")
            _set_api_key_from_keyring(ctx, api_key_env)
        else:
            return CommandResult(success=False, message="API key required for this provider.")

    if provider == "openrouter":
        ensure_openrouter_headers()

    ctx.config.model.provider = provider
    if provider in default_models:
        ctx.config.model.model = default_models[provider]
    if provider in router_fallbacks:
        ctx.config.router.llm_fallback = router_fallbacks[provider]
    ctx.config.model.api_key_env = api_key_env or ""
    ctx.config.model.base_url = ctx.config.model.base_url or None

    if api_key_env:
        _set_api_key_from_keyring(ctx, api_key_env)

    if provider == "ollama":
        ensure_provider_env(ctx.config)
    ctx.config.save()

    return CommandResult(
        success=True,
        message=ctx.t("commands.model.provider_changed", provider=provider),
        data={"reload_agent": True},
    )


@subcommand("model", "model", "Change LLM model", "/model model <name>")
async def cmd_model_model(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Change the LLM model."""
    if not args:
        default_models = {
            "openrouter": "amazon/nova-2-lite-v1:free",
            "anthropic": "claude-3-5-sonnet-20241022",
            "openai": "gpt-4o",
            "mistral": "mistral-large-latest",
            "groq": "llama-3.1-70b-versatile",
            "ollama": "llama3.2",
            "litellm": "gpt-4o",
        }
        suggestions = default_models.get(ctx.config.model.provider, "")
        return CommandResult(
            success=False,
            message=f"Usage: `/model model <name>`\n\nSuggested for {ctx.config.model.provider}: `{suggestions}`",
        )

    model = args[0]
    ctx.config.model.model = model

    if ctx.config.model.provider == "ollama":
        ctx.config.model.base_url = None  # reset per model switch
        is_cloud = "cloud" in model.lower() or ollama_requires_api_key(ctx.config)
        ctx.config.model.base_url = ctx.config.model.base_url or (
            "https://ollama.com" if is_cloud else "http://localhost:11434"
        )
        ensure_provider_env(ctx.config)
        if is_cloud:
            ctx.config.model.api_key_env = "OLLAMA_API_KEY"
            api_key_env = "OLLAMA_API_KEY"
            if not (os.getenv(api_key_env) or ctx.secrets.has(api_key_env)):
                api_key = await ctx.ui.prompt_secret(f"🔑 Enter {api_key_env}")
                if api_key:
                    ctx.secrets.set(api_key_env, api_key)
                    ctx.ui.success("✅ API key saved to keyring")
                    _set_api_key_from_keyring(ctx, api_key_env)
                else:
                    return CommandResult(
                        success=False,
                        message=ctx.t("commands.model.api_key_missing"),
                    )
            # Force cloud endpoint if still local
            if ctx.config.model.base_url and "localhost" in ctx.config.model.base_url:
                ctx.config.model.base_url = "https://ollama.com/v1"
                ensure_provider_env(ctx.config)
        else:
            pull_result = await _ensure_ollama_model(ctx, model)
            if pull_result and not pull_result.success:
                return pull_result
    else:
        api_key_env = ctx.config.model.api_key_env or f"{ctx.config.model.provider.upper()}_API_KEY"
        _set_api_key_from_keyring(ctx, api_key_env)
        if ctx.config.model.provider == "openrouter":
            ensure_openrouter_headers()
    ctx.config.save()

    return CommandResult(
        success=True,
        message=ctx.t("commands.model.model_changed", model=model),
        data={"reload_agent": True},
    )


@subcommand("model", "test", "Test LLM connection", "/model test")
async def cmd_model_test(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Test the LLM provider connection."""
    import os

    provider = ctx.config.model.provider
    key_env = ctx.config.model.api_key_env or f"{provider.upper()}_API_KEY"

    # Ensure API key is available for the test
    if not os.getenv(key_env):
        secret_value = ctx.secrets.get(key_env) if hasattr(ctx.secrets, "get") else None
        if secret_value:
            os.environ[key_env] = secret_value

    ctx.ui.info(f"🔍 Testing connection to {provider}...")

    try:
        from pydantic_ai import Agent

        primary_model = f"{provider}:{ctx.config.model.model}"

        def _normalize(model_name: str) -> str:
            return model_name if ":" in model_name else f"{provider}:{model_name}"

        candidates: list[str] = [primary_model]
        if provider == "openrouter":
            if ctx.config.router.llm_fallback:
                candidates.append(_normalize(ctx.config.router.llm_fallback))
            # Broadly available fallbacks (free + auto router)
            candidates.extend(
                [
                    "openrouter:amazon/nova-2-lite-v1:free",
                    "openrouter:openrouter/auto",
                ]
            )

        # Remove duplicates while preserving order
        seen: set[str] = set()
        unique_candidates: list[str] = []
        for m in candidates:
            if m not in seen:
                seen.add(m)
                unique_candidates.append(m)
        candidates = unique_candidates

        errors: list[tuple[str, str]] = []

        with ctx.ui.spinner(f"Testing {len(candidates)} model option(s)..."):
            for model_path in candidates:
                start = time.time()
                try:
                    agent = Agent(
                        model_path,
                        system_prompt="Reply with exactly: OK",
                    )
                    result = await agent.run("Test")
                    elapsed = time.time() - start

                    # Support both legacy result.data and newer attributes
                    raw_data = getattr(result, "data", None)
                    if raw_data is None and hasattr(result, "output"):
                        raw_data = result.output
                    response_text = str(raw_data)

                    if "ok" in response_text.lower():
                        fallback_note = ""
                        if model_path != primary_model:
                            fallback_note = f"\n  - Fallback used: `{model_path}`"
                        return CommandResult(
                            success=True,
                            message=f"✅ LLM connection OK\n"
                            f"  - Provider: `{provider}`\n"
                            f"  - Model: `{model_path}`\n"
                            f"  - Latency: `{elapsed:.2f}s`"
                            f"{fallback_note}",
                        )

                    errors.append((model_path, f"Unexpected response: {response_text}"))
                except Exception as e:
                    errors.append((model_path, str(e)))

        # If we reach here, all attempts failed
        error_lines = [f"  - {m}: {err}" for m, err in errors[:2]]
        if len(errors) > 2:
            error_lines.append(f"  - ... and {len(errors) - 2} more")

        return CommandResult(
            success=False,
            message="❌ LLM connection failed\n"
            + "\n".join(error_lines)
            + "\n\nCheck your API key with `/secret list` and provider with `/model show`",
        )

    except Exception as e:
        return CommandResult(
            success=False,
            message=f"❌ LLM connection failed\n"
            f"  - Error: `{e}`\n\n"
            "Check your API key with `/secret list` and provider with `/model show`",
        )


@subcommand("model", "router", "Configure intent router", "/model router <show|local|llm>")
async def cmd_model_router(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Configure the intent router."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage:\n"
            "  `/model router show` - Show router config\n"
            "  `/model router local` - Use local ONNX model\n"
            "  `/model router llm <model>` - Use LLM for routing",
        )

    action = args[0].lower()

    if action == "show":
        return _show_router_config(ctx)
    elif action == "local":
        return _set_local_router(ctx)
    elif action == "llm":
        return _set_llm_router(ctx, args)
    else:
        return CommandResult(success=False, message=f"Unknown router action: `{action}`")


def _show_router_config(ctx: SharedContext) -> CommandResult:
    """Show router configuration."""
    router_config = ctx.config.router
    lines = [
        "**Router Configuration**\n",
        f"  - Type: `{router_config.type}`",
        f"  - Model: `{router_config.model or 'default'}`",
        f"  - Tier: `{router_config.tier or 'auto'}`",
        f"  - LLM Fallback: `{router_config.llm_fallback or 'none'}`",
    ]

    model_path = Path.home() / ".merlya" / "models" / "router.onnx"
    if model_path.exists():
        size_mb = model_path.stat().st_size / (1024 * 1024)
        lines.append(f"\n  ✅ ONNX model loaded ({size_mb:.1f}MB)")
    else:
        lines.append("\n  ⚠️ ONNX model not found (using pattern matching)")

    return CommandResult(success=True, message="\n".join(lines))


def _set_local_router(ctx: SharedContext) -> CommandResult:
    """Set router to local ONNX model."""
    ctx.config.router.type = "local"
    ctx.config.save()
    return CommandResult(success=True, message="✅ Router set to local (ONNX embedding model)")


def _set_llm_router(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set router to use LLM."""
    if len(args) < 2:
        return CommandResult(
            success=False,
            message="Usage: `/model router llm <model>`\nExample: `/model router llm gpt-4o-mini`",
        )
    llm_model = args[1]
    if ":" not in llm_model:
        llm_model = f"{ctx.config.model.provider}:{llm_model}"
    ctx.config.router.type = "llm"
    ctx.config.router.llm_fallback = llm_model
    ctx.config.save()
    return CommandResult(success=True, message=f"✅ Router set to LLM ({llm_model})")


async def _ensure_ollama_model(ctx: SharedContext, model: str) -> CommandResult | None:
    """
    Ensure the requested Ollama model is available (pull if missing).

    Returns a CommandResult on failure, or None on success.
    """
    if not shutil.which("ollama"):
        return CommandResult(
            success=False,
            message=ctx.t("commands.model.ollama_cli_missing"),
        )

    ctx.ui.info(ctx.t("commands.model.ollama_pull_start", model=model))

    try:
        proc = await asyncio.create_subprocess_exec(
            "ollama",
            "pull",
            model,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        return CommandResult(
            success=False,
            message=ctx.t("commands.model.ollama_cli_missing"),
        )
    except Exception as e:  # pragma: no cover - defensive
        return CommandResult(
            success=False,
            message=ctx.t("commands.model.ollama_pull_failed", model=model, error=str(e)),
        )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except TimeoutError:
        proc.kill()
        return CommandResult(
            success=False,
            message=ctx.t("commands.model.ollama_pull_failed", model=model, error="timeout"),
        )

    if proc.returncode == 0:
        ctx.ui.success(ctx.t("commands.model.ollama_pull_ready", model=model))
        return None

    error_text = (stderr or stdout or b"").decode(errors="ignore").strip()
    lowered = error_text.lower()
    if "not found" in lowered or "no such model" in lowered or "does not exist" in lowered:
        return CommandResult(
            success=False,
            message=ctx.t("commands.model.ollama_pull_not_found", model=model),
        )

    return CommandResult(
        success=False,
        message=ctx.t(
            "commands.model.ollama_pull_failed",
            model=model,
            error=error_text or "unknown error",
        ),
    )


def _set_api_key_from_keyring(ctx: SharedContext, api_key_env: str) -> None:
    """Load an API key from keyring into the environment if present."""
    if os.getenv(api_key_env):
        return
    secret_getter = getattr(ctx.secrets, "get", None)
    if secret_getter:
        value = secret_getter(api_key_env)
        if isinstance(value, str) and value:
            os.environ[api_key_env] = value
