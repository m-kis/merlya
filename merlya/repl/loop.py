"""
Merlya REPL - Main loop.

Interactive console with autocompletion.

Architecture:
  User Input
  ├── "/" command → Slash command dispatch (fast-path, 0 tokens)
  └── Free text → Orchestrator (LLM) → Delegates to specialists
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from merlya.config.constants import COMPLETION_CACHE_TTL_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from merlya.agent.orchestrator import Orchestrator
    from merlya.core.context import SharedContext

from loguru import logger
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

# Prompt style
PROMPT_STYLE = Style.from_dict(
    {
        "prompt": "#00aa00 bold",
        "host": "#888888",
    }
)


@dataclass
class WelcomeStatus:
    """Structured data for the welcome screen."""

    version: str
    env: str
    session_id: str
    model_label: str
    keyring_label: str


def format_model_label(agent_model: str | None, provider: str, model: str) -> str:
    """Format model label for the welcome screen."""
    model_value = agent_model or f"{provider}:{model}"
    if ":" in model_value:
        provider_name, model_name = model_value.split(":", 1)
    else:
        provider_name, model_name = provider, model_value
    return f"✅ {provider_name}:{model_name}"


def build_welcome_lines(
    translate: Callable[..., str],
    status: WelcomeStatus,
) -> tuple[list[str], list[str]]:
    """Assemble hero and warning lines for the welcome screen."""
    hero_lines = [
        translate("welcome_screen.subtitle", version=status.version),
        "",
        f"Model: {status.model_label}   Keyring: {status.keyring_label}",
        "",
        translate("welcome_screen.commands_hint"),
        "  /help  /hosts  /scan  /new  /exit",
        "",
        translate("welcome_screen.prompt"),
    ]

    warning_lines = [
        translate("welcome_screen.warning_header"),
        translate("welcome_screen.warning_body"),
    ]

    return hero_lines, warning_lines


class MerlyaCompleter(Completer):
    """
    Autocompletion for Merlya REPL.

    Supports:
    - Slash commands (/help, /hosts, etc.)
    - Host mentions (@hostname)
    - Variable mentions (@variable)
    - Secret mentions (@secret-name)
    """

    def __init__(self, ctx: SharedContext) -> None:
        """Initialize completer."""
        self.ctx = ctx
        self._hosts_cache: list[str] = []
        self._variables_cache: list[str] = []
        self._secrets_cache: list[str] = []
        self._last_cache_update: float = 0.0

    async def _update_cache(self) -> None:
        """Update completion cache."""
        import time

        now = time.time()
        if now - self._last_cache_update < COMPLETION_CACHE_TTL_SECONDS:
            return

        try:
            hosts = await self.ctx.hosts.get_all()
            self._hosts_cache = [h.name for h in hosts]

            variables = await self.ctx.variables.get_all()
            self._variables_cache = [v.name for v in variables]

            # Secrets from keyring
            self._secrets_cache = self.ctx.secrets.list_names()

            self._last_cache_update = now
        except Exception as e:
            logger.debug(f"Failed to update completion cache: {e}")

    def get_completions(self, document: Any, _complete_event: Any) -> Iterable[Completion]:
        """Get completions for current input."""
        text = document.text_before_cursor
        document.get_word_before_cursor()

        # Slash commands
        if text.startswith("/"):
            from merlya.commands import get_registry

            registry = get_registry()
            for completion in registry.get_completions(text):
                yield Completion(
                    completion,
                    start_position=-len(text),
                    display_meta="command",
                )
            return

        # @ mentions (hosts and variables)
        if "@" in text:
            # Find the @ position
            at_pos = text.rfind("@")
            prefix = text[at_pos + 1 :]

            # Complete hosts
            for host in self._hosts_cache:
                if host.lower().startswith(prefix.lower()):
                    yield Completion(
                        host,
                        start_position=-len(prefix),
                        display=f"@{host}",
                        display_meta="host",
                    )

            # Complete variables
            for var in self._variables_cache:
                if var.lower().startswith(prefix.lower()):
                    yield Completion(
                        var,
                        start_position=-len(prefix),
                        display=f"@{var}",
                        display_meta="variable",
                    )

            # Complete secrets
            for secret in self._secrets_cache:
                if secret.lower().startswith(prefix.lower()):
                    yield Completion(
                        secret,
                        start_position=-len(prefix),
                        display=f"@{secret}",
                        display_meta="secret",
                    )


class REPL:
    """
    Merlya REPL (Read-Eval-Print Loop).

    Main interactive console for Merlya.

    Architecture:
      "/" commands → Slash command dispatch (fast-path)
      Free text → Orchestrator (LLM delegates to specialists)
    """

    def __init__(
        self,
        ctx: SharedContext,
        orchestrator: Orchestrator,
    ) -> None:
        """
        Initialize REPL.

        Args:
            ctx: Shared context.
            orchestrator: Main orchestrator for LLM processing.
        """
        self.ctx = ctx
        self.orchestrator = orchestrator
        self.completer = MerlyaCompleter(ctx)
        self.running = False
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Setup prompt session
        history_path = ctx.config.general.data_dir / "history"
        self.session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self.completer,
            style=PROMPT_STYLE,
        )

    async def run(self) -> None:
        """Run the REPL loop."""
        from merlya.commands import get_registry, init_commands
        from merlya.router.handler import handle_message

        # Initialize commands
        init_commands()
        registry = get_registry()

        # Welcome message
        self._show_welcome()

        self.running = True

        while self.running:
            try:
                # Update completion cache
                await self.completer._update_cache()

                # Get input
                user_input = await self.session.prompt_async(
                    [("class:prompt", "Merlya"), ("class:host", " > ")],
                )

                user_input = user_input.strip()
                if not user_input:
                    continue

                # Limit input length to prevent excessive API costs / OOM
                MAX_INPUT_LENGTH = 10000
                if len(user_input) > MAX_INPUT_LENGTH:
                    self.ctx.ui.error(f"Input too long (max {MAX_INPUT_LENGTH} chars)")
                    continue

                # =====================================================
                # SLASH COMMANDS → Fast-path dispatch (0 LLM tokens)
                # =====================================================
                if user_input.startswith("/"):
                    result = await registry.execute(self.ctx, user_input)
                    if result:
                        # Check for special actions (data must be a dict)
                        if isinstance(result.data, dict):
                            if result.data.get("exit"):
                                self.running = False
                                break
                            if result.data.get("new_conversation"):
                                self.orchestrator.reset()
                            if result.data.get("reload_agent"):
                                self._reload_orchestrator()

                        # Display result
                        if result.success:
                            self.ctx.ui.markdown(result.message)
                        else:
                            self.ctx.ui.error(result.message)
                    continue

                # =====================================================
                # FREE TEXT → Orchestrator (LLM delegates to specialists)
                # =====================================================

                # Expand @ mentions (variables → values, secrets → kept as @ref)
                expanded_input = await self._expand_mentions(user_input)

                # Process with Orchestrator
                try:
                    with self.ctx.ui.spinner(self.ctx.t("ui.spinner.agent")):
                        response = await handle_message(self.ctx, self.orchestrator, expanded_input)
                except asyncio.CancelledError:
                    # Handle Ctrl+C during orchestrator execution
                    self.ctx.ui.newline()
                    self.ctx.ui.warning(self.ctx.t("ui.request_cancelled"))
                    continue

                # Display response
                self.ctx.ui.newline()
                self.ctx.ui.markdown(response.message)

                if response.actions_taken:
                    self.ctx.ui.muted(f"\nActions: {', '.join(response.actions_taken)}")

                if response.suggestions:
                    self.ctx.ui.info(f"\nSuggestions: {', '.join(response.suggestions)}")

                # Show handler info in debug mode
                if response.handled_by not in ("orchestrator", "agent"):
                    self.ctx.ui.muted(f"[{response.handled_by}]")

                self.ctx.ui.newline()

            except KeyboardInterrupt:
                # User interrupt: cancel current input/command but keep REPL alive
                self.ctx.ui.newline()
                self.ctx.ui.warning("Interrupted, command cancelled")
                continue

            except asyncio.CancelledError:
                # Graceful shutdown initiated by signal handler
                self.ctx.ui.newline()
                self.ctx.ui.warning("Interrupted, shutting down...")
                self.running = False
                break

            except EOFError:
                self.running = False
                break

            except Exception as e:
                logger.error(f"REPL error: {e}")
                self.ctx.ui.error(f"Error: {e}")

        # Cleanup (may be called again by CLI wrapper, but close() is idempotent)
        try:
            # Shield cleanup from cancellation so we can close resources cleanly
            await asyncio.shield(self.ctx.close())
        except asyncio.CancelledError:
            logger.debug("Cleanup cancelled, retrying close without shield")
            with contextlib.suppress(Exception):
                await self.ctx.close()

    async def _expand_mentions(self, text: str) -> str:
        """
        Expand @ mentions in text.

        @hostname -> kept as-is (agent will resolve from inventory)
        @variable -> variable value (non-sensitive, user-defined)
        @secret   -> kept as-is (resolved only at execution time in ssh_execute)

        SECURITY: Secrets are NEVER expanded here to prevent leaking to LLM.
        The LLM sees @secret-name, and resolution happens in ssh_execute.

        NEW: If a @mention is not found as variable, secret, or host,
        prompt the user to define it inline (issue #40).
        """
        # Find all @ mentions (deduplicated, preserve order)
        seen: set[str] = set()
        mentions: list[str] = []
        for m in re.findall(r"@(\w[\w.-]*)", text):
            if m not in seen:
                seen.add(m)
                mentions.append(m)

        undefined_mentions: list[str] = []

        for mention in mentions:
            # Host references must never be expanded or replaced
            host = await self.ctx.hosts.get_by_name(mention)
            if host:
                continue

            # Check if it's a known secret (never expand secrets)
            if self.ctx.secrets.has(mention):
                continue

            # Try as variable (variables are non-sensitive, OK to expand)
            var = await self.ctx.variables.get(mention)
            if var:
                text = text.replace(f"@{mention}", var.value)
                continue

            undefined_mentions.append(mention)

        # Prompt for undefined mentions (issue #40)
        if undefined_mentions:
            text = await self._prompt_for_undefined_mentions(text, undefined_mentions)

        return text

    # Valid pattern for variable/secret names (must start with letter)
    _VALID_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

    async def _prompt_for_undefined_mentions(self, text: str, undefined: list[str]) -> str:
        """
        Prompt user to define undefined @ mentions inline.

        For each undefined mention, ask if it should be a variable or secret,
        then prompt for the value.
        """
        total = len(undefined)
        for i, mention in enumerate(undefined, 1):
            # Show progress for multiple mentions
            progress = f"[{i}/{total}] " if total > 1 else ""
            self.ctx.ui.warning(
                f"{progress}@{mention} is not defined as a variable, secret, or host."
            )

            # Validate name format before allowing to set
            if not self._VALID_NAME_PATTERN.match(mention):
                self.ctx.ui.muted(
                    f"@{mention} has invalid format (must start with letter, "
                    "contain only letters, numbers, hyphens, underscores). Keeping as-is."
                )
                continue

            # Ask what type it should be
            choice = await self.ctx.ui.prompt(
                f"Define @{mention} as (v)ariable, (s)ecret, (h)ost, or (i)gnore? [v/s/h/i]",
            )

            if not choice:
                choice = "i"

            choice = choice.lower().strip()

            if choice.startswith("v"):
                # Define as variable
                value = await self.ctx.ui.prompt(f"Enter value for @{mention}:")
                if value:
                    try:
                        await self.ctx.variables.set(mention, value)
                        text = text.replace(f"@{mention}", value)
                        self.ctx.ui.success(f"Variable @{mention} set.")
                    except Exception as e:
                        logger.error(f"Failed to set variable @{mention}: {e}")
                        self.ctx.ui.error(f"Failed to set @{mention}: {e}")
                else:
                    self.ctx.ui.muted(f"Skipped @{mention}")

            elif choice.startswith("s"):
                # Define as secret
                value = await self.ctx.ui.prompt_secret(f"Enter secret value for @{mention}:")
                if value:
                    try:
                        self.ctx.secrets.set(mention, value)
                        # Don't expand secrets - keep @mention in text
                        self.ctx.ui.success(f"Secret @{mention} set.")
                    except Exception as e:
                        logger.error(f"Failed to set secret @{mention}: {e}")
                        self.ctx.ui.error(f"Failed to set @{mention}: {e}")
                else:
                    self.ctx.ui.muted(f"Skipped @{mention}")

            elif choice.startswith("h"):
                # Define as host
                hostname = await self.ctx.ui.prompt(
                    f"Enter hostname/IP for @{mention} (e.g., 192.168.1.5):"
                )
                if hostname:
                    try:
                        from merlya.persistence.models import Host

                        # Parse hostname:port if provided
                        port = 22
                        if ":" in hostname:
                            hostname, port_str = hostname.rsplit(":", 1)
                            port = int(port_str)

                        host = Host(name=mention, hostname=hostname, port=port)
                        await self.ctx.hosts.create(host)
                        self.ctx.ui.success(f"Host @{mention} added ({hostname}:{port}).")
                    except Exception as e:
                        logger.error(f"Failed to add host @{mention}: {e}")
                        self.ctx.ui.error(f"Failed to add host @{mention}: {e}")
                else:
                    self.ctx.ui.muted(f"Skipped @{mention}")

            else:
                # Ignore - keep as-is
                self.ctx.ui.muted(f"Keeping @{mention} as-is")

        return text

    def _show_welcome(self) -> None:
        """Show welcome message."""
        env = os.environ.get("MERLYA_ENV", "dev")
        # Get model from orchestrator's provider config
        model_name = self.orchestrator.model_override or self.ctx.config.model.model
        orchestrator_model = f"{self.orchestrator.provider}:{model_name}"
        model_label = format_model_label(
            orchestrator_model,
            self.ctx.config.model.provider,
            self.ctx.config.model.model,
        )
        keyring_status = "✅ OK" if getattr(self.ctx.secrets, "is_secure", False) else "⚠️ fallback"

        status = WelcomeStatus(
            version=self._get_version(),
            env=env,
            session_id=self.session_id,
            model_label=model_label,
            keyring_label=keyring_status,
        )

        hero_lines, warning_lines = build_welcome_lines(self.ctx.t, status)

        self.ctx.ui.welcome_screen(
            title=self.ctx.t("welcome_screen.title"),
            warning_title=self.ctx.t("welcome_screen.warning_title"),
            hero_lines=hero_lines,
            warning_lines=warning_lines,
        )

    def _get_version(self) -> str:
        """Get version string."""
        from merlya import __version__

        return __version__

    def _reload_orchestrator(self) -> None:
        """Reload orchestrator with current model settings."""
        from merlya.agent.orchestrator import Orchestrator

        provider = self.ctx.config.model.provider
        model = self.ctx.config.model.model

        self.orchestrator = Orchestrator(
            context=self.ctx,
            provider=provider,
            model_override=model,
        )
        logger.info(f"🔄 Orchestrator reloaded with {provider}:{model}")


async def run_repl() -> None:
    """
    Main entry point for the REPL.

    Sets up context and runs the loop.

    Architecture:
      "/" commands → Slash command dispatch (fast-path)
      Free text → Orchestrator (LLM delegates to specialists)
    """
    from merlya.agent.orchestrator import Orchestrator
    from merlya.commands import init_commands
    from merlya.core.context import SharedContext
    from merlya.health import run_startup_checks
    from merlya.secrets import load_api_keys_from_keyring
    from merlya.setup import check_first_run, run_setup_wizard

    # Initialize commands
    init_commands()

    # Create context
    ctx = await SharedContext.create()

    # Check first run
    if await check_first_run():
        result = await run_setup_wizard(ctx.ui, ctx)
        if result.completed and result.llm_config:
            # Update config with wizard settings
            ctx.config.model.provider = result.llm_config.provider
            ctx.config.model.model = result.llm_config.model
            ctx.config.model.api_key_env = result.llm_config.api_key_env
            # Save fallback model to router config
            if result.llm_config.fallback_model:
                ctx.config.router.llm_fallback = result.llm_config.fallback_model
            # Save config to disk
            ctx.config.save()
            ctx.ui.success("Configuration saved to ~/.merlya/config.yaml")

    # Load API keys from keyring into environment
    load_api_keys_from_keyring(ctx.config, ctx.secrets)

    # Apply provider-specific environment setup (OpenRouter, Ollama, etc.)
    # This must be called AFTER loading API keys from keyring
    from merlya.config.provider_env import ensure_provider_env

    ensure_provider_env(ctx.config)

    # Initialize components BEFORE health checks so they report correctly
    # 1. Initialize SessionManager
    try:
        import psutil

        from merlya.session import SessionManager
        from merlya.session.context_tier import ContextTier

        # Convert string tier to enum, use RAM-based detection when "auto"
        tier_str = ctx.config.policy.context_tier
        if tier_str and tier_str.lower() != "auto":
            tier = ContextTier.from_string(tier_str)
        else:
            # Auto-detect based on available RAM
            mem = psutil.virtual_memory()
            available_gb = mem.available / (1024**3)
            tier = ContextTier.from_ram_gb(available_gb)
            logger.debug(f"Auto-detected context tier: {tier.value} (RAM: {available_gb:.1f}GB)")

        model = f"{ctx.config.model.provider}:{ctx.config.model.model}"
        SessionManager(model=model, default_tier=tier)
        logger.debug(f"SessionManager initialized with tier={tier.value}")
    except Exception as e:
        logger.debug(f"SessionManager init skipped: {e}")

    # 2. Initialize MCPManager (if configured)
    try:
        if ctx.config.mcp and ctx.config.mcp.servers:
            await ctx.get_mcp_manager()
            logger.debug("MCPManager initialized")
    except Exception as e:
        logger.debug(f"MCPManager init skipped: {e}")

    # Run health checks (only show details in debug mode)
    health = await run_startup_checks()
    is_debug = ctx.config.logging.console_level == "debug"

    if is_debug:
        ctx.ui.info(ctx.t("startup.health_checks"))
        for check in health.checks:
            ctx.ui.health_status(check.name, check.status, check.message)

    if not health.can_start:
        ctx.ui.error("Cannot start: critical checks failed")
        return

    ctx.health = health

    # Create Orchestrator (main entry point for LLM processing)
    provider = ctx.config.model.provider
    model_override = ctx.config.model.model
    orchestrator = Orchestrator(
        context=ctx,
        provider=provider,
        model_override=model_override,
    )
    if is_debug:
        ctx.ui.info(ctx.t("startup.orchestrator_ready", provider=provider))

    # Run REPL
    repl = REPL(ctx, orchestrator)
    await repl.run()
