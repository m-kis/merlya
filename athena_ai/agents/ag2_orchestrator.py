"""
Ag2 (Autogen) Orchestrator for Athena.

This orchestrator uses a multi-agent system to solve complex infrastructure tasks.
It replaces the monolithic UnifiedOrchestrator when advanced autonomy is needed.
"""
import os
from typing import Any, Dict, Optional

from rich.console import Console
from rich.panel import Panel

from athena_ai.agents import autogen_tools, knowledge_tools
from athena_ai.agents.base_orchestrator import BaseOrchestrator
from athena_ai.triage import (
    BehaviorProfile,
    PriorityClassifier,
    PriorityResult,
    describe_behavior,
    get_behavior,
)
from athena_ai.utils.logger import logger

try:
    import autogen
    from autogen import AssistantAgent, UserProxyAgent
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False
    logger.warning("pyautogen not installed. Ag2Orchestrator will not work.")


class Ag2Orchestrator(BaseOrchestrator):
    """
    Orchestrator based on Ag2 (Autogen) Multi-Agent framework.

    Agents:
    - UserProxy: Represents the user, executes tools.
    - Engineer: Writes code/commands to solve tasks.
    - Planner: Breaks down complex requests.

    Features:
    - Automatic priority classification (P0-P3)
    - Behavior profiles based on priority
    """

    def __init__(self, env: str = "dev", language: str = "en"):
        super().__init__(env=env, language=language)
        self.console = Console()

        if not HAS_AUTOGEN:
            raise ImportError("pyautogen is required for Ag2Orchestrator. Run 'pip install pyautogen'.")

        # Initialize priority classifier
        self.priority_classifier = PriorityClassifier()
        self.current_priority: Optional[PriorityResult] = None
        self.current_behavior: Optional[BehaviorProfile] = None

        # Initialize tools
        autogen_tools.initialize_autogen_tools(
            executor=self.executor,
            context_manager=self.context_manager,
            permissions=self.permissions,
            context_memory=self.context_manager.memory if hasattr(self.context_manager, 'memory') else None,
            error_correction=None,  # Can be injected if available
            credentials=self.credentials,  # For @variable resolution
        )

        # Configure LLM
        self.llm_config = self._get_llm_config()

        # Initialize Agents
        self._init_agents()

    def _get_llm_config(self) -> Dict[str, Any]:
        """Get LLM configuration for Autogen."""
        # Try to get config from environment or fallback to defaults
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")
        model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3-opus")
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
        Detects various completion indicators in English and French.
        """
        content = msg.get("content", "")
        if not content:
            return False

        content_lower = content.lower().strip()

        # Check for explicit TERMINATE
        if content.rstrip().endswith("TERMINATE"):
            return True

        # Check for common completion phrases (EN + FR)
        completion_phrases = [
            # English
            "task completed",
            "task is complete",
            "successfully completed",
            "all done",
            "request fulfilled",
            "here is the summary",
            "the task has been completed",
            "i have completed",
            # French
            "tâche terminée",
            "tâche complétée",
            "voici le résumé",
            "mission accomplie",
            "travail terminé",
        ]

        for phrase in completion_phrases:
            if phrase in content_lower:
                # If phrase found AND message mentions terminate
                if "terminate" in content_lower:
                    return True

        return False

    def _init_agents(self):
        """Initialize Autogen agents."""

        # 1. User Proxy (The Bridge)
        # Executes tools and interacts with the user
        self.user_proxy = UserProxyAgent(
            name="User_Proxy",
            human_input_mode="NEVER",  # We handle input via CLI
            max_consecutive_auto_reply=50,  # Allow more steps for complex tasks (increased from 30)
            is_termination_msg=self._is_termination_msg,
            code_execution_config={
                "work_dir": "coding",
                "use_docker": False,  # For MVP, run locally (sandbox later)
            },
            llm_config=self.llm_config,
            system_message="""You are the execution bridge between the user and specialized agents.
Execute tools when requested and report results.

CRITICAL: You MUST say "TERMINATE" (exactly this word, alone on the last line) when:
- The task has been completed successfully
- All requested information has been gathered and presented
- The user's question has been fully answered

Never stop mid-task. Always complete the full request before terminating.
"""
        )

        # 2. Engineer (The Doer)
        # Writes code and calls tools
        self.engineer = AssistantAgent(
            name="DevSecOps_Engineer",
            llm_config=self.llm_config,
            system_message=f"""You are an expert DevSecOps Engineer.
Your goal is to FULLY COMPLETE infrastructure tasks using the provided tools.

Available Tools:
CORE:
- list_hosts(): See all available hosts (USE FIRST!)
- scan_host(hostname): Discover OS, services, etc.
- execute_command(target, command, reason): Run shell commands
- check_permissions(target): Check sudo/root access

FILES:
- read_remote_file(host, path, lines): Read file content
- write_remote_file(host, path, content, backup): Write file (backup=True by default)
- tail_logs(host, path, lines, grep): Tail logs with optional filter

SYSTEM:
- disk_info(host, path, mode, check_smart, check_raid): Disk space, SMART, RAID
- memory_info(host): RAM usage and top consumers
- process_list(host, filter, sort_by): List processes
- network_connections(host, port, state): Network connections

SERVICES:
- service_control(host, service, action): systemctl start/stop/restart/status

CONTAINERS:
- docker_exec(container, command, host): Execute in Docker container
- kubectl_exec(namespace, pod, command): Execute in K8s pod

BEST PRACTICES:
- If a command fails, check the error message and try an alternative syntax
- Use the dedicated tools (tail_logs, disk_info, etc.) instead of raw commands when available
- For services, prefer service_control() over manual systemctl commands

Rules:
1. Use list_hosts() FIRST to verify hosts exist
2. ALWAYS scan a host before acting on it (unless already scanned)
3. If a command fails, try an alternative approach before giving up
4. Be concise and efficient
5. CONTINUE WORKING until the task is FULLY COMPLETE
6. Provide a clear summary of findings/results

TERMINATION: Only say "TERMINATE" on the last line when:
- ALL steps of the task are complete
- Results have been summarized and presented
- The user's request has been FULLY addressed

DO NOT terminate mid-task. If a command fails, try to fix it or explain why.

Current Environment: {self.env}
"""
        )

        # 3. Register Tools
        self._register_tools()

        # 4. Setup streaming callbacks for message-by-message display
        self._setup_streaming_callbacks()

    def _register_tools(self):
        """Register tools with agents."""

        # Helper to register for both agents (caller and executor)
        def register(func):
            autogen.register_function(
                func,
                caller=self.engineer,
                executor=self.user_proxy,
                name=func.__name__,
                description=func.__doc__
            )

        # Register tools from autogen_tools
        # Core tools
        register(autogen_tools.scan_host)
        register(autogen_tools.execute_command)
        register(autogen_tools.check_permissions)
        register(autogen_tools.get_infrastructure_context)
        register(autogen_tools.list_hosts)
        register(autogen_tools.audit_host)
        register(autogen_tools.add_route)
        register(autogen_tools.analyze_security_logs)

        # File operations
        register(autogen_tools.read_remote_file)
        register(autogen_tools.write_remote_file)
        register(autogen_tools.tail_logs)
        register(autogen_tools.glob_files)
        register(autogen_tools.grep_files)
        register(autogen_tools.find_file)

        # Web tools
        register(autogen_tools.web_search)
        register(autogen_tools.web_fetch)

        # Interaction & Learning
        register(autogen_tools.ask_user)
        register(autogen_tools.remember_skill)
        register(autogen_tools.recall_skill)

        # Knowledge Graph (FalkorDB)
        register(knowledge_tools.record_incident)
        register(knowledge_tools.search_knowledge)
        register(knowledge_tools.get_solution_suggestion)
        register(knowledge_tools.graph_stats)

        # System info
        register(autogen_tools.disk_info)
        register(autogen_tools.memory_info)
        register(autogen_tools.network_connections)
        register(autogen_tools.process_list)

        # Service control
        register(autogen_tools.service_control)

        # Container operations
        register(autogen_tools.docker_exec)
        register(autogen_tools.kubectl_exec)

    def _setup_streaming_callbacks(self):
        """
        Setup streaming callbacks for message-by-message display.

        This enables real-time feedback to the user as agents communicate,
        similar to Claude Code's streaming behavior but at message level.
        """
        def on_agent_message(recipient, messages, sender, config):
            """
            Callback called for each agent message.

            Displays agent activity in real-time so users see progress.
            """
            if not messages:
                return False, None

            last_msg = messages[-1]
            content = last_msg.get("content", "")

            if not content:
                return False, None

            # Determine message type and display accordingly
            sender_name = sender.name if hasattr(sender, 'name') else str(sender)

            # Truncate very long content for display
            display_content = content[:500] + "..." if len(content) > 500 else content

            # Check if this is a tool call result
            if "function_call" in last_msg or last_msg.get("role") == "function":
                # Tool execution - show brief status
                self.console.print("[dim]⚙ Tool executed[/dim]")
            elif sender_name == "DevSecOps_Engineer":
                # Engineer thinking/planning - show with context
                if "TERMINATE" not in content:
                    self.console.print(f"[cyan]◆ Engineer:[/cyan] {display_content[:200]}")
            elif sender_name == "User_Proxy":
                # User proxy response (usually tool results)
                if len(content) > 100:
                    self.console.print(f"[green]◆ Result:[/green] {display_content[:150]}...")

            # Return False to not modify the conversation flow
            return False, None

        # Register callback on the engineer agent to capture its responses
        try:
            self.engineer.register_reply(
                [autogen.Agent, None],
                on_agent_message,
                position=0  # Execute before other reply functions
            )
            logger.debug("Streaming callbacks registered successfully")
        except Exception as e:
            logger.warning(f"Could not register streaming callbacks: {e}")

    def reset_session(self):
        """Reset the chat session."""
        self.user_proxy.reset()
        self.engineer.reset()
        self.console.print("[dim]Ag2 Session Reset[/dim]")

    async def chat_continue(self, message: str) -> str:
        """
        Continue the conversation with the agents.

        Args:
            message: User input

        Returns:
            Agent response (summary or last message)
        """
        try:
            # In Ag2, we can continue chat by initiating again with clear_history=False
            # But UserProxyAgent.initiate_chat usually starts a new flow.
            # For continuous chat, we might need to use send() if we were in a loop,
            # but here we are bridging sync/async in a REPL.

            # The simplest way for Autogen 0.2+ to maintain state is to NOT reset agents
            # and call initiate_chat again. Autogen agents keep history by default unless reset.

            # We use a custom summary method to get the last meaningful response
            chat_result = self.user_proxy.initiate_chat(
                self.engineer,
                message=message,
                clear_history=False,
                summary_method="last_msg"
            )

            # If the chat was just a one-off tool execution, we might want to return the output.
            # But usually we return the last message from the Assistant.

            return chat_result.summary or "✅ Task completed."

        except Exception as e:
            logger.error(f"Ag2 chat failed: {e}", exc_info=True)
            return f"❌ Error: {str(e)}"

    def _display_priority(self, result: PriorityResult) -> None:
        """Display priority classification to user."""
        priority = result.priority
        color = priority.color
        label = priority.label

        # Build priority display
        priority_text = f"[bold {color}]{priority.name}[/bold {color}] - {label}"

        # Add environment if detected
        if result.environment_detected:
            priority_text += f" | env: {result.environment_detected}"

        # Add service/host if detected
        if result.service_detected:
            priority_text += f" | service: {result.service_detected}"
        if result.host_detected:
            priority_text += f" | host: {result.host_detected}"

        # Display with panel
        self.console.print(Panel(
            f"{priority_text}\n[dim]{result.reasoning}[/dim]",
            title="🎯 Triage",
            border_style=color,
            padding=(0, 1),
        ))

        # Show behavior mode
        behavior_desc = describe_behavior(priority)
        self.console.print(f"[dim]Mode: {behavior_desc}[/dim]\n")

    async def process_request(
        self,
        user_query: str,
        auto_confirm: bool = False,
        dry_run: bool = False,
        **kwargs
    ) -> str:
        """
        Process request using Multi-Agent conversation.

        Flow:
        1. Classify priority (P0-P3)
        2. Get behavior profile
        3. Display triage result
        4. Execute with appropriate behavior
        """
        if dry_run:
            return "🔍 Dry run not supported in Ag2 mode yet."

        # Step 1: Classify priority
        system_state = kwargs.get("system_state")
        self.current_priority = self.priority_classifier.classify(
            user_query,
            system_state=system_state,
        )

        # Step 2: Get behavior profile
        self.current_behavior = get_behavior(self.current_priority.priority)

        # Step 3: Display triage result
        self._display_priority(self.current_priority)

        # Step 4: Apply behavior-based auto-confirm
        # If behavior allows auto-confirm for reads, enable it

        # Log priority for debugging
        logger.info(
            f"Request classified as {self.current_priority.priority.name} "
            f"(confidence: {self.current_priority.confidence:.0%})"
        )

        # Execute - spinner is handled by REPL caller
        # Callbacks display intermediate progress (Engineer, Tool, Result)
        return await self.chat_continue(user_query)
