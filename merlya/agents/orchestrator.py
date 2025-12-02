"""
Unified Multi-Agent Orchestrator.

Consolidates Ag2Orchestrator and EnhancedAg2Orchestrator into a single
configurable orchestrator following DRY, SRP, and OCP principles.

Uses autogen-agentchat 0.7+ async API.

Modes:
- BASIC: Single engineer agent (fast, simple tasks)
- ENHANCED: Multi-agent team with selector (complex tasks)
"""
import os
from enum import Enum
from typing import Any, Callable, List, Optional

from rich.console import Console

from merlya.agents import autogen_tools, knowledge_tools
from merlya.agents.base_orchestrator import BaseOrchestrator
from merlya.agents.orchestrator_service.intent import IntentParser
from merlya.agents.orchestrator_service.planner import ExecutionPlanner
from merlya.llm.model_config import ModelConfig
from merlya.utils.config import ConfigManager
from merlya.utils.logger import logger

# Optional imports
try:
    from merlya.utils.verbosity import get_verbosity
    HAS_VERBOSITY = True
except ImportError:
    HAS_VERBOSITY = False

try:
    from merlya.knowledge.falkordb_client import FalkorDBClient, FalkorDBConfig
    HAS_FALKORDB = True
except ImportError:
    HAS_FALKORDB = False

# New autogen-agentchat 0.7+ imports
try:
    from autogen_ext.models.openai import OpenAIChatCompletionClient
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False
    logger.warning("⚠️ autogen-agentchat not installed. Orchestrator will not work.")


class OrchestratorMode(Enum):
    """Orchestrator operating modes."""
    BASIC = "basic"           # Single engineer agent
    ENHANCED = "enhanced"     # Multi-agent team


class Orchestrator(BaseOrchestrator):
    """
    Unified Multi-Agent Orchestrator.

    Uses autogen-agentchat 0.7+ async API.

    Combines the functionality of Ag2Orchestrator and EnhancedAg2Orchestrator
    into a single, configurable class.

    Args:
        mode: Operating mode (BASIC or ENHANCED)
        env: Environment name (dev, staging, prod)
        language: Response language (en, fr)

    Example:
        # Simple mode for quick tasks
        orchestrator = Orchestrator(mode=OrchestratorMode.BASIC)

        # Enhanced mode with multi-agent team
        orchestrator = Orchestrator(mode=OrchestratorMode.ENHANCED)
    """

    def __init__(
        self,
        mode: OrchestratorMode = OrchestratorMode.BASIC,
        env: str = "dev",
        language: str = "en",
        console: Optional[Console] = None,
    ):
        super().__init__(env=env, language=language)

        if not HAS_AUTOGEN:
            raise ImportError(
                "autogen-agentchat is required. "
                "Run 'pip install pyautogen autogen-ext[openai]'."
            )

        self.mode = mode
        self.console = console or Console()
        self.config_manager = ConfigManager()

        # Verbosity (optional)
        self.verbosity = get_verbosity() if HAS_VERBOSITY else None

        # Intent Parser (uses local embeddings first, LLM router as fallback)
        self.intent_parser = IntentParser(
            self.console,
            self.verbosity,
            llm_router=self.llm_router
        )
        self.current_priority: Any = None

        # Knowledge graph (ENHANCED mode only)
        self.knowledge_db: FalkorDBClient | None = None
        if mode == OrchestratorMode.ENHANCED and HAS_FALKORDB:
            self._init_knowledge_db()

        # Initialize tools
        autogen_tools.initialize_autogen_tools(
            executor=self.executor,
            context_manager=self.context_manager,
            permissions=self.permissions,
            context_memory=getattr(self.context_manager, 'memory', None),
            credentials=self.credentials,
        )

        # Configure model client
        self.model_client = self._create_model_client()

        # Collect tools as callables
        self._tools = self._collect_tools()

        # Execution Planner
        self.planner = ExecutionPlanner(
            model_client=self.model_client,
            tools=self._tools,
            env=self.env,
            console=self.console
        )

        # Initialize agents
        self.planner.init_agents(mode.value, self.knowledge_db)

        logger.info(f"Orchestrator initialized in {mode.value} mode")

    # =========================================================================
    # Model Client Configuration (new API)
    # =========================================================================

    def _create_model_client(self) -> "OpenAIChatCompletionClient":
        """Create OpenAI-compatible model client.

        Priority: Environment variables > Config file > Defaults
        Provider is determined solely by ModelConfig (unified config).
        """
        # Load model config from ~/.merlya/config.json
        model_config = ModelConfig()
        config_provider = model_config.get_provider()

        # Determine provider: env var overrides config
        provider = os.getenv("MERLYA_PROVIDER", "").lower() or config_provider

        # ✅ FIX: Get model for THE ACTUAL PROVIDER, not config_provider
        # This ensures we use the correct model for the selected provider

        # Ollama (local LLM)
        if provider == "ollama" or os.getenv("OLLAMA_MODEL"):
            model = os.getenv("OLLAMA_MODEL") or model_config.get_model("ollama")
            logger.info(f"✅ Using Ollama: {model}")
            return OpenAIChatCompletionClient(
                model=model,
                api_key="ollama",
                base_url="http://localhost:11434/v1",
                model_info={
                    "vision": False,
                    "function_calling": True,
                    "json_output": True,
                    "family": "unknown",
                    "structured_output": True,
                },
            )

        if provider == "openrouter" or os.getenv("OPENROUTER_API_KEY"):
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError("OPENROUTER_API_KEY not set.")
            # ✅ FIX: Get model for "openrouter", not config_provider
            model = os.getenv("OPENROUTER_MODEL") or model_config.get_model("openrouter")
            logger.info(f"✅ Using OpenRouter: {model}")
            return OpenAIChatCompletionClient(
                model=model,
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                model_info={
                    "vision": False,
                    "function_calling": True,
                    "json_output": True,
                    "family": "unknown",
                    "structured_output": True,
                },
            )

        if provider == "anthropic" or os.getenv("ANTHROPIC_API_KEY"):
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set.")
            # ✅ FIX: Get model for "anthropic", not config_provider
            model = os.getenv("ANTHROPIC_MODEL") or model_config.get_model("anthropic")
            logger.info(f"✅ Using Anthropic: {model}")
            return OpenAIChatCompletionClient(
                model=model,
                api_key=api_key,
                base_url="https://api.anthropic.com/v1",
                model_info={
                    "vision": True,
                    "function_calling": True,
                    "json_output": True,
                    "family": "unknown",
                    "structured_output": True,
                },
            )

        if provider == "openai" or os.getenv("OPENAI_API_KEY"):
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set.")
            # ✅ FIX: Get model for "openai", not config_provider
            model = os.getenv("OPENAI_MODEL") or model_config.get_model("openai")
            logger.info(f"✅ Using OpenAI: {model}")
            return OpenAIChatCompletionClient(
                model=model,
                api_key=api_key,
            )

        raise ValueError(
            "No AI provider configured. Set MERLYA_PROVIDER and the corresponding API key, "
            "or use Ollama (MERLYA_PROVIDER=ollama with OLLAMA_MODEL)."
        )

    def reload_agents(self) -> None:
        """Reload agents with current configuration."""
        import asyncio

        logger.info("Reloading agents...")

        # Close old model client to prevent "Event loop is closed" errors
        # The client uses httpx internally which has async connections
        old_client = self.model_client
        if old_client is not None:
            try:
                # Try to get the current event loop, or create a new one
                try:
                    loop = asyncio.get_running_loop()
                    # If we're in an async context, schedule the close
                    loop.create_task(old_client.close())
                except RuntimeError:
                    # No running loop - create a new one just for cleanup
                    asyncio.run(old_client.close())
            except Exception as e:
                # Log but don't fail - the old client may already be closed
                logger.debug(f"Could not close old model client: {e}")

        self.model_client = self._create_model_client()
        self.planner = ExecutionPlanner(
            model_client=self.model_client,
            tools=self._tools,
            env=self.env,
            console=self.console
        )
        self.planner.init_agents(self.mode.value, self.knowledge_db)
        logger.info("Agents reloaded.")

    # =========================================================================
    # Tool Collection (new API - tools as callables)
    # =========================================================================

    def _collect_tools(self) -> List[Callable[..., Any]]:
        """Collect all tools as callable functions."""
        tools: List[Callable[..., Any]] = [
            # Core tools
            autogen_tools.scan_host,
            autogen_tools.execute_command,
            autogen_tools.check_permissions,
            autogen_tools.get_infrastructure_context,
            autogen_tools.list_hosts,
            autogen_tools.audit_host,
            autogen_tools.add_route,
            autogen_tools.analyze_security_logs,
            # File operations
            autogen_tools.read_remote_file,
            autogen_tools.write_remote_file,
            autogen_tools.tail_logs,
            autogen_tools.glob_files,
            autogen_tools.grep_files,
            autogen_tools.find_file,
            # Web tools
            autogen_tools.web_search,
            autogen_tools.web_fetch,
            # Interaction & Learning
            autogen_tools.ask_user,
            autogen_tools.get_user_variables,
            autogen_tools.get_variable_value,
            autogen_tools.remember_skill,
            autogen_tools.recall_skill,
            autogen_tools.request_elevation,
            autogen_tools.save_report,
            # Knowledge Graph tools
            knowledge_tools.record_incident,
            knowledge_tools.search_knowledge,
            knowledge_tools.get_solution_suggestion,
            knowledge_tools.graph_stats,
            # System info
            autogen_tools.disk_info,
            autogen_tools.memory_info,
            autogen_tools.network_connections,
            autogen_tools.process_list,
            autogen_tools.service_control,
            # Containers
            autogen_tools.docker_exec,
            autogen_tools.kubectl_exec,
        ]
        return tools

    # =========================================================================
    # Knowledge Graph (ENHANCED mode)
    # =========================================================================

    def _init_knowledge_db(self) -> None:
        """Initialize FalkorDB connection."""
        try:
            config = FalkorDBConfig(
                graph_name="merlya_knowledge",
                auto_start_docker=True,
            )
            self.knowledge_db = FalkorDBClient(config)
            if self.knowledge_db.connect():
                logger.info("FalkorDB connected")
                self._ensure_knowledge_schema()
            else:
                logger.warning("FalkorDB not available")
                self.knowledge_db = None
        except Exception as e:
            logger.warning(f"FalkorDB init failed: {e}")
            self.knowledge_db = None

    def _ensure_knowledge_schema(self) -> None:
        """Ensure knowledge graph indexes exist."""
        if not self.knowledge_db:
            return
        try:
            self.knowledge_db.query("CREATE INDEX IF NOT EXISTS FOR (h:Host) ON (h.hostname)")
            self.knowledge_db.query("CREATE INDEX IF NOT EXISTS FOR (i:Incident) ON (i.created_at)")
        except Exception as e:
            logger.warning(f"Failed to create schema: {e}")

    # =========================================================================
    # Session Management
    # =========================================================================

    def reset_session(self) -> None:
        """Reset the chat session."""
        # New API doesn't have agent.reset(), just reinitialize
        self.planner.init_agents(self.mode.value, self.knowledge_db)
        self.console.print("[dim]🔄 Session reset[/dim]")

    async def shutdown(self) -> None:
        """Clean shutdown of orchestrator resources.

        Closes the model client to prevent 'Event loop is closed' errors
        from httpx connections during garbage collection.
        """
        if self.model_client is not None:
            try:
                await self.model_client.close()
                logger.debug("Model client closed successfully")
            except Exception as e:
                logger.debug(f"Error closing model client: {e}")

    def shutdown_sync(self) -> None:
        """Synchronous wrapper for shutdown.

        Use this when not in an async context (e.g., REPL exit).
        """
        import asyncio

        try:
            asyncio.run(self.shutdown())
        except RuntimeError as e:
            # Event loop may already be closed
            logger.debug(f"Sync shutdown skipped: {e}")

    # =========================================================================
    # Error Handling
    # =========================================================================

    def _handle_execution_error(self, error: Exception) -> str:
        """
        Classify and format execution errors with actionable messages.

        Args:
            error: The exception that occurred

        Returns:
            User-friendly error message
        """
        error_str = str(error)

        # Check for function calling / tool use not supported
        if "No endpoints found that support tool use" in error_str or "404" in error_str:
            logger.error("❌ Model doesn't support function calling: {}", error, exc_info=True)
            return self._build_function_calling_error_message()

        # Generic error fallback
        logger.error("❌ Orchestrator failed: {}", error, exc_info=True)
        return f"❌ Error: {error_str}"

    def _build_function_calling_error_message(self) -> str:
        """
        Build actionable error message when model doesn't support function calling.

        Returns:
            User-friendly error message with specific solutions
        """
        model_config = ModelConfig()
        current_provider = model_config.get_provider()
        current_model = model_config.get_model(current_provider)

        message_parts = [
            "❌ Model Error: The current model doesn't support function calling (required for multi-agent mode)",
            "",
            "Current configuration:",
            f"  • Provider: {current_provider}",
            f"  • Model: {current_model}",
            "",
            "💡 Solutions:",
        ]

        # Suggest provider-specific solutions
        if current_provider == "openrouter":
            message_parts.extend([
                "  1. Switch to a compatible OpenRouter model:",
                "     /model set openrouter google/gemini-2.0-flash-exp:free",
                "     /model set openrouter anthropic/claude-3.5-sonnet",
                "     /model set openrouter qwen/qwen-2.5-72b-instruct",
                "",
                "  2. Switch to Ollama (if configured):",
                "     /model provider ollama",
            ])
        elif current_provider == "ollama":
            message_parts.extend([
                "  1. Verify Ollama model supports function calling",
                "  2. Try a different Ollama model:",
                "     /model set ollama qwen2.5-coder:latest",
                "",
                "  3. Switch to a cloud provider:",
                "     /model provider openrouter",
            ])
        elif current_provider == "anthropic":
            message_parts.extend([
                "  1. Use Claude without date suffix:",
                "     /model set anthropic claude-3-5-sonnet-20241022",
                "",
                "  2. Switch to OpenRouter for more model options:",
                "     /model provider openrouter",
            ])
        else:
            message_parts.extend([
                "  1. Check available models: /model list",
                "  2. Switch provider: /model provider <provider>",
                "  3. Set compatible model: /model set <provider> <model>",
            ])

        message_parts.extend([
            "",
            "📖 For more information:",
            "   /model help",
        ])

        return "\n".join(message_parts)

    # =========================================================================
    # Main Processing (new async API)
    # =========================================================================

    async def process_request(
        self,
        user_query: str,
        auto_confirm: bool = False,
        dry_run: bool = False,
        **kwargs
    ) -> str:
        """
        Process request using Multi-Agent conversation.

        Args:
            user_query: User's request
            auto_confirm: Auto-confirm critical actions
            dry_run: Preview only, don't execute
            conversation_history: Recent conversation context (list of {role, content})

        Returns:
            Agent response
        """
        if dry_run:
            return f"🔍 Dry run: Would process in {self.mode.value} mode"

        # Step 1: Full classification (priority + intent) - use AI when available
        # Use original_query for triage if provided (avoids exposing resolved credentials)
        system_state = kwargs.get("system_state")
        original_query = kwargs.get("original_query")
        triage_query = original_query if original_query else user_query

        try:
            triage_context = await self.intent_parser.classify_full_async(triage_query, system_state)
        except Exception as e:
            logger.error(f"❌ Classification failed: {e}", exc_info=True)
            # Fallback: process without triage context
            conversation_history = kwargs.get("conversation_history", [])
            try:
                return await self.planner.execute_basic(user_query, conversation_history)
            except Exception as fallback_error:
                return self._handle_execution_error(fallback_error)

        # Store for backward compatibility
        self.current_priority = triage_context.priority_result

        # Step 2: Display triage with intent
        self.intent_parser.display_full_triage(triage_context)

        # Log with defensive attribute access
        priority_name = getattr(
            getattr(triage_context.priority_result, "priority", None), "name", "UNKNOWN"
        )
        intent_value = getattr(triage_context.intent, "value", "unknown") if triage_context.intent else "unknown"
        logger.info(
            f"🎯 Request classified as {priority_name} "
            f"(intent: {intent_value}, mode: {self.mode.value})"
        )

        # Step 3: Get conversation history for context
        conversation_history = kwargs.get("conversation_history", [])

        # Step 4: Execute based on mode (with tool restrictions and intent)
        try:
            allowed_tools = triage_context.allowed_tools

            # Fetch knowledge context if in ENHANCED mode
            knowledge_context = None
            if self.mode == OrchestratorMode.ENHANCED and HAS_FALKORDB:
                try:
                    # Search for relevant knowledge using triage_query to avoid
                    # exposing resolved credentials in search
                    knowledge_context = knowledge_tools.search_knowledge(triage_query, limit=3)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to fetch knowledge context: {e}")

            if self.mode == OrchestratorMode.ENHANCED:
                result = await self.planner.execute_enhanced(
                    user_query,
                    priority_name,  # Already extracted with defensive access above
                    conversation_history,
                    allowed_tools=allowed_tools,
                    intent=intent_value,  # Pass intent for behavior adaptation
                    knowledge_context=knowledge_context,
                )
            else:
                result = await self.planner.execute_basic(
                    user_query,
                    conversation_history,
                    allowed_tools=allowed_tools,
                    intent=intent_value,  # Pass intent for behavior adaptation
                    priority=priority_name,  # Pass priority for behavior adaptation
                )

            # Step 5: Implicit positive feedback - classification was used successfully
            # After ~3 successful uses, pattern becomes trusted (confidence >= 0.7)
            self.intent_parser.confirm_last_classification()

            return result

        except Exception as e:
            return self._handle_execution_error(e)

    async def chat_continue(self, message: str) -> str:
        """Continue conversation (BASIC mode compatibility)."""
        return await self.planner.execute_basic(message)


# =============================================================================
# Factory function for easy instantiation
# =============================================================================

def create_orchestrator(
    mode: str = "basic",
    env: str = "dev",
    language: str = "en",
    console: Optional[Console] = None,
) -> Orchestrator:
    """
    Factory function to create orchestrator.

    Args:
        mode: "basic" or "enhanced"
        env: Environment name
        language: Response language
        console: Optional existing console

    Returns:
        Configured Orchestrator instance
    """
    mode_enum = OrchestratorMode(mode.lower())
    return Orchestrator(mode=mode_enum, env=env, language=language, console=console)
