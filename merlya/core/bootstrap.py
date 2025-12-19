"""
Merlya Core - Bootstrap module.

Unified initialization for CLI and REPL modes.
Ensures consistent behavior across all entry points.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.agent import MerlyaAgent
    from merlya.core.context import SharedContext
    from merlya.health import StartupHealth


@dataclass
class BootstrapResult:
    """Result of bootstrap initialization."""

    ctx: SharedContext
    health: StartupHealth
    agent: MerlyaAgent


async def bootstrap(
    *,
    auto_confirm: bool = False,
    quiet: bool = False,
    output_format: str = "text",
    verbose: bool = False,
) -> BootstrapResult:
    """
    Initialize Merlya with unified bootstrap sequence.

    This is the single entry point for all initialization, ensuring
    consistent behavior between CLI and REPL modes.

    Args:
        auto_confirm: Skip confirmation prompts (non-interactive mode).
        quiet: Minimal output.
        output_format: Output format (text/json).
        verbose: Enable verbose logging.

    Returns:
        BootstrapResult with initialized context, health, and agent.
    """
    from merlya.agent import MerlyaAgent
    from merlya.commands import init_commands
    from merlya.core.context import SharedContext
    from merlya.health import run_startup_checks
    from merlya.secrets import load_api_keys_from_keyring

    # Initialize commands registry
    init_commands()

    # Create shared context
    ctx = await SharedContext.create()
    ctx.auto_confirm = auto_confirm
    ctx.quiet = quiet
    ctx.output_format = output_format

    # Configure logging from config (respects saved settings)
    _configure_logging_from_config(ctx, verbose=verbose, quiet=quiet)

    # Initialize Logfire observability (if LOGFIRE_TOKEN is set)
    try:
        _init_observability()
    except Exception as e:
        logger.warning(
            f"Observability initialization failed, continuing without it: {e}", exc_info=True
        )

    # Load API keys from keyring
    load_api_keys_from_keyring(ctx.config, ctx.secrets)

    # Run health checks (only show details in debug mode)
    health = await run_startup_checks()
    ctx.health = health
    is_debug = ctx.config.logging.console_level == "debug"

    if not quiet and is_debug:
        ctx.ui.info(ctx.t("startup.health_checks"))
        for check in health.checks:
            ctx.ui.health_status(check.name, check.status, check.message)

    if not health.can_start:
        ctx.ui.error("❌ Cannot start: critical checks failed")
        raise RuntimeError("Health checks failed")

    # Initialize router
    await ctx.init_router(health.model_tier)

    if not quiet and is_debug:
        router = ctx.router
        if router and router.classifier.model_loaded:
            dims = router.classifier.embedding_dim or "?"
            ctx.ui.info(ctx.t("startup.router_init", model="local", dims=dims))
        else:
            fallback = ctx.config.router.llm_fallback or "pattern matching"
            ctx.ui.warning(ctx.t("startup.router_fallback", mode=fallback))

    # Create agent
    model = f"{ctx.config.model.provider}:{ctx.config.model.model}"
    agent = MerlyaAgent(ctx, model=model)

    logger.debug("✅ Bootstrap complete")

    return BootstrapResult(ctx=ctx, health=health, agent=agent)


def _configure_logging_from_config(
    ctx: SharedContext,
    *,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    """
    Configure logging based on saved config and runtime flags.

    Priority (highest to lowest):
    1. --quiet flag → disable logging
    2. --verbose flag → DEBUG level
    3. Config logging.console_level

    Args:
        ctx: Shared context with config.
        verbose: Enable verbose (DEBUG) logging.
        quiet: Disable all console logging.
    """
    from merlya.core.logging import configure_logging

    if quiet:
        logger.disable("merlya")
        return

    # Determine console level
    if verbose:
        console_level = "DEBUG"
    else:
        # Use config value - prefer logging.console_level, fallback to general.log_level
        console_level = str(
            getattr(ctx.config.logging, "console_level", None)
            or getattr(ctx.config.general, "log_level", "info")
        )

    # File level from config
    file_level = str(getattr(ctx.config.logging, "file_level", "debug"))

    configure_logging(
        console_level=console_level.upper(),
        file_level=file_level.upper(),
        force=True,
    )

    logger.debug(f"⚙️ Logging configured: console={console_level}, file={file_level}")


def _init_observability() -> None:
    """
    Initialize Logfire observability if configured.

    Logfire is enabled when LOGFIRE_TOKEN environment variable is set.
    It provides:
    - Distributed tracing for PydanticAI agent calls
    - LLM cost and token tracking
    - Loguru logs bridged to Logfire dashboard
    """
    from merlya.core.observability import init_logfire

    init_logfire()
