from typing import Callable, List

from rich.console import Console

from athena_ai.agents import autogen_tools, knowledge_tools

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

    def __init__(self, model_client, tools: List[Callable], env: str = "dev", console: Console = None):
        self.model_client = model_client
        self.tools = tools
        self.env = env
        self.console = console or Console()

        self.engineer = None
        self.planner = None
        self.security_expert = None
        self.knowledge_manager = None
        self.team = None

    def init_agents(self, mode: str, knowledge_db=None):
        """Initialize agents based on mode."""
        # Engineer (main agent with tools)
        self.engineer = AssistantAgent(
            name="DevSecOps_Engineer",
            model_client=self.model_client,
            tools=self.tools,
            system_message=self._get_engineer_prompt(),
            description="Expert DevSecOps engineer who executes infrastructure tasks using tools.",
        )

        # Additional agents for ENHANCED mode
        if mode == "enhanced":
            self._init_enhanced_agents(knowledge_db)
            self._init_team()

    def _init_enhanced_agents(self, knowledge_db):
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
        if knowledge_db:
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

    def _init_team(self):
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
4. Be EFFICIENT: Only run necessary commands, avoid redundant checks
5. ALWAYS end with a clear, human-readable summary explaining your findings

IMPORTANT: Your FINAL message must be a clear summary for the user, NOT raw command output.
Format your final response in markdown with:
- Brief answer to the user's question
- Key findings (if applicable)
- Any recommendations

Say "TERMINATE" at the END of your final summary message.

Environment: {self.env}"""

    async def execute_basic(self, user_query: str) -> str:
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

    async def execute_enhanced(self, user_query: str, priority_name: str) -> str:
        """Process with multi-agent team."""
        self.console.print("[bold cyan]🤖 Multi-Agent Team Active...[/bold cyan]")

        task = f"""
Task: {user_query}

Priority: {priority_name}
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

        # Get last message from the assistant (not tool results)
        for msg in reversed(result.messages):
            content = getattr(msg, 'content', '')
            if not content:
                continue

            # Skip tool call results (they start with SUCCESS/ERROR or are raw output)
            if content.startswith("✅ SUCCESS") or content.startswith("❌ ERROR"):
                continue

            # Clean up TERMINATE from the response
            if "TERMINATE" in content:
                content = content.replace("TERMINATE", "").strip()

            if content:
                return content

        return "✅ Task completed."
