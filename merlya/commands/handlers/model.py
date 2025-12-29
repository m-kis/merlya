"""
Merlya Commands - Model management handlers.

Implements /model command with subcommands: show, provider, brain, fast, test.

Two model roles:
  - brain: Complex reasoning, planning, analysis (Orchestrator, Centers)
  - fast: Quick routing, fingerprinting, token-efficient tasks (Router, Classifier)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.config.provider_env import (
    ensure_provider_env,
    ollama_requires_api_key,
)
from merlya.config.providers import get_provider_models

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("model", "Manage LLM provider and models", "/model <subcommand>")
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
    key_env = config.api_key_env or f"{config.provider.upper()}_API_KEY"
    has_key = key_env and ctx.secrets.has(key_env)

    # Get actual brain/fast models
    brain_model = config.get_orchestrator_model()
    fast_model = config.get_fast_model()

    lines = [
        "**Model Configuration**\n",
        f"**Provider:** `{config.provider}`",
        f"**API Key:** `{'configured' if has_key else 'not set'}` ({key_env})",
        "",
        "**Models:**",
        f"  🧠 brain: `{brain_model}` (reasoning, planning)",
        f"  ⚡ fast: `{fast_model}` (routing, fingerprinting)",
    ]

    if config.base_url:
        lines.append(f"\n**Base URL:** `{config.base_url}`")

    return CommandResult(success=True, message="\n".join(lines))


@subcommand("model", "provider", "Change LLM provider", "/model provider <name>")
async def cmd_model_provider(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Change the LLM provider (sets default brain/fast models for provider)."""
    from merlya.config.providers import list_providers

    providers = list_providers()

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

    # Get provider defaults (brain, fast, api_key_env, base_url)
    try:
        provider_config = get_provider_models(provider)
    except ValueError as e:
        return CommandResult(success=False, message=str(e))

    api_key_env = provider_config.api_key_env

    if api_key_env and not ctx.secrets.has(api_key_env):
        api_key = await ctx.ui.prompt_secret(f"🔑 Enter {api_key_env}")
        if api_key:
            ctx.secrets.set(api_key_env, api_key)
            ctx.ui.success("✅ API key saved to keyring")
            _set_api_key_from_keyring(ctx, api_key_env)
        else:
            return CommandResult(success=False, message="API key required for this provider.")

    # Update config with provider defaults
    ctx.config.model.provider = provider
    ctx.config.model.model = provider_config.brain  # Default brain model
    ctx.config.model.reasoning_model = None  # Reset to use provider default
    ctx.config.model.fast_model = None  # Reset to use provider default
    ctx.config.model.api_key_env = api_key_env or ""
    ctx.config.model.base_url = provider_config.base_url

    # Set router fallback to fast model
    ctx.config.router.llm_fallback = f"{provider}:{provider_config.fast}"

    if api_key_env:
        _set_api_key_from_keyring(ctx, api_key_env)

    # Apply provider-specific environment setup (Ollama, OpenRouter, etc.)
    ensure_provider_env(ctx.config)
    ctx.config.save()

    return CommandResult(
        success=True,
        message=f"✅ Provider changed to `{provider}`\n\n"
        f"  🧠 brain: `{provider_config.brain}`\n"
        f"  ⚡ fast: `{provider_config.fast}`\n\n"
        f"Use `/model brain <name>` or `/model fast <name>` to customize.",
        data={"reload_agent": True},
    )


@subcommand("model", "brain", "Set brain model (reasoning)", "/model brain <name>")
async def cmd_model_brain(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set the brain model for complex reasoning tasks."""
    provider = ctx.config.model.provider
    provider_config = get_provider_models(provider)

    if not args:
        # Show current brain model and suggestions
        current = ctx.config.model.get_orchestrator_model()
        return CommandResult(
            success=True,
            message=f"**Brain Model** (reasoning, planning, analysis)\n\n"
            f"  Current: `{current}`\n"
            f"  Default for {provider}: `{provider_config.brain}`\n\n"
            f"Usage: `/model brain <model_name>`",
        )

    model_name = args[0]

    # Handle Ollama: check if local and pull model if needed
    if provider == "ollama":
        is_cloud = "cloud" in model_name.lower() or ollama_requires_api_key(ctx.config)
        if not is_cloud:
            pull_result = await _ensure_ollama_model(ctx, model_name)
            if pull_result and not pull_result.success:
                return pull_result

    ctx.config.model.model = model_name
    ctx.config.model.reasoning_model = model_name
    ensure_provider_env(ctx.config)
    ctx.config.save()

    return CommandResult(
        success=True,
        message=f"🧠 Brain model changed to `{model_name}`",
        data={"reload_agent": True},
    )


@subcommand("model", "fast", "Set fast model (routing)", "/model fast <name>")
async def cmd_model_fast(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set the fast model for quick routing tasks."""
    provider = ctx.config.model.provider
    provider_config = get_provider_models(provider)

    if not args:
        # Show current fast model and suggestions
        current = ctx.config.model.get_fast_model()
        return CommandResult(
            success=True,
            message=f"**Fast Model** (routing, fingerprinting, classification)\n\n"
            f"  Current: `{current}`\n"
            f"  Default for {provider}: `{provider_config.fast}`\n\n"
            f"Usage: `/model fast <model_name>`",
        )

    model_name = args[0]

    # Handle Ollama: check if local and pull model if needed
    if provider == "ollama":
        is_cloud = "cloud" in model_name.lower() or ollama_requires_api_key(ctx.config)
        if not is_cloud:
            pull_result = await _ensure_ollama_model(ctx, model_name)
            if pull_result and not pull_result.success:
                return pull_result

    ctx.config.model.fast_model = model_name
    ensure_provider_env(ctx.config)
    ctx.config.save()

    return CommandResult(
        success=True,
        message=f"⚡ Fast model changed to `{model_name}`",
        data={"reload_agent": True},
    )


@subcommand("model", "model", "DEPRECATED - Use /model brain", "/model model <name>")
async def cmd_model_model(ctx: SharedContext, args: list[str]) -> CommandResult:
    """DEPRECATED: Use /model brain or /model fast instead."""
    ctx.ui.warning("⚠️ `/model model` is deprecated. Use `/model brain` or `/model fast`.")

    if not args:
        return CommandResult(
            success=False,
            message="⚠️ **DEPRECATED**: Use `/model brain <name>` or `/model fast <name>` instead.\n\n"
            "  - `/model brain <name>` - Complex reasoning (orchestrator, planning)\n"
            "  - `/model fast <name>` - Quick routing (classification, fingerprinting)",
        )

    # Redirect to brain model for backward compatibility
    return await cmd_model_brain(ctx, args)


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


@subcommand("model", "router", "DEPRECATED - Router removed", "/model router")
async def cmd_model_router(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """DEPRECATED: Router has been removed. All routing is now handled by the Orchestrator."""
    return CommandResult(
        success=False,
        message="⚠️ `/model router` is **deprecated**.\n\n"
        "The intent router has been removed. All requests are now processed by the **Orchestrator**.\n\n"
        "Use `/model show` to see current configuration.",
    )


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
