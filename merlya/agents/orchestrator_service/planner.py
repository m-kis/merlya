import asyncio
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from rich.console import Console

from merlya.agents import autogen_tools, knowledge_tools
from merlya.triage.jump_host_detector import detect_jump_host
from merlya.triage.variable_detector import get_variable_detector
from merlya.utils.logger import logger

from .prompts import (
    get_behavior_for_priority,
    get_engineer_prompt,
    get_fallback_response,
    get_intent_guidance,
    get_priority_guidance,
)
from .response_extractor import (
    collect_tool_outputs,
    extract_response,
    generate_synthesis,
)

if TYPE_CHECKING:
    from autogen_agentchat.base import TaskResult

# Optional imports
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False

class ExecutionPlanner:
    """Handles agent team creation and execution planning."""

    def __init__(self, client_factory: Callable[[str], Any], tools: List[Callable[..., Any]], env: str = "dev", console: Optional[Console] = None):
        self.client_factory = client_factory
        self.tools = tools
        self.env = env
        self.console = console or Console()

        self.engineer = None
        self.planner = None
        self.security_expert = None
        self.knowledge_manager = None
        self.team = None

    def init_agents(self, mode: str, knowledge_db: Any = None) -> None:
        """Initialize agents based on mode."""
        if not HAS_AUTOGEN:
            raise ImportError(
                "autogen-agentchat is required. Install with: pip install autogen-agentchat"
            )

        # Warn if interaction tools are missing (documented in engineer prompt)
        tool_names = {getattr(t, '__name__', str(t)) for t in self.tools if callable(t)}
        interaction_tools = {'ask_user', 'request_elevation'}
        missing_interaction = interaction_tools - tool_names
        if missing_interaction:
            logger.warning(
                f"Missing INTERACTION tools: {missing_interaction}. "
                "Agent may fail if it tries to use ask_user() or request_elevation()."
            )

        # Engineer (main agent with tools)
        # Default to synthesis model for general engineering tasks
        self.engineer = AssistantAgent(  # type: ignore[assignment]
            name="DevSecOps_Engineer",
            model_client=self.client_factory("synthesis"),
            tools=self.tools,  # type: ignore[arg-type]
            system_message=get_engineer_prompt(self.env),
            description="Expert DevSecOps engineer who executes infrastructure tasks using tools.",
        )

        # Additional agents for ENHANCED mode
        if mode == "enhanced":
            self._init_enhanced_agents(knowledge_db)
            self._init_team()

    def _init_enhanced_agents(self, knowledge_db):
        """Initialize additional agents for ENHANCED mode."""
        # Planner (no tools, just planning)
        # Use planning model (e.g. Opus) for complex reasoning
        self.planner = AssistantAgent(
            name="Planner",
            model_client=self.client_factory("planning"),
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
            model_client=self.client_factory("synthesis"),
            tools=[autogen_tools.audit_host, autogen_tools.analyze_security_logs],
            system_message="""You are the security expert.
Review all actions for security implications.
Validate hostnames and credentials.
Flag dangerous commands and suggest safer alternatives.""",
            description="Security expert who reviews actions for security implications.",
        )

        # Knowledge Manager (if FalkorDB available)
        if knowledge_db:
            self.knowledge_manager = AssistantAgent(
                name="Knowledge_Manager",
                model_client=self.client_factory("synthesis"),
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

    def _init_team(self):
        """Initialize team for multi-agent collaboration."""
        participants = [self.planner, self.security_expert, self.engineer]
        if self.knowledge_manager:
            participants.append(self.knowledge_manager)

        # Use SelectorGroupChat for intelligent speaker selection
        # Limit to 15 messages to prevent long, confusing sessions
        termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(15)

        self.team = SelectorGroupChat(
            participants=participants,
            model_client=self.client_factory("synthesis"),
            termination_condition=termination,
            selector_prompt="""Select the next speaker based on the conversation flow:
1. START with Planner to create a plan (unless it's a simple follow-up).
2. Planner -> Security_Expert (to review the plan).
3. Security_Expert -> DevSecOps_Engineer (to execute).
4. DevSecOps_Engineer -> Planner (if plan needs adjustment) or TERMINATE (if done).
5. Knowledge_Manager can be called at any time to store findings.

Return only the agent name.""",
        )

    def _build_task_with_context(
        self,
        user_query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        variable_context: Optional[str] = None
    ) -> str:
        """
        Build task string with conversation and variable context.

        Injects recent conversation history so the agent understands
        references like "this server", "the file", etc.

        Also injects variable context hint when query mentions @variables.
        """
        parts = []

        # Add variable context if provided
        if variable_context:
            parts.append(variable_context)

        # Add conversation history if available
        if conversation_history:
            # Take last N exchanges (user + assistant pairs) to keep context manageable
            max_context_messages = 6  # 3 exchanges
            recent = conversation_history[-max_context_messages:]

            if recent:
                parts.append("[Previous conversation context:]")
                for msg in recent:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    # Truncate long messages
                    if len(content) > 500:
                        content = content[:500] + "..."
                    prefix = "User" if role == "user" else "Assistant"
                    parts.append(f"{prefix}: {content}")
                parts.append("")

        # Add current request
        if parts:
            parts.append("[Current request:]")
        parts.append(user_query)

        return "\n".join(parts)

    def _detect_variable_query(self, user_query: str) -> Optional[str]:
        """
        Detect if query is about user variables using semantic similarity.

        Uses sentence-transformers for intelligent detection, with keyword fallback.

        Returns a context string if variable-related, None otherwise.
        """
        detector = get_variable_detector()
        is_variable_query, confidence = detector.detect(user_query)

        if is_variable_query:
            logger.debug(f"📊 Variable query detected: confidence={confidence:.2f}")
            return detector.get_context_hint()

        return None

    def _detect_jump_host(self, user_query: str) -> Optional[str]:
        """
        Detect if query specifies a jump host for SSH pivoting.

        Detects patterns like:
        - "via @bastion"
        - "à travers @ansible"
        - "through @jumphost"

        Returns a context string with pivoting instructions if detected.
        """
        jump_info = detect_jump_host(user_query)

        if jump_info:
            logger.info(f"🌐 Jump host detected: {jump_info}")
            # Build context hint for the LLM
            target = jump_info.target_host or "the target host"
            return f"""📌 **SSH PIVOTING DETECTED**
The user wants to connect to {target} via the jump host '@{jump_info.jump_host}'.
This means the target is not directly accessible and requires pivoting through '{jump_info.jump_host}'.

**IMPORTANT**: When using execute_command() or scan_host() for this request:
- Use the `via_host` parameter set to "{jump_info.jump_host}"
- Example: execute_command(target="{target}", command="...", reason="...", via_host="{jump_info.jump_host}")

This enables SSH agent forwarding and proper tunneling through the jump host."""

        return None

    async def execute_basic(
        self,
        user_query: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        allowed_tools: Optional[List[str]] = None,
        intent: str = "action",
        priority: Optional[str] = None,
    ) -> str:
        """
        Process with single engineer agent.

        Args:
            user_query: User's request
            conversation_history: Recent conversation context
            allowed_tools: List of allowed tool names (None = all)
            intent: Intent type (query, action, analysis)
            priority: Priority level (P0, P1, P2, P3) - affects behavior profile
        """
        if not HAS_AUTOGEN:
            raise ImportError(
                "autogen-agentchat is required for execute_basic(). "
                "Install with: pip install autogen-agentchat"
            )
        if self.engineer is None:
            raise RuntimeError("Agents not initialized. Call init_agents() first.")

        # Get behavior profile based on priority
        priority_name = priority or "P3"
        behavior = get_behavior_for_priority(priority_name)

        # Determine task type for model selection
        # P0/P1 -> correction (fast)
        # P2 -> synthesis (balanced)
        # P3 -> planning (thorough)
        task_type = "synthesis"
        if priority_name in ("P0", "P1"):
            task_type = "correction"
        elif priority_name == "P3":
            task_type = "planning"

        # Create a temporary engineer with the specific model for this task
        engineer = AssistantAgent(
            name="DevSecOps_Engineer",
            model_client=self.client_factory(task_type),
            tools=self.tools,
            system_message=get_engineer_prompt(self.env),
            description="Expert DevSecOps engineer who executes infrastructure tasks using tools.",
        )

        # Detect variable-related queries
        variable_context = self._detect_variable_query(user_query)

        # Detect jump host for SSH pivoting
        jump_host_context = self._detect_jump_host(user_query)

        # Combine contexts
        combined_context = None
        if variable_context or jump_host_context:
            parts = [c for c in [variable_context, jump_host_context] if c]
            combined_context = "\n\n".join(parts)

        # Build task with conversation context
        task = self._build_task_with_context(user_query, conversation_history, combined_context)

        # Add priority-specific guidance (adapts agent behavior)
        priority_guidance = get_priority_guidance(priority_name)

        # Add intent-specific guidance
        intent_guidance = get_intent_guidance(intent)
        task = f"{priority_guidance}\n{intent_guidance}\n\n{task}"

        # Add tool restrictions if specified
        if allowed_tools:
            task += f"\n\n⚠️ TOOL RESTRICTION: You may ONLY use these tools: {', '.join(allowed_tools)}. Do NOT use any other tools."

        # Log effective configuration
        logger.info(
            f"⚙️ Executing with priority={priority_name}, intent={intent}, "
            f"max_commands={behavior.max_commands_before_pause}, "
            f"response_format={behavior.response_format}"
        )

        # Create a simple team with just the engineer
        # Keep message limits tight to prevent long, confusing sessions
        # The agent should TERMINATE when task is complete, not keep going
        if priority_name in ("P0", "P1"):
            max_messages = 12  # Fast response for urgent issues
        else:
            max_messages = 18  # Standard - enough for 3-4 tool chains

        termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(max_messages)

        team = RoundRobinGroupChat(
            participants=[engineer],
            termination_condition=termination,
        )

        # Run the team with timeout to prevent indefinite blocking
        try:
            result = await asyncio.wait_for(
                team.run(task=task),
                timeout=300.0  # 5 minute timeout for LLM response
            )
        except asyncio.TimeoutError:
            logger.error("⏱️ Agent team execution timed out after 5 minutes")
            return "❌ **Timeout**: L'exécution a pris trop de temps (>5 minutes). Réessayez avec une requête plus simple."

        # Extract or generate synthesis
        return await self._extract_or_synthesize(result, user_query)

    async def execute_enhanced(
        self,
        user_query: str,
        priority_name: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        allowed_tools: Optional[List[str]] = None,
        intent: str = "action",
        knowledge_context: Optional[str] = None,
    ) -> str:
        """Process with multi-agent team."""
        if not HAS_AUTOGEN:
            raise ImportError(
                "autogen-agentchat is required for execute_enhanced(). "
                "Install with: pip install autogen-agentchat"
            )
        self.console.print("[bold cyan]🤖 Multi-Agent Team Active...[/bold cyan]")

        # Get behavior profile based on priority
        behavior = get_behavior_for_priority(priority_name)

        # Detect variable-related queries
        variable_context = self._detect_variable_query(user_query)

        # Detect jump host for SSH pivoting
        jump_host_context = self._detect_jump_host(user_query)

        # Combine contexts
        combined_context = None
        if variable_context or jump_host_context:
            parts = [c for c in [variable_context, jump_host_context] if c]
            combined_context = "\n\n".join(parts)

        # Build base task with context
        base_task = self._build_task_with_context(user_query, conversation_history, combined_context)

        # Add priority-specific guidance (adapts agent behavior)
        priority_guidance = get_priority_guidance(priority_name)

        # Add intent-specific guidance
        intent_guidance = get_intent_guidance(intent)

        # Build tool restriction text if specified
        tool_restriction = ""
        if allowed_tools:
            tool_restriction = f"\n\n⚠️ TOOL RESTRICTION: You may ONLY use these tools: {', '.join(allowed_tools)}. Do NOT use any other tools."

        # Log effective configuration
        logger.info(
            f"⚙️ Executing ENHANCED with priority={priority_name}, intent={intent}, "
            f"max_commands={behavior.max_commands_before_pause}, "
            f"response_format={behavior.response_format}"
        )

        task = f"""{priority_guidance}
{intent_guidance}

{base_task}

Environment: {self.env}
{tool_restriction}

Past Knowledge Context:
{knowledge_context or "No relevant past incidents found."}

Work together:
1. Planner: Create step-by-step plan (considering past knowledge)
2. Security_Expert: Review for security concerns
3. DevSecOps_Engineer: Investigate, recommend, then execute if approved
"""

        # Run the team with timeout to prevent indefinite blocking
        if self.team is None:
            raise RuntimeError("Team not initialized. Call init_agents() with mode='enhanced' first.")

        try:
            result = await asyncio.wait_for(
                self.team.run(task=task),
                timeout=300.0  # 5 minute timeout for LLM response
            )
        except asyncio.TimeoutError:
            logger.error("⏱️ Enhanced agent team execution timed out after 5 minutes")
            return "❌ **Timeout**: L'exécution a pris trop de temps (>5 minutes). L'API LLM ne répond pas."

        return await self._extract_or_synthesize(result, user_query)

    async def _extract_or_synthesize(self, result: "TaskResult", user_query: str) -> str:
        """
        Extract synthesis from result, or generate one if missing.

        If the agent didn't provide a clear synthesis, collect tool outputs
        and ask the LLM to synthesize them.
        """
        # First, try to find an existing synthesis
        synthesis = extract_response(result)

        # If we got a real synthesis (not empty or just task completed), return it
        if synthesis and synthesis not in ("", "✅ Task completed."):
            return synthesis

        # No synthesis found - collect tool outputs and generate one
        tool_outputs = collect_tool_outputs(result)

        if not tool_outputs:
            # No tool outputs either - provide helpful message based on context
            logger.warning("⚠️ No synthesis and no tool outputs found in response")
            return get_fallback_response(user_query)

        # Ask LLM to synthesize the outputs
        return await generate_synthesis(user_query, tool_outputs, self.client_factory)
