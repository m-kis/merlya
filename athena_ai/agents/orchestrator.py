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
from typing import Callable

from rich.console import Console
from rich.panel import Panel

from athena_ai.agents import autogen_tools, knowledge_tools
from athena_ai.agents.base_orchestrator import BaseOrchestrator
from athena_ai.triage import (
    PriorityClassifier,
    PriorityResult,
    describe_behavior,
    get_behavior,
)
from athena_ai.utils.config import ConfigManager
from athena_ai.utils.logger import logger

# Optional imports
try:
    from athena_ai.utils.verbosity import VerbosityLevel, get_verbosity
    HAS_VERBOSITY = True
except ImportError:
    HAS_VERBOSITY = False

try:
    from athena_ai.knowledge.falkordb_client import FalkorDBClient, FalkorDBConfig
    HAS_FALKORDB = True
except ImportError:
    HAS_FALKORDB = False

# New autogen-agentchat 0.7+ imports
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
    from autogen_ext.models.openai import OpenAIChatCompletionClient
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False
    logger.warning("autogen-agentchat not installed. Orchestrator will not work.")


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
    ):
        super().__init__(env=env, language=language)

        if not HAS_AUTOGEN:
            raise ImportError(
                "autogen-agentchat is required. "
                "Run 'pip install pyautogen autogen-ext[openai]'."
            )

        self.mode = mode
        self.console = Console()
        self.config_manager = ConfigManager()

        # Verbosity (optional)
        self.verbosity = get_verbosity() if HAS_VERBOSITY else None

        # Priority classification
        self.priority_classifier = PriorityClassifier()
        self.current_priority: PriorityResult | None = None

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

        # Initialize agents based on mode
        self._init_agents()

        # Team for ENHANCED mode
        self.team = None
        if mode == OrchestratorMode.ENHANCED:
            self._init_team()

        logger.info(f"Orchestrator initialized in {mode.value} mode")

    # =========================================================================
    # Model Client Configuration (new API)
    # =========================================================================

    def _create_model_client(self) -> "OpenAIChatCompletionClient":
        """Create OpenAI-compatible model client."""
        # Check for local LLM (Ollama) - via config or env var
        use_ollama = (
            self.config_manager.use_local_llm or
            os.getenv("ATHENA_PROVIDER", "").lower() == "ollama" or
            os.getenv("OLLAMA_MODEL")
        )

        if use_ollama:
            model = (
                os.getenv("OLLAMA_MODEL") or
                self.config_manager.local_llm_model or
                "llama3.2"
            )
            logger.info(f"Using Local LLM (Ollama): {model}")
            # Ollama models require model_info since they're not recognized by default
            return OpenAIChatCompletionClient(
                model=model,
                api_key="ollama",  # Ollama doesn't need a real key
                base_url="http://localhost:11434/v1",
                model_info={
                    "vision": False,
                    "function_calling": True,
                    "json_output": True,
                    "family": "unknown",
                    "structured_output": True,
                },
            )

        # Cloud LLM (OpenRouter, Anthropic, OpenAI)
        provider = os.getenv("ATHENA_PROVIDER", "").lower()

        if provider == "openrouter" or os.getenv("OPENROUTER_API_KEY"):
            api_key = os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError("OPENROUTER_API_KEY not set.")
            model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
            logger.info(f"Using OpenRouter: {model}")
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
            model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
            logger.info(f"Using Anthropic: {model}")
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
            model = os.getenv("OPENAI_MODEL", "gpt-4o")
            logger.info(f"Using OpenAI: {model}")
            # OpenAI models are recognized, no need for model_info
            return OpenAIChatCompletionClient(
                model=model,
                api_key=api_key,
            )

        raise ValueError(
            "No AI provider configured. Set ATHENA_PROVIDER and the corresponding API key, "
            "or use Ollama (ATHENA_PROVIDER=ollama with OLLAMA_MODEL)."
        )

    def reload_agents(self) -> None:
        """Reload agents with current configuration."""
        logger.info("Reloading agents...")
        self.model_client = self._create_model_client()
        self._init_agents()
        if self.mode == OrchestratorMode.ENHANCED:
            self._init_team()
        logger.info("Agents reloaded.")

    # =========================================================================
    # Tool Collection (new API - tools as callables)
    # =========================================================================

    def _collect_tools(self) -> list[Callable]:
        """Collect all tools as callable functions."""
        tools = [
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
            autogen_tools.remember_skill,
            autogen_tools.recall_skill,
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
                graph_name="athena_knowledge",
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
    # Agent Initialization (new API)
    # =========================================================================

    def _init_agents(self) -> None:
        """Initialize agents based on mode."""
        # Engineer (main agent with tools)
        self.engineer = AssistantAgent(
            name="DevSecOps_Engineer",
            model_client=self.model_client,
            tools=self._tools,
            system_message=self._get_engineer_prompt(),
            description="Expert DevSecOps engineer who executes infrastructure tasks using tools.",
        )

        # Additional agents for ENHANCED mode
        if self.mode == OrchestratorMode.ENHANCED:
            self._init_enhanced_agents()

    def _init_enhanced_agents(self) -> None:
        """Initialize additional agents for ENHANCED mode."""
        # Planner (no tools, just planning)
        self.planner = AssistantAgent(
            name="Planner",
            model_client=self.model_client,
            system_message="""You are the planning specialist.
Analyze requests and break them into clear steps.
Identify dependencies and suggest which agent handles each step.
Consider security, resources, and rollback possibilities.
After planning, hand off to the DevSecOps_Engineer for execution.""",
            description="Planning specialist who breaks down complex tasks into steps.",
        )

        # Security Expert
        self.security_expert = AssistantAgent(
            name="Security_Expert",
            model_client=self.model_client,
            tools=[autogen_tools.audit_host, autogen_tools.analyze_security_logs],
            system_message="""You are the security expert.
Review all actions for security implications.
Validate hostnames and credentials.
Flag dangerous commands and suggest safer alternatives.""",
            description="Security expert who reviews actions for security implications.",
        )

        # Knowledge Manager (if FalkorDB available)
        if self.knowledge_db:
            self.knowledge_manager = AssistantAgent(
                name="Knowledge_Manager",
                model_client=self.model_client,
                tools=[
                    knowledge_tools.record_incident,
                    knowledge_tools.search_knowledge,
                    knowledge_tools.get_solution_suggestion,
                ],
                system_message="""You are the knowledge manager.
Store important findings in the knowledge graph.
Recall relevant past incidents and solutions.
Identify patterns across incidents.""",
                description="Knowledge manager who stores and retrieves incident information.",
            )
        else:
            self.knowledge_manager = None

    def _get_engineer_prompt(self) -> str:
        """Get system prompt for Engineer."""
        return f"""You are an expert DevSecOps Engineer.
Your goal is to FULLY COMPLETE infrastructure tasks using the provided tools.

Available Tools:
CORE: list_hosts(), scan_host(hostname), execute_command(target, command, reason), check_permissions(target)
FILES: read_remote_file(host, path, lines), write_remote_file(host, path, content, backup), tail_logs(host, path, lines, grep)
SYSTEM: disk_info(host), memory_info(host), process_list(host), network_connections(host)
SERVICES: service_control(host, service, action)
CONTAINERS: docker_exec(container, command, host), kubectl_exec(namespace, pod, command)

Rules:
1. Use list_hosts() FIRST to verify hosts exist
2. ALWAYS scan a host before acting on it
3. If a command fails, try an alternative approach
4. CONTINUE until task is FULLY COMPLETE
5. Provide clear summary of findings

Say "TERMINATE" only when ALL steps are complete.

Environment: {self.env}"""

    # =========================================================================
    # Team Initialization (ENHANCED mode - new API)
    # =========================================================================

    def _init_team(self) -> None:
        """Initialize team for multi-agent collaboration."""
        participants = [self.planner, self.security_expert, self.engineer]
        if self.knowledge_manager:
            participants.append(self.knowledge_manager)

        # Use SelectorGroupChat for intelligent speaker selection
        termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(20)

        self.team = SelectorGroupChat(
            participants=participants,
            model_client=self.model_client,
            termination_condition=termination,
            selector_prompt="""Select the next speaker based on the conversation flow:
- If the task needs planning, select Planner
- If security review is needed, select Security_Expert
- If execution is needed, select DevSecOps_Engineer
- If knowledge lookup is needed, select Knowledge_Manager (if available)
- After planning, usually DevSecOps_Engineer should execute
Return only the agent name.""",
        )

    # =========================================================================
    # Session Management
    # =========================================================================

    def reset_session(self) -> None:
        """Reset the chat session."""
        # New API doesn't have agent.reset(), just reinitialize
        self._init_agents()
        if self.mode == OrchestratorMode.ENHANCED:
            self._init_team()
        self.console.print("[dim]Session reset[/dim]")

    # =========================================================================
    # Priority Display
    # =========================================================================

    def _display_priority(self, result: PriorityResult) -> None:
        """Display priority classification to user."""
        priority = result.priority
        color = priority.color
        label = priority.label

        priority_text = f"[bold {color}]{priority.name}[/bold {color}] - {label}"

        if result.environment_detected:
            priority_text += f" | env: {result.environment_detected}"
        if result.service_detected:
            priority_text += f" | service: {result.service_detected}"
        if result.host_detected:
            priority_text += f" | host: {result.host_detected}"

        self.console.print(Panel(
            f"{priority_text}\n[dim]{result.reasoning}[/dim]",
            title="🎯 Triage",
            border_style=color,
            padding=(0, 1),
        ))

        # Show behavior mode
        behavior_desc = describe_behavior(priority)
        self.console.print(f"[dim]Mode: {behavior_desc}[/dim]\n")

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

        Returns:
            Agent response
        """
        if dry_run:
            return f"🔍 Dry run: Would process in {self.mode.value} mode"

        # Step 1: Classify priority
        system_state = kwargs.get("system_state")
        self.current_priority = self.priority_classifier.classify(
            user_query,
            system_state=system_state,
        )

        # Step 2: Get behavior profile (for future adaptive behavior)
        _ = get_behavior(self.current_priority.priority)

        # Step 3: Display triage (respect verbosity)
        should_display = True
        if self.verbosity:
            should_display = self.verbosity.should_output(VerbosityLevel.NORMAL)

        if should_display:
            self._display_priority(self.current_priority)

        logger.info(
            f"Request classified as {self.current_priority.priority.name} "
            f"(confidence: {self.current_priority.confidence:.0%}, mode: {self.mode.value})"
        )

        # Step 4: Execute based on mode
        try:
            if self.mode == OrchestratorMode.ENHANCED:
                return await self._process_enhanced(user_query)
            else:
                return await self._process_basic(user_query)
        except Exception as e:
            logger.error(f"Orchestrator failed: {e}", exc_info=True)
            return f"❌ Error: {str(e)}"

    async def _process_basic(self, user_query: str) -> str:
        """Process with single engineer agent."""
        # Create a simple team with just the engineer
        termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(10)

        team = RoundRobinGroupChat(
            participants=[self.engineer],
            termination_condition=termination,
        )

        # Run the team
        result = await team.run(task=user_query)

        # Extract final response
        return self._extract_response(result)

    async def _process_enhanced(self, user_query: str) -> str:
        """Process with multi-agent team."""
        self.console.print("[bold cyan]🤖 Multi-Agent Team Active...[/bold cyan]")

        task = f"""
Task: {user_query}

Priority: {self.current_priority.priority.name}
Environment: {self.env}

Work together:
1. Planner: Create step-by-step plan
2. Security_Expert: Review for security concerns
3. DevSecOps_Engineer: Execute the plan
"""

        result = await self.team.run(task=task)
        return self._extract_response(result)

    def _extract_response(self, result: "TaskResult") -> str:
        """Extract response from TaskResult."""
        if not result.messages:
            return "✅ Task completed."

        # Get last non-empty message
        for msg in reversed(result.messages):
            content = getattr(msg, 'content', '')
            if content and "TERMINATE" not in content:
                return content

        return "✅ Task completed."

    async def chat_continue(self, message: str) -> str:
        """Continue conversation (BASIC mode compatibility)."""
        return await self._process_basic(message)


# =============================================================================
# Factory function for easy instantiation
# =============================================================================

def create_orchestrator(
    mode: str = "basic",
    env: str = "dev",
    language: str = "en",
) -> Orchestrator:
    """
    Factory function to create orchestrator.

    Args:
        mode: "basic" or "enhanced"
        env: Environment name
        language: Response language

    Returns:
        Configured Orchestrator instance
    """
    mode_enum = OrchestratorMode(mode.lower())
    return Orchestrator(mode=mode_enum, env=env, language=language)
