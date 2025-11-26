"""
Enhanced AG2 Orchestrator with Multi-Agent System and FalkorDB Knowledge Graph.

This orchestrator uses:
1. Multiple specialized agents (Planner, Security, Infrastructure, etc.)
2. FalkorDB for knowledge storage and retrieval
3. Group chat for complex multi-step reasoning
4. Learning from past interactions
"""
import os
import asyncio
from typing import Dict, Any, List, Optional
from rich.console import Console
from rich.panel import Panel

from athena_ai.agents.base_orchestrator import BaseOrchestrator
from athena_ai.utils.logger import logger
from athena_ai.agents import autogen_tools
from athena_ai.utils.verbosity import get_verbosity, VerbosityLevel

# FalkorDB integration
try:
    from athena_ai.knowledge.falkordb_client import FalkorDBClient, FalkorDBConfig
    HAS_FALKORDB = True
except ImportError:
    HAS_FALKORDB = False

# Triage System
from athena_ai.triage import (
    Priority,
    PriorityResult,
    PriorityClassifier,
    get_behavior,
    describe_behavior,
)

try:
    import autogen
    from autogen import (
        UserProxyAgent,
        AssistantAgent,
        GroupChat,
        GroupChatManager,
    )
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False
    logger.warning("pyautogen not installed. EnhancedAg2Orchestrator will not work.")


class EnhancedAg2Orchestrator(BaseOrchestrator):
    """
    Enhanced Multi-Agent Orchestrator with Knowledge Graph.

    Agents:
    - User_Proxy: Represents the user, executes tools
    - Planner: Decomposes complex tasks into steps
    - Security_Expert: Security analysis and validation
    - Infrastructure_Engineer: System operations
    - Knowledge_Manager: FalkorDB interactions

    Features:
    - GroupChat for collaborative reasoning
    - FalkorDB for persistent knowledge
    - Learning from past interactions
    - Priority-based behavior adaptation
    """

    def __init__(self, env: str = "dev", language: str = "en"):
        super().__init__(env=env, language=language)
        self.console = Console()
        self.verbosity = get_verbosity()

        if not HAS_AUTOGEN:
            raise ImportError("pyautogen is required. Run 'pip install pyautogen'.")

        # Priority classifier
        self.priority_classifier = PriorityClassifier()
        self.current_priority: Optional[PriorityResult] = None

        # Initialize FalkorDB if available
        self.knowledge_db: Optional[FalkorDBClient] = None
        if HAS_FALKORDB:
            self._init_knowledge_db()

        # Initialize tools
        autogen_tools.initialize_autogen_tools(
            executor=self.executor,
            context_manager=self.context_manager,
            permissions=self.permissions,
            credentials=self.credentials,  # For @variable resolution
        )

        # Configure LLM
        self.llm_config = self._get_llm_config()

        # Initialize agents
        self._init_agents()

        # Initialize group chat
        self._init_group_chat()

    def _init_knowledge_db(self) -> None:
        """Initialize FalkorDB connection."""
        try:
            config = FalkorDBConfig(
                graph_name="athena_knowledge",
                auto_start_docker=True,
            )
            self.knowledge_db = FalkorDBClient(config)
            if self.knowledge_db.connect():
                logger.info("FalkorDB connected for knowledge storage")
                self._ensure_knowledge_schema()
            else:
                logger.warning("FalkorDB not available, running without knowledge graph")
                self.knowledge_db = None
        except Exception as e:
            logger.warning(f"FalkorDB initialization failed: {e}")
            self.knowledge_db = None

    def _ensure_knowledge_schema(self) -> None:
        """Ensure knowledge graph schema exists."""
        if not self.knowledge_db:
            return

        try:
            # Create indexes for common queries
            self.knowledge_db.query(
                "CREATE INDEX IF NOT EXISTS FOR (h:Host) ON (h.hostname)"
            )
            self.knowledge_db.query(
                "CREATE INDEX IF NOT EXISTS FOR (i:Incident) ON (i.created_at)"
            )
            self.knowledge_db.query(
                "CREATE INDEX IF NOT EXISTS FOR (s:Solution) ON (s.pattern)"
            )
            logger.debug("Knowledge graph schema ensured")
        except Exception as e:
            logger.warning(f"Failed to create knowledge schema: {e}")

    def _get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration for Autogen."""
        api_key = (
            os.getenv("OPENROUTER_API_KEY") or
            os.getenv("ANTHROPIC_API_KEY") or
            os.getenv("OPENAI_API_KEY")
        )
        model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
        base_url = "https://openrouter.ai/api/v1" if os.getenv("OPENROUTER_API_KEY") else None

        config_list = [{
            "model": model,
            "api_key": api_key,
            "base_url": base_url
        }]

        return {
            "config_list": config_list,
            "temperature": 0.1,
            "timeout": 120,
        }

    def _is_termination_msg(self, msg: Dict[str, Any]) -> bool:
        """
        Check if message indicates task completion.

        More flexible than just checking for "TERMINATE" at end.
        """
        content = msg.get("content", "")
        if not content:
            return False

        content_lower = content.lower().strip()

        # Check for explicit TERMINATE
        if content.rstrip().endswith("TERMINATE"):
            return True

        # Check for completion phrases with terminate
        completion_phrases = [
            "task completed",
            "task is complete",
            "successfully completed",
            "all done",
            "request fulfilled",
        ]

        for phrase in completion_phrases:
            if phrase in content_lower and "terminate" in content_lower:
                return True

        return False

    def _init_agents(self) -> None:
        """Initialize all specialized agents."""

        # 1. User Proxy (Tool Executor)
        self.user_proxy = UserProxyAgent(
            name="User_Proxy",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=30,  # Allow more steps for complex tasks
            is_termination_msg=self._is_termination_msg,
            code_execution_config={"work_dir": "coding", "use_docker": False},
            llm_config=self.llm_config,
            system_message="""You are the execution bridge that runs tools.
Execute tools when requested by other agents and report results.

CRITICAL: You MUST say "TERMINATE" (exactly this word, alone on the last line) when:
- The task has been completed successfully
- All requested information has been gathered and presented
- The user's question has been fully answered

Never stop mid-task. Always complete the full request before terminating.
"""
        )

        # 2. Planner Agent
        self.planner = AssistantAgent(
            name="Planner",
            llm_config=self.llm_config,
            system_message="""You are the planning specialist.
Your role is to:
1. Analyze user requests and break them into clear steps
2. Identify dependencies between steps
3. Suggest which agent should handle each step
4. Validate that plans are complete and safe

When planning, consider:
- Security implications
- Resource requirements
- Rollback possibilities
- Verification steps

Always respond with a structured plan when asked.
"""
        )

        # 3. Security Expert
        self.security_expert = AssistantAgent(
            name="Security_Expert",
            llm_config=self.llm_config,
            system_message="""You are the security expert.
Your role is to:
1. Review all actions for security implications
2. Validate hostnames and credentials
3. Check for dangerous commands (rm -rf, etc.)
4. Ensure principle of least privilege
5. Flag any security concerns

You MUST approve all destructive or sensitive operations.
If something seems risky, ask for clarification or suggest safer alternatives.
"""
        )

        # 4. Infrastructure Engineer
        self.infra_engineer = AssistantAgent(
            name="Infrastructure_Engineer",
            llm_config=self.llm_config,
            system_message=f"""You are the infrastructure expert.
Your role is to FULLY COMPLETE infrastructure operations using the available tools.

Available Tools:
- scan_host(hostname): Discover OS, services, etc.
- execute_command(target, command, reason): Run shell commands
- check_permissions(target): Check sudo/root access
- audit_host(target): Security audit
- get_infrastructure_context(): See inventory
- list_hosts(): See all available hosts
- analyze_security_logs(target): Analyze auth logs

Rules:
1. Use list_hosts() first if you need to find hosts
2. NEVER invent hostnames - use only validated hosts
3. CONTINUE WORKING until the task is FULLY COMPLETE
4. Provide a clear summary of findings/results

TERMINATION: Only say "TERMINATE" on the last line when:
- ALL steps of the task are complete
- Results have been summarized and presented
- The user's request has been FULLY addressed

DO NOT terminate mid-task. If a command fails, try to fix it or explain why.

Current Environment: {self.env}
"""
        )

        # 5. Knowledge Manager (if FalkorDB available)
        if self.knowledge_db:
            self.knowledge_manager = AssistantAgent(
                name="Knowledge_Manager",
                llm_config=self.llm_config,
                system_message="""You are the knowledge manager.
Your role is to:
1. Store important findings in the knowledge graph
2. Recall relevant past incidents and solutions
3. Identify patterns across incidents
4. Suggest solutions based on historical data

When something noteworthy happens (incident, solution, configuration),
ask to store it in the knowledge base for future reference.
"""
            )
        else:
            self.knowledge_manager = None

        # Register tools with appropriate agents
        self._register_tools()

    def _register_tools(self) -> None:
        """Register tools with agents."""

        def register(func, agents):
            """Register function with multiple agents."""
            for caller in agents:
                autogen.register_function(
                    func,
                    caller=caller,
                    executor=self.user_proxy,
                    name=func.__name__,
                    description=func.__doc__
                )

        # Infrastructure tools for engineer
        register(autogen_tools.scan_host, [self.infra_engineer])
        register(autogen_tools.execute_command, [self.infra_engineer])
        register(autogen_tools.check_permissions, [self.infra_engineer])
        register(autogen_tools.get_infrastructure_context, [self.infra_engineer, self.planner])
        register(autogen_tools.list_hosts, [self.infra_engineer, self.planner])

        # Security tools for security expert
        register(autogen_tools.audit_host, [self.security_expert, self.infra_engineer])
        register(autogen_tools.analyze_security_logs, [self.security_expert, self.infra_engineer])

        # Knowledge tools if available
        if self.knowledge_db:
            self._register_knowledge_tools()

    def _register_knowledge_tools(self) -> None:
        """Register knowledge graph tools."""
        if not self.knowledge_manager:
            return

        def store_incident(
            host: str,
            description: str,
            severity: str,
            resolution: str = ""
        ) -> str:
            """Store an incident in the knowledge graph."""
            try:
                self.knowledge_db.create_node("Incident", {
                    "host": host,
                    "description": description,
                    "severity": severity,
                    "resolution": resolution,
                    "env": self.env,
                })
                return f"✅ Incident stored for {host}"
            except Exception as e:
                return f"❌ Failed to store incident: {e}"

        def recall_incidents(
            host: str = "",
            pattern: str = ""
        ) -> str:
            """Recall past incidents from knowledge graph."""
            try:
                if host:
                    results = self.knowledge_db.query(
                        "MATCH (i:Incident) WHERE i.host = $host RETURN i ORDER BY i.created_at DESC LIMIT 5",
                        {"host": host}
                    )
                elif pattern:
                    results = self.knowledge_db.query(
                        "MATCH (i:Incident) WHERE i.description CONTAINS $pattern RETURN i ORDER BY i.created_at DESC LIMIT 5",
                        {"pattern": pattern}
                    )
                else:
                    results = self.knowledge_db.query(
                        "MATCH (i:Incident) RETURN i ORDER BY i.created_at DESC LIMIT 10"
                    )

                if not results:
                    return "No incidents found matching criteria"

                output = ["📚 Past Incidents:"]
                for r in results:
                    inc = r.get("i", {})
                    output.append(f"- [{inc.get('severity', 'unknown')}] {inc.get('host', '?')}: {inc.get('description', '')}")
                return "\n".join(output)

            except Exception as e:
                return f"❌ Failed to recall incidents: {e}"

        # Register knowledge tools
        autogen.register_function(
            store_incident,
            caller=self.knowledge_manager,
            executor=self.user_proxy,
            name="store_incident",
            description="Store an incident in the knowledge graph"
        )

        autogen.register_function(
            recall_incidents,
            caller=self.knowledge_manager,
            executor=self.user_proxy,
            name="recall_incidents",
            description="Recall past incidents from knowledge graph"
        )

    def _init_group_chat(self) -> None:
        """Initialize group chat for multi-agent collaboration."""
        # Build agent list
        agents = [self.user_proxy, self.planner, self.security_expert, self.infra_engineer]
        if self.knowledge_manager:
            agents.append(self.knowledge_manager)

        # Custom speaker selection for efficient routing
        def speaker_selection(last_speaker, groupchat):
            """Select next speaker based on conversation flow."""
            messages = groupchat.messages
            if not messages:
                return self.planner  # Start with planning

            last_msg = messages[-1].get("content", "").lower()

            # Route based on content
            if "security" in last_msg or "audit" in last_msg or "dangerous" in last_msg:
                return self.security_expert
            elif "execute" in last_msg or "run" in last_msg or "command" in last_msg:
                return self.infra_engineer
            elif "plan" in last_msg or "steps" in last_msg:
                return self.planner
            elif "knowledge" in last_msg or "past" in last_msg or "history" in last_msg:
                return self.knowledge_manager if self.knowledge_manager else self.infra_engineer
            elif last_speaker == self.planner:
                return self.infra_engineer  # After planning, execute
            elif last_speaker == self.security_expert:
                return self.infra_engineer  # After security review, execute
            else:
                return self.infra_engineer  # Default to engineer

        self.group_chat = GroupChat(
            agents=agents,
            messages=[],
            max_round=20,
            speaker_selection_method=speaker_selection,
        )

        self.chat_manager = GroupChatManager(
            groupchat=self.group_chat,
            llm_config=self.llm_config,
        )

    def reset_session(self) -> None:
        """Reset the chat session."""
        for agent in [self.user_proxy, self.planner, self.security_expert, self.infra_engineer]:
            agent.reset()
        if self.knowledge_manager:
            self.knowledge_manager.reset()
        self.group_chat.messages.clear()
        self.console.print("[dim]Session reset[/dim]")

    async def process_request(
        self,
        user_query: str,
        auto_confirm: bool = False,
        dry_run: bool = False,
        use_group_chat: bool = True,
        **kwargs
    ) -> str:
        """
        Process request using Multi-Agent system.

        Args:
            user_query: User's request
            auto_confirm: Skip confirmations
            dry_run: Preview only
            use_group_chat: Use collaborative group chat (vs single agent)

        Returns:
            Agent response
        """
        if dry_run:
            return "🔍 Dry run: Multi-agent analysis would be performed"

        # Step 1: Classify priority
        self.current_priority = self.priority_classifier.classify(user_query)
        behavior = get_behavior(self.current_priority.priority)

        # Step 2: Display triage (if verbose)
        if self.verbosity.should_output(VerbosityLevel.NORMAL):
            self._display_priority(self.current_priority)

        # Step 3: Check knowledge base for similar past incidents
        if self.knowledge_db and self.verbosity.is_verbose:
            self._check_knowledge_base(user_query)

        # Step 4: Execute with appropriate mode
        self.console.print("[bold cyan]🤖 Multi-Agent Team Active...[/bold cyan]")

        try:
            if use_group_chat:
                # Use group chat for complex reasoning
                result = self.user_proxy.initiate_chat(
                    self.chat_manager,
                    message=f"""
Task: {user_query}

Priority: {self.current_priority.priority.name}
Environment: {self.env}

Please work together to solve this task:
1. Planner: Create a step-by-step plan
2. Security_Expert: Review for security concerns
3. Infrastructure_Engineer: Execute the plan
4. Knowledge_Manager: Store any learnings

Begin with planning.
""",
                    clear_history=True,
                )
            else:
                # Simple mode - direct to engineer
                result = self.user_proxy.initiate_chat(
                    self.infra_engineer,
                    message=user_query,
                    clear_history=False,
                )

            return result.summary or "✅ Task completed."

        except Exception as e:
            logger.error(f"Multi-agent execution failed: {e}", exc_info=True)
            return f"❌ Error: {str(e)}"

    def _display_priority(self, result: PriorityResult) -> None:
        """Display priority classification."""
        priority = result.priority
        self.console.print(Panel(
            f"[bold {priority.color}]{priority.name}[/bold {priority.color}] - {priority.label}\n"
            f"[dim]{result.reasoning}[/dim]",
            title="🎯 Triage",
            border_style=priority.color,
            padding=(0, 1),
        ))

    def _check_knowledge_base(self, query: str) -> None:
        """Check knowledge base for relevant past incidents."""
        if not self.knowledge_db:
            return

        try:
            # Extract key terms for search
            results = self.knowledge_db.query(
                "MATCH (i:Incident) RETURN i ORDER BY i.created_at DESC LIMIT 3"
            )

            if results:
                self.console.print("[dim]📚 Related past incidents found in knowledge base[/dim]")

        except Exception as e:
            logger.debug(f"Knowledge base check failed: {e}")

    def store_learning(
        self,
        pattern_type: str,
        pattern_value: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """Store a learning in the knowledge graph."""
        if not self.knowledge_db:
            return False

        try:
            self.knowledge_db.create_node("Learning", {
                "pattern_type": pattern_type,
                "pattern_value": pattern_value,
                "env": self.env,
                **(metadata or {}),
            })
            return True
        except Exception as e:
            logger.error(f"Failed to store learning: {e}")
            return False
