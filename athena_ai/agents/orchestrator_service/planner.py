from typing import Any, Callable, List, Optional

from rich.console import Console

from athena_ai.agents import autogen_tools, knowledge_tools
from athena_ai.triage.behavior import BehaviorProfile, get_behavior
from athena_ai.triage.priority import Priority
from athena_ai.utils.logger import logger

# Optional imports
try:
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.base import TaskResult
    from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
    from autogen_agentchat.messages import FunctionExecutionResult
    from autogen_agentchat.teams import RoundRobinGroupChat, SelectorGroupChat
    HAS_AUTOGEN = True
except ImportError:
    HAS_AUTOGEN = False
    FunctionExecutionResult = None  # type: ignore

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
1. START with Planner to create a plan (unless it's a simple follow-up).
2. Planner -> Security_Expert (to review the plan).
3. Security_Expert -> DevSecOps_Engineer (to execute).
4. DevSecOps_Engineer -> Planner (if plan needs adjustment) or TERMINATE (if done).
5. Knowledge_Manager can be called at any time to store findings.

Return only the agent name.""",
        )

    def _get_engineer_prompt(self) -> str:
        """Get system prompt for Engineer - Expert DevSecOps/Linux Engineer."""
        return f"""You are a SENIOR DevSecOps/Linux Engineer with 15+ years of experience.
You have deep expertise in: Linux systems, databases (MongoDB, PostgreSQL, MySQL),
Kubernetes, Docker, networking, security, and infrastructure automation.

YOUR ROLE:
- You are NOT just a command executor
- You THINK like an expert engineer: analyze, understand root causes, propose solutions
- You EXPLAIN technical concepts clearly
- You RECOMMEND best practices and alternatives
- You GUIDE users through complex problems

Available Tools:
CORE: list_hosts(), scan_host(hostname), execute_command(target, command, reason), check_permissions(target)
FILES: read_remote_file(host, path, lines), write_remote_file(host, path, content, backup), tail_logs(host, path, lines, grep)
SYSTEM: disk_info(host), memory_info(host), process_list(host), network_connections(host)
SERVICES: service_control(host, service, action)
CONTAINERS: docker_exec(container, command, host), kubectl_exec(namespace, pod, command)
INTERACTION: ask_user(question), request_elevation(target, command, error_message, reason)

HOW TO RESPOND:
1. **Understand first**: What is the user REALLY trying to solve?
2. **Investigate**: Gather relevant information (logs, configs, status)
3. **Analyze**: Identify root cause or explain current state
4. **Recommend**: Propose solutions with clear explanations
5. **Execute if asked**: Only execute after explaining what you'll do

RESPONSE FORMAT (Markdown):
## Analysis
[What you found and what it means]

## Root Cause / Explanation
[Technical explanation in clear terms]

## Recommendations
[Concrete solutions with example commands]
```bash
# Example command with explanation
command here
```

## Next Steps
[What the user should do next]

IMPORTANT RULES:
- Use list_hosts() FIRST to verify hosts exist
- ALWAYS scan a host before acting on it
- EXPLAIN your reasoning, don't just execute blindly
- For complex issues, ASK if the user wants you to execute fixes
- When using ask_user() to get information, CONTINUE the task after receiving the response - do NOT terminate until the full task is complete
- When a command fails with "Permission denied", use request_elevation() to ask user for privilege escalation
- Say "TERMINATE" ONLY at the END of your FINAL summary, after completing ALL requested actions

Environment: {self.env}"""

    def _build_task_with_context(self, user_query: str, conversation_history: List[dict] = None) -> str:
        """
        Build task string with conversation context.

        Injects recent conversation history so the agent understands
        references like "this server", "the file", etc.
        """
        if not conversation_history:
            return user_query

        # Take last N exchanges (user + assistant pairs) to keep context manageable
        max_context_messages = 6  # 3 exchanges
        recent = conversation_history[-max_context_messages:]

        if not recent:
            return user_query

        # Build context summary
        context_parts = ["[Previous conversation context:]"]
        for msg in recent:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            prefix = "User" if role == "user" else "Assistant"
            context_parts.append(f"{prefix}: {content}")

        context_parts.append("\n[Current request:]")
        context_parts.append(user_query)

        return "\n".join(context_parts)

    def _get_behavior_for_priority(self, priority_name: str) -> BehaviorProfile:
        """Get BehaviorProfile for a priority level."""
        try:
            priority = Priority[priority_name]
            return get_behavior(priority)
        except (KeyError, ValueError):
            # Default to P3 behavior (most careful)
            return get_behavior(Priority.P3)

    def _get_priority_guidance(self, priority_name: str) -> str:
        """Get priority-specific execution guidance."""
        behavior = self._get_behavior_for_priority(priority_name)

        if priority_name in ("P0", "P1"):
            return f"""
🚨 **PRIORITY: {priority_name} - FAST RESPONSE MODE**
- Act quickly: gather essential info and respond
- Auto-confirm read operations
- Maximum {behavior.max_commands_before_pause} commands before pause
- Use {behavior.response_format} responses
- Focus on immediate resolution"""
        elif priority_name == "P2":
            return f"""
⚠️ **PRIORITY: {priority_name} - THOROUGH MODE**
- Take time to analyze thoroughly
- Show your reasoning
- Confirm write operations
- Maximum {behavior.max_commands_before_pause} commands before pause
- Provide detailed explanations"""
        else:  # P3
            return f"""
📋 **PRIORITY: {priority_name} - CAREFUL MODE**
- Full analysis with chain-of-thought
- Confirm all operations
- Maximum {behavior.max_commands_before_pause} commands before pause
- Detailed responses with explanations
- Let user decide next steps"""

    def _get_intent_guidance(self, intent: str) -> str:
        """Get intent-specific guidance to inject into the task."""
        if intent == "analysis":
            return """
🔍 **MODE: ANALYSIS** - Your focus is to INVESTIGATE and RECOMMEND.
- Dig deep: check logs, configs, status
- EXPLAIN what you find in clear terms
- PROPOSE solutions with example commands
- Ask before executing any fixes
- This is a teaching moment: educate the user"""

        elif intent == "query":
            return """
📋 **MODE: QUERY** - Your focus is to GATHER and PRESENT information.
- Collect the requested information efficiently
- Present results clearly and organized
- This is READ-ONLY: avoid making changes"""

        else:  # action
            return """
⚡ **MODE: ACTION** - Your focus is to EXECUTE safely.
- Verify targets before acting
- Execute the requested task
- Report results clearly"""

    async def execute_basic(
        self,
        user_query: str,
        conversation_history: List[dict] = None,
        allowed_tools: List[str] = None,
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
        behavior = self._get_behavior_for_priority(priority_name)

        # Build task with conversation context
        task = self._build_task_with_context(user_query, conversation_history)

        # Add priority-specific guidance (adapts agent behavior)
        priority_guidance = self._get_priority_guidance(priority_name)

        # Add intent-specific guidance
        intent_guidance = self._get_intent_guidance(intent)
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
        # Adjust message limit based on priority (P0/P1 = faster, fewer iterations)
        if priority_name in ("P0", "P1"):
            max_messages = 15  # Faster response
        else:
            max_messages = 25  # More thorough

        termination = TextMentionTermination("TERMINATE") | MaxMessageTermination(max_messages)

        team = RoundRobinGroupChat(
            participants=[self.engineer],
            termination_condition=termination,
        )

        # Run the team
        result = await team.run(task=task)

        # Extract or generate synthesis
        return await self._extract_or_synthesize(result, user_query)

    async def execute_enhanced(
        self,
        user_query: str,
        priority_name: str,
        conversation_history: List[dict] = None,
        allowed_tools: List[str] = None,
        intent: str = "action",
        knowledge_context: str = None,
    ) -> str:
        """Process with multi-agent team."""
        if not HAS_AUTOGEN:
            raise ImportError(
                "autogen-agentchat is required for execute_enhanced(). "
                "Install with: pip install autogen-agentchat"
            )
        self.console.print("[bold cyan]🤖 Multi-Agent Team Active...[/bold cyan]")

        # Get behavior profile based on priority
        behavior = self._get_behavior_for_priority(priority_name)

        # Build base task with context
        base_task = self._build_task_with_context(user_query, conversation_history)

        # Add priority-specific guidance (adapts agent behavior)
        priority_guidance = self._get_priority_guidance(priority_name)

        # Add intent-specific guidance
        intent_guidance = self._get_intent_guidance(intent)

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

        # Run the team
        result = await self.team.run(task=task)

        return await self._extract_or_synthesize(result, user_query)

    async def _extract_or_synthesize(self, result: "TaskResult", user_query: str) -> str:
        """
        Extract synthesis from result, or generate one if missing.

        If the agent didn't provide a clear synthesis, collect tool outputs
        and ask the LLM to synthesize them.
        """
        # First, try to find an existing synthesis
        synthesis = self._extract_response(result)

        # If we got a real synthesis (not just task completed), return it
        if synthesis and synthesis != "✅ Task completed.":
            return synthesis

        # No synthesis found - collect tool outputs and generate one
        tool_outputs = self._collect_tool_outputs(result)

        if not tool_outputs:
            return "✅ Task completed - no data collected."

        # Ask LLM to synthesize the outputs
        return await self._generate_synthesis(user_query, tool_outputs)

    def _collect_tool_outputs(self, result: "TaskResult") -> List[str]:
        """Collect all tool execution outputs from the conversation."""
        outputs = []

        for msg in result.messages:
            raw_content = getattr(msg, 'content', '')
            if not raw_content:
                continue

            # Extract actual string content from autogen objects
            content = self._extract_content(raw_content)
            if not content:
                continue

            # Collect tool results
            if content.startswith("✅ SUCCESS") or content.startswith("❌ ERROR"):
                # Extract just the output part, not the status prefix
                if "\nOutput:" in content:
                    output_part = content.split("\nOutput:", 1)[1].strip()
                    if output_part and len(output_part) < 2000:  # Limit size
                        outputs.append(output_part)

        return outputs

    async def _generate_synthesis(self, user_query: str, tool_outputs: List[str]) -> str:
        """Generate a synthesis from tool outputs using the LLM."""
        # Combine outputs (limit total size)
        combined = "\n---\n".join(tool_outputs[:5])  # Max 5 outputs
        if len(combined) > 4000:
            combined = combined[:4000] + "\n... (truncated)"

        synthesis_prompt = f"""Based on the following command outputs, provide a clear, concise answer to the user's question.

User question: {user_query}

Command outputs:
{combined}

Instructions:
- Answer the user's question directly
- Summarize key findings
- Use markdown formatting
- Be concise but complete
- Include any recommendations if relevant

Provide your synthesis now:"""

        try:
            # Use the model client to generate synthesis
            from autogen_core import CancellationToken

            response = await self.model_client.create(
                messages=[{"role": "user", "content": synthesis_prompt}],
                cancellation_token=CancellationToken(),
            )

            if response and response.content:
                return response.content
        except Exception:
            # Fallback: return a basic summary
            return f"## Résumé\n\nCommandes exécutées avec succès.\n\n### Données collectées:\n```\n{combined[:1000]}\n```"

        return "✅ Task completed."

    def _extract_content(self, content: Any) -> str:
        """
        Extract string content from autogen message content.

        Handles FunctionExecutionResult, lists, dicts, and strings.
        """
        if content is None:
            return ""

        # Handle FunctionExecutionResult (autogen 0.7+ tool results)
        if FunctionExecutionResult and isinstance(content, FunctionExecutionResult):
            return str(content.content) if content.content else ""

        # Handle list of content items
        if isinstance(content, list):
            parts = []
            for item in content:
                if FunctionExecutionResult and isinstance(item, FunctionExecutionResult):
                    parts.append(str(item.content) if item.content else "")
                elif isinstance(item, dict):
                    parts.append(str(item.get('text', item)))
                else:
                    parts.append(str(item))
            return "\n".join(parts)

        # Handle dict content
        if isinstance(content, dict):
            return str(content.get('text', content))

        # Already a string
        if isinstance(content, str):
            return content

        # Fallback: convert to string
        return str(content)

    def _extract_response(self, result: "TaskResult") -> str:
        """Extract response from TaskResult."""
        if not result.messages:
            return "✅ Task completed."

        # Debug: Log all messages to understand structure
        logger.debug(f"TaskResult has {len(result.messages)} messages")
        for i, msg in enumerate(result.messages):
            msg_type = type(msg).__name__
            raw_content = getattr(msg, 'content', None)
            content_type = type(raw_content).__name__ if raw_content else 'None'
            logger.debug(f"  [{i}] {msg_type}: content_type={content_type}")

        # Get last message from the assistant (not tool results)
        for msg in reversed(result.messages):
            # Check for TextMessage or similar final response types
            msg_type = type(msg).__name__

            # Skip tool-related messages
            if msg_type in ('ToolCallRequestEvent', 'ToolCallExecutionEvent', 'ToolCallSummaryMessage'):
                continue

            raw_content = getattr(msg, 'content', '')
            if not raw_content:
                continue

            # Extract actual string content from autogen objects
            content = self._extract_content(raw_content)
            if not content:
                continue

            # Skip tool call results (they start with SUCCESS/ERROR or are raw output)
            if content.startswith("✅ SUCCESS") or content.startswith("❌ ERROR"):
                continue

            # Clean up TERMINATE only from the end of the response
            content = content.strip()
            if content.endswith("TERMINATE"):
                content = content[:-9].strip()  # Remove "TERMINATE" from end

            if content:
                return content

        return "✅ Task completed."
