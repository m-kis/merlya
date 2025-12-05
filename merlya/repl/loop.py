"""
Merlya REPL - Main loop.

Interactive console with autocompletion.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from merlya.agent import MerlyaAgent
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


class MerlyaCompleter(Completer):
    """
    Autocompletion for Merlya REPL.

    Supports:
    - Slash commands (/help, /hosts, etc.)
    - Host mentions (@hostname)
    - Variable mentions (@variable)
    """

    def __init__(self, ctx: SharedContext) -> None:
        """Initialize completer."""
        self.ctx = ctx
        self._hosts_cache: list[str] = []
        self._variables_cache: list[str] = []
        self._last_cache_update: float = 0.0

    async def _update_cache(self) -> None:
        """Update completion cache."""
        import time

        now = time.time()
        if now - self._last_cache_update < 30:  # Cache for 30 seconds
            return

        try:
            hosts = await self.ctx.hosts.get_all()
            self._hosts_cache = [h.name for h in hosts]

            variables = await self.ctx.variables.get_all()
            self._variables_cache = [v.name for v in variables]

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

        # Welcome message
        self._show_welcome()

        self.running = True

        while self.running:
            try:
                # Update completion cache
                await self.completer._update_cache()

                # Get input
                user_input = await self.session.prompt_async(
                    [("class:prompt", "merlya"), ("class:host", " > ")],
                )

                user_input = user_input.strip()
                if not user_input:
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

                        # Display result
                        if result.success:
                            self.ctx.ui.markdown(result.message)
                        else:
                            self.ctx.ui.error(result.message)
                    continue

                # Route and process with agent
                from merlya.router import IntentRouter

                router = IntentRouter()
                await router.initialize()

                route_result = await router.route(user_input)

                # Expand @ mentions
                expanded_input = await self._expand_mentions(user_input)

                # Run agent
                response = await self.agent.run(expanded_input, route_result)

                # Display response
                self.ctx.ui.newline()
                self.ctx.ui.markdown(response.message)

                if response.actions_taken:
                    self.ctx.ui.muted(f"\nActions: {', '.join(response.actions_taken)}")

                if response.suggestions:
                    self.ctx.ui.info(f"\nSuggestions: {', '.join(response.suggestions)}")

                self.ctx.ui.newline()

            except KeyboardInterrupt:
                self.ctx.ui.newline()
                continue

            except EOFError:
                self.running = False
                break

            except Exception as e:
                logger.error(f"REPL error: {e}")
                self.ctx.ui.error(f"Error: {e}")

        # Cleanup
        await self.ctx.close()
        self.ctx.ui.info("Goodbye!")

    async def _expand_mentions(self, text: str) -> str:
        """
        Expand @ mentions in text.

        @hostname -> resolved host info
        @variable -> variable value
        """
        # Find all @ mentions
        mentions = re.findall(r"@(\w[\w.-]*)", text)

        for mention in mentions:
            # Try as variable first
            var = await self.ctx.variables.get(mention)
            if var:
                text = text.replace(f"@{mention}", var.value)
                continue

            # Try as secret
            secret = self.ctx.secrets.get(mention)
            if secret:
                text = text.replace(f"@{mention}", secret)
                continue

            # Keep as host reference (agent will resolve)

        return text

    def _show_welcome(self) -> None:
        """Show welcome message."""
        self.ctx.ui.panel(
            f"""
Merlya v{self._get_version()} - AI Infrastructure Assistant

Type your request or use /help for commands.
Use @hostname to reference hosts, @variable for variables.
            """,
            title="Welcome",
            style="info",
        )

    def _get_version(self) -> str:
        """Get version string."""
        try:
            from importlib.metadata import version

            return version("merlya")
        except Exception:
            return "0.5.0"


async def run_repl() -> None:
    """
    Main entry point for the REPL.

    Sets up context and runs the loop.
    """
    from merlya.agent import MerlyaAgent
    from merlya.commands import init_commands
    from merlya.core.context import SharedContext
    from merlya.health import run_startup_checks
    from merlya.setup import check_first_run, run_setup_wizard

    # Initialize commands
    init_commands()

    # Create context
    ctx = await SharedContext.create()

    # Check first run
    if await check_first_run():
        result = await run_setup_wizard(ctx.ui)
        if result.completed and result.llm_config:
            # Update config with wizard settings
            ctx.config.model.provider = result.llm_config.provider
            ctx.config.model.model = result.llm_config.model
            ctx.config.model.api_key_env = result.llm_config.api_key_env
            # Save config to disk
            ctx.config.save()
            ctx.ui.success("Configuration saved to ~/.merlya/config.yaml")

    # Run health checks
    ctx.ui.info("Running health checks...")
    health = await run_startup_checks()

    for check in health.checks:
        ctx.ui.health_status(check.name, check.status, check.message)

    if not health.can_start:
        ctx.ui.error("Cannot start: critical checks failed")
        return

    ctx.health = health

    # Create agent
    model = f"{ctx.config.model.provider}:{ctx.config.model.model}"
    agent = MerlyaAgent(ctx, model=model)

    # Run REPL
    repl = REPL(ctx, agent)
    await repl.run()
