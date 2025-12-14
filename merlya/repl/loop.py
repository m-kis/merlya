"""
Merlya REPL - Main loop.

Interactive console with autocompletion.
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

    from merlya.agent import MerlyaAgent
    from merlya.config.models import RouterConfig
    from merlya.core.context import SharedContext
    from merlya.router import IntentRouter

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
    provider_label: str
    model_label: str
    router_label: str
    keyring_label: str


def format_model_labels(agent_model: str | None, provider: str, model: str) -> tuple[str, str]:
    """
    Format provider and model labels for the welcome screen.

    Uses the agent model when available, otherwise falls back to config values.
    """
    model_value = agent_model or f"{provider}:{model}"
    if ":" in model_value:
        provider_name, model_name = model_value.split(":", 1)
    else:
        provider_name, model_name = provider, model_value

    provider_label = f"✅ {provider_name} ({model_name})"
    model_label = f"✅ {provider_name}:{model_name}"
    return provider_label, model_label


def format_router_label(router: IntentRouter | None, router_config: RouterConfig) -> str:
    """Describe the router mode for the welcome screen."""
    fallback = router_config.llm_fallback or "pattern"
    classifier = getattr(router, "classifier", None)

    if classifier and getattr(classifier, "model_loaded", False):
        model_id = getattr(classifier, "model_id", None)
        if model_id:
            return f"✅ local ({model_id})"
        return "✅ local"

    if router_config.type == "llm":
        return f"🔀 {fallback}"

    return f"⚠️ local unavailable (fallback {fallback})"


def build_welcome_lines(
    translate: Callable[..., str],
    status: WelcomeStatus,
) -> tuple[list[str], list[str]]:
    """Assemble hero and warning lines for the welcome screen."""
    hero_lines = [
        translate("welcome_screen.subtitle", version=status.version),
        "",
        translate("welcome_screen.env_session", env=status.env, session=status.session_id),
        "",
        translate("welcome_screen.provider", provider=status.provider_label),
        translate("welcome_screen.model", model=status.model_label),
        translate("welcome_screen.router", router=status.router_label),
        translate("welcome_screen.keyring", keyring=status.keyring_label),
        "",
        translate("welcome_screen.commands_hint"),
        "",
        translate("welcome_screen.command_help"),
        translate("welcome_screen.command_conv"),
        translate("welcome_screen.command_new"),
        translate("welcome_screen.command_scan"),
        translate("welcome_screen.command_exit"),
        "",
        translate("welcome_screen.prompt"),
        "",
        translate("welcome_screen.feedback"),
    ]

    tips = [
        translate("welcome_screen.tip_specific"),
        translate("welcome_screen.tip_target"),
        translate("welcome_screen.tip_context"),
    ]

    warning_lines = [
        translate("welcome_screen.warning_header"),
        "",
        translate("welcome_screen.warning_body"),
        "",
        translate("welcome_screen.warning_tips_title"),
        *[f"• {tip}" for tip in tips],
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
    """

    def __init__(
        self,
        ctx: SharedContext,
        agent: MerlyaAgent,
    ) -> None:
        """
        Initialize REPL.

        Args:
            ctx: Shared context.
            agent: Main agent.
        """
        self.ctx = ctx
        self.agent = agent
        self.completer = MerlyaCompleter(ctx)
        self.running = False
        self.router: IntentRouter | None = None
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

        # Initialize commands
        init_commands()
        registry = get_registry()

        # Router prepared during startup
        self.router = self.ctx.router

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

                # Check for slash command
                if user_input.startswith("/"):
                    result = await registry.execute(self.ctx, user_input)
                    if result:
                        # Check for special actions (data must be a dict)
                        if isinstance(result.data, dict):
                            if result.data.get("exit"):
                                self.running = False
                                break
                            if result.data.get("new_conversation"):
                                self.agent.clear_history()
                            if result.data.get("load_conversation"):
                                self.agent.load_conversation(result.data["load_conversation"])
                            if result.data.get("reload_agent"):
                                self._reload_agent()

                        # Display result
                        if result.success:
                            self.ctx.ui.markdown(result.message)
                        else:
                            self.ctx.ui.error(result.message)
                    continue

                # Route and process with agent
                if not self.router:
                    raise RuntimeError("Router not initialized")
                with self.ctx.ui.spinner(self.ctx.t("ui.spinner.routing")):
                    route_result = await self.router.route(user_input)

                # Expand @ mentions (only for non-fast-path)
                if not route_result.is_fast_path:
                    expanded_input = await self._expand_mentions(user_input)
                else:
                    expanded_input = user_input

                # Handle via fast path, skill, or agent
                try:
                    from merlya.router.handler import handle_user_message

                    # Use spinner only for non-fast-path (fast path is instant)
                    if route_result.is_fast_path:
                        response = await handle_user_message(
                            self.ctx, self.agent, expanded_input, route_result
                        )
                    else:
                        with self.ctx.ui.spinner(self.ctx.t("ui.spinner.agent")):
                            response = await handle_user_message(
                                self.ctx, self.agent, expanded_input, route_result
                            )
                except asyncio.CancelledError:
                    # Handle Ctrl+C during agent execution
                    self.ctx.ui.newline()
                    self.ctx.ui.warning("Request cancelled")
                    continue

                # Display response
                self.ctx.ui.newline()
                self.ctx.ui.markdown(response.message)

                if response.actions_taken:
                    self.ctx.ui.muted(f"\nActions: {', '.join(response.actions_taken)}")

                if response.suggestions:
                    self.ctx.ui.info(f"\nSuggestions: {', '.join(response.suggestions)}")

                # Show handler info in debug mode
                if response.handled_by != "agent":
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
        self.ctx.ui.info("Goodbye!")

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
                f"Define @{mention} as (v)ariable, (s)ecret, or (i)gnore? [v/s/i]",
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

            else:
                # Ignore - keep as-is
                self.ctx.ui.muted(f"Keeping @{mention} as-is")

        return text

    def _show_welcome(self) -> None:
        """Show welcome message."""
        env = os.environ.get("MERLYA_ENV", "dev")
        provider_label, model_label = format_model_labels(
            getattr(self.agent, "model", None),
            self.ctx.config.model.provider,
            self.ctx.config.model.model,
        )
        router_label = format_router_label(self.router, self.ctx.config.router)
        keyring_status = (
            "✅ Keyring"
            if getattr(self.ctx.secrets, "is_secure", False)
            else self.ctx.t("welcome_screen.keyring_fallback")
        )

        status = WelcomeStatus(
            version=self._get_version(),
            env=env,
            session_id=self.session_id,
            provider_label=provider_label,
            model_label=model_label,
            router_label=router_label,
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
        try:
            from importlib.metadata import version

            return version("merlya")
        except Exception:
            return "0.5.6"

    def _reload_agent(self) -> None:
        """Reload agent with current model settings."""
        from merlya.agent import MerlyaAgent

        model = f"{self.ctx.config.model.provider}:{self.ctx.config.model.model}"
        self.agent = MerlyaAgent(self.ctx, model=model)
        self.agent.clear_history()


async def run_repl() -> None:
    """
    Main entry point for the REPL.

    Sets up context and runs the loop.
    """
    from merlya.agent import MerlyaAgent
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
            # Set router fallback to use same provider
            if result.llm_config.fallback_model:
                ctx.config.router.llm_fallback = result.llm_config.fallback_model
            # Save config to disk
            ctx.config.save()
            ctx.ui.success("Configuration saved to ~/.merlya/config.yaml")

    # Load API keys from keyring into environment
    load_api_keys_from_keyring(ctx.config, ctx.secrets)

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

    # 2. Load skills
    try:
        from merlya.skills import SkillLoader

        loader = SkillLoader()
        loader.load_all()
        logger.debug("Skills loaded")
    except Exception as e:
        logger.debug(f"Skills loading skipped: {e}")

    # 3. Initialize MCPManager (if configured)
    try:
        if ctx.config.mcp and ctx.config.mcp.servers:
            await ctx.get_mcp_manager()
            logger.debug("MCPManager initialized")
    except Exception as e:
        logger.debug(f"MCPManager init skipped: {e}")

    # Run health checks
    ctx.ui.info(ctx.t("startup.health_checks"))
    health = await run_startup_checks()

    for check in health.checks:
        ctx.ui.health_status(check.name, check.status, check.message)

    if not health.can_start:
        ctx.ui.error("Cannot start: critical checks failed")
        return

    ctx.health = health

    # Initialize intent router using health tier and config
    await ctx.init_router(health.model_tier)
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

    # Run REPL
    repl = REPL(ctx, agent)
    await repl.run()
