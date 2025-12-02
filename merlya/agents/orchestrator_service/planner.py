from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from rich.console import Console

from merlya.agents import autogen_tools, knowledge_tools
from merlya.triage.behavior import BehaviorProfile, get_behavior
from merlya.triage.priority import Priority
from merlya.utils.logger import logger

if TYPE_CHECKING:
    from autogen_agentchat.base import TaskResult

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

    def __init__(self, model_client: Any, tools: List[Callable[..., Any]], env: str = "dev", console: Optional[Console] = None):
        self.model_client = model_client
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
        self.engineer = AssistantAgent(  # type: ignore[assignment]
            name="DevSecOps_Engineer",
            model_client=self.model_client,
            tools=self.tools,  # type: ignore[arg-type]
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
        """Get system prompt for Engineer - Expert DevSecOps/Linux Engineer.

        Optimized for token efficiency while maintaining capability.
        """
        return f"""You are an expert DevSecOps/Linux Engineer. You THINK, ANALYZE, and RECOMMEND solutions—not just execute commands blindly.

TOOLS:
- HOSTS: list_hosts(), scan_host(hostname), check_permissions(target)
- EXEC: execute_command(target, command, reason)
- FILES: read_remote_file(host, path), write_remote_file(host, path, content), tail_logs(host, path, lines, grep)
- SYSTEM: disk_info(host), memory_info(host), process_list(host), network_connections(host), service_control(host, service, action)
- CONTAINERS: docker_exec(container, command), kubectl_exec(namespace, pod, command)
- VARIABLES: get_user_variables(), get_variable_value(name) - access user-defined @variables
- INTERACTION: ask_user(question), request_elevation(target, command, error_message)

VARIABLES SYSTEM:
- Users define variables with `/variables set <key> <value>` (e.g., @Test, @proddb)
- When asked about a @variable, use get_variable_value(name) to retrieve it
- Use get_user_variables() to list all defined variables
- @variables are substituted in queries, so "check @myserver" becomes "check actual-hostname"

WORKFLOW:
1. Understand the real problem
2. Gather info (logs, configs, status) - use tools appropriately
3. Analyze and explain findings clearly
4. Recommend solutions with example commands
5. Execute only when asked or for simple actions

RULES:
- list_hosts() FIRST before acting on hosts
- EXPLAIN reasoning, don't just execute
- On "Permission denied" → use request_elevation()
- After ask_user() → CONTINUE task, don't terminate
- For @variable queries → use get_variable_value() or get_user_variables()

RESPONSE FORMAT (Markdown with sections: Analysis, Recommendations, Next Steps)

TERMINATION: Always provide a summary before TERMINATE. Never terminate without content.

Environment: {self.env}"""

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
        Detect if query is about user variables and provide context hint.

        Returns a context string if variable-related, None otherwise.
        """
        import re

        query_lower = user_query.lower()

        # Detect variable-related queries
        variable_patterns = [
            r'@\w+',                    # Direct @variable reference
            r'variable',                # Mentions "variable"
            r'variables',               # Mentions "variables"
            r'affiche.*variable',       # French: "display variable"
            r'montre.*variable',        # French: "show variable"
            r'liste.*variable',         # French: "list variable"
            r'show.*variable',          # English: "show variable"
            r'display.*variable',       # English: "display variable"
            r'list.*variable',          # English: "list variable"
            r'what.*is.*@',             # "What is @..."
            r'qu.*est.*@',              # French: "What is @..."
            r'valeur.*@',               # French: "value of @..."
            r'value.*@',                # English: "value of @..."
        ]

        for pattern in variable_patterns:
            if re.search(pattern, query_lower):
                return """📌 **VARIABLE QUERY DETECTED**
This query is about user-defined @variables in Merlya.
Use get_user_variables() to list all variables, or get_variable_value(name) to get a specific one.
Variables are set via `/variables set <key> <value>` and can be used as @key in queries."""

        return None

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
        behavior = self._get_behavior_for_priority(priority_name)

        # Detect variable-related queries
        variable_context = self._detect_variable_query(user_query)

        # Build task with conversation context
        task = self._build_task_with_context(user_query, conversation_history, variable_context)

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
        behavior = self._get_behavior_for_priority(priority_name)

        # Detect variable-related queries
        variable_context = self._detect_variable_query(user_query)

        # Build base task with context
        base_task = self._build_task_with_context(user_query, conversation_history, variable_context)

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
        if self.team is None:
            raise RuntimeError("Team not initialized. Call init_agents() with mode='enhanced' first.")
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

        # If we got a real synthesis (not empty or just task completed), return it
        if synthesis and synthesis not in ("", "✅ Task completed."):
            return synthesis

        # No synthesis found - collect tool outputs and generate one
        tool_outputs = self._collect_tool_outputs(result)

        if not tool_outputs:
            # No tool outputs either - provide helpful message based on context
            logger.warning("⚠️ No synthesis and no tool outputs found in response")
            return self._get_fallback_response(user_query)

        # Ask LLM to synthesize the outputs
        return await self._generate_synthesis(user_query, tool_outputs)

    def _get_fallback_response(self, user_query: str) -> str:
        """Generate a helpful fallback response when agent produced no output."""
        query_lower = user_query.lower()

        # Check for common query types and provide helpful guidance
        if any(word in query_lower for word in ['list', 'show', 'display']):
            if 'host' in query_lower or 'server' in query_lower:
                return """## ℹ️ No Hosts Found

No hosts are configured in your inventory yet.

### Quick Setup:
1. **Add a host manually:**
   ```
   /inventory add-host myserver
   ```

2. **Import from Ansible inventory:**
   ```
   /inventory import ansible /path/to/inventory
   ```

3. **Configure SSH key (optional):**
   ```
   /inventory ssh-key set ~/.ssh/id_ed25519
   ```

Use `/inventory help` for more options."""

        if 'scan' in query_lower or 'check' in query_lower:
            return """## ℹ️ Unable to Scan

Could not complete the scan. Possible reasons:
- No hosts configured (use `/inventory add-host`)
- SSH key not configured (use `/inventory ssh-key set`)
- Host unreachable (check network/firewall)

Use `list hosts` to see available hosts."""

        # Generic fallback
        return """## ℹ️ Task Completed

The task was processed but no specific results were returned.

This can happen when:
- No hosts are configured yet
- The requested resource doesn't exist
- A connection issue occurred

Try:
- `/inventory` to check your hosts
- `/help` for available commands"""

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
        if FunctionExecutionResult is not None and isinstance(content, FunctionExecutionResult):
            return str(content.content) if content.content else ""

        # Handle list of content items
        if isinstance(content, list):
            parts = []
            for item in content:
                if FunctionExecutionResult is not None and isinstance(item, FunctionExecutionResult):
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
        """Extract response from TaskResult.

        Handles multiple message types and ensures we never return empty responses.
        If no clear synthesis is found, returns None to trigger synthesis generation.
        """
        if not result.messages:
            return "✅ Task completed."

        # Debug: Log all messages to understand structure
        logger.debug(f"TaskResult has {len(result.messages)} messages")
        for i, msg in enumerate(result.messages):
            msg_type = type(msg).__name__
            raw_content = getattr(msg, 'content', None)
            content_type = type(raw_content).__name__ if raw_content else 'None'
            logger.debug(f"  [{i}] {msg_type}: content_type={content_type}")

        # Collect all potential response content (not just last message)
        candidate_responses = []

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

            # Clean up TERMINATE from response
            content = content.strip()

            # Remove TERMINATE from end (with possible trailing whitespace/newlines)
            if content.endswith("TERMINATE"):
                content = content[:-9].rstrip()

            # Also handle case where TERMINATE is on its own line at the end
            lines = content.split('\n')
            while lines and lines[-1].strip() == "TERMINATE":
                lines.pop()
            content = '\n'.join(lines).strip()

            # Skip if content is ONLY "TERMINATE" or empty after cleaning
            if not content or content == "TERMINATE":
                continue

            # We found a valid response
            if content:
                candidate_responses.append(content)
                # Return first valid response (most recent)
                return content

        # If we found no valid response content, signal for synthesis
        # Return None instead of generic message so caller can generate synthesis
        if not candidate_responses:
            return ""  # Empty signals need for synthesis

        return "✅ Task completed."
