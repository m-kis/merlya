"""
Merlya Subagents - Factory.

Creates ephemeral agents for parallel host execution.
"""

from __future__ import annotations

import re
import threading
import uuid
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai import Agent

from merlya.config.constants import DEFAULT_TOOL_RETRIES, LLM_TIMEOUT_DEFAULT, REQUEST_LIMIT_SKILL
from merlya.config.provider_env import ensure_provider_env

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.skills.models import SkillConfig

# Constants
DEFAULT_SUBAGENT_MODEL = "anthropic:claude-3-5-sonnet-latest"
DEFAULT_MAX_HISTORY = 10
MAX_SYSTEM_PROMPT_LENGTH = 10000

# Input validation limits
MAX_HOST_LENGTH = 1000
MAX_TASK_LENGTH = 10000

# Regex to remove control characters (except newlines/tabs)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


# Base system prompt for subagents
SUBAGENT_BASE_PROMPT = """You are a Merlya subagent executing a specific task on a host.

You are focused on:
- Executing the given task efficiently
- Using only the tools provided
- Reporting clear, structured results
- Not deviating from the assigned task

Context:
- Host: {host}
- Task: {task}

Rules:
1. Stay focused on the specific task
2. Report findings clearly
3. Do not explore beyond the task scope
4. Handle errors gracefully and report them
"""


class SubagentFactory:
    """Factory for creating ephemeral subagents.

    Creates PydanticAI agents configured for single-host execution
    with tool filtering and custom system prompts.

    Example:
        >>> factory = SubagentFactory(context)
        >>> agent = factory.create(
        ...     host="web-01",
        ...     skill=disk_audit_skill,
        ...     task="check disk usage",
        ... )
        >>> result = await agent.run(task)
    """

    def __init__(
        self,
        context: SharedContext,
        model: str | None = None,
        max_history: int = DEFAULT_MAX_HISTORY,
    ) -> None:
        """
        Initialize the factory.

        Args:
            context: Shared context with config and repositories.
            model: Model to use for subagents (default from config).
            max_history: Maximum history messages per subagent.
        """
        self.context = context
        self._model = model
        self.max_history = max_history
        ensure_provider_env(context.config)
        logger.debug("🏭 SubagentFactory initialized")

    @property
    def model(self) -> str:
        """Get the model to use for subagents."""
        if self._model:
            return self._model
        # Try to get from config, fallback to default
        if hasattr(self.context, "config") and self.context.config:
            provider = getattr(self.context.config.model, "provider", None)
            model = getattr(self.context.config.model, "model", None)
            if provider and model:
                return f"{provider}:{model}"
        return DEFAULT_SUBAGENT_MODEL

    def create(
        self,
        host: str,
        skill: SkillConfig | None = None,
        task: str = "",
        tools: list[str] | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
    ) -> SubagentInstance:
        """
        Create a subagent for a specific host.

        Args:
            host: Host identifier for this subagent.
            skill: Optional skill config for system prompt and tools.
            task: Task description for context.
            tools: Explicit tool list (overrides skill if provided).
            system_prompt: Custom system prompt (overrides skill if provided).
            model: Custom model (overrides factory default).

        Returns:
            SubagentInstance ready for execution.
        """
        subagent_id = str(uuid.uuid4())[:8]

        # Determine system prompt
        effective_prompt = self._build_system_prompt(
            host=host,
            task=task,
            skill=skill,
            custom_prompt=system_prompt,
        )

        # Determine tools
        effective_tools = tools if tools is not None else (skill.tools_allowed if skill else [])

        # Determine model
        effective_model = model or self.model

        logger.debug(
            f"🏭 Creating subagent {subagent_id} for host={host}, "
            f"tools={len(effective_tools)}, model={effective_model}"
        )

        return SubagentInstance(
            subagent_id=subagent_id,
            host=host,
            model=effective_model,
            system_prompt=effective_prompt,
            tools_allowed=effective_tools,
            context=self.context,
            max_history=self.max_history,
            skill_name=skill.name if skill else None,
        )

    def _build_system_prompt(
        self,
        host: str,
        task: str,
        skill: SkillConfig | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        """
        Build the system prompt for a subagent.

        Priority:
        1. Custom prompt (if provided)
        2. Skill's system_prompt (if skill provided)
        3. Base prompt with host/task context

        Args:
            host: Host identifier.
            task: Task description.
            skill: Optional skill configuration.
            custom_prompt: Optional custom prompt.

        Returns:
            Complete system prompt.
        """
        # Use custom prompt if provided
        if custom_prompt:
            prompt = self._format_prompt(custom_prompt, host, task)
        # Use skill's system prompt if available
        elif skill and skill.system_prompt:
            prompt = self._format_prompt(skill.system_prompt, host, task)
        else:
            # Build from base prompt
            prompt = SUBAGENT_BASE_PROMPT.format(host=host, task=task)

            # Add skill context if available
            if skill:
                prompt += f"\n\nSkill: {skill.name}"
                if skill.description:
                    prompt += f"\nDescription: {skill.description}"

        # Add tools guidance if skill has tool restrictions
        if skill and skill.tools_allowed:
            tools_list = ", ".join(skill.tools_allowed)
            prompt += f"\n\n## Allowed Tools\nYou may ONLY use these tools: {tools_list}"
            prompt += "\nDo NOT use any other tools not in this list."

        return prompt

    def _format_prompt(self, prompt: str, host: str, task: str) -> str:
        """Format a prompt template with host and task.

        Uses safe string replacement instead of .format() to prevent
        format string injection vulnerabilities.
        """
        # Sanitize inputs - remove control characters and limit length
        safe_host = CONTROL_CHAR_PATTERN.sub("", host)[:MAX_HOST_LENGTH]
        safe_task = CONTROL_CHAR_PATTERN.sub("", task)[:MAX_TASK_LENGTH]

        # Truncate prompt for safety
        safe_prompt = prompt[:MAX_SYSTEM_PROMPT_LENGTH]

        # Use safe string replacement instead of format()
        # This avoids format string injection vulnerabilities
        result = safe_prompt.replace("{host}", safe_host).replace("{task}", safe_task)

        # If no placeholders were replaced, append context
        if "{host}" not in prompt and "{task}" not in prompt:
            result = f"{safe_prompt}\n\nHost: {safe_host}\nTask: {safe_task}"

        return result


class SubagentInstance:
    """An ephemeral subagent instance for single-host execution.

    Wraps a PydanticAI agent with host-specific configuration
    and tool filtering.

    Example:
        >>> instance = factory.create(host="web-01", skill=skill)
        >>> result = await instance.run("check disk usage")
        >>> print(result.output)
    """

    def __init__(
        self,
        subagent_id: str,
        host: str,
        model: str,
        system_prompt: str,
        tools_allowed: list[str],
        context: SharedContext,
        max_history: int = DEFAULT_MAX_HISTORY,
        skill_name: str | None = None,
    ) -> None:
        """
        Initialize the subagent instance.

        Args:
            subagent_id: Unique identifier.
            host: Host this subagent targets.
            model: LLM model to use.
            system_prompt: System prompt for the agent.
            tools_allowed: List of allowed tool names.
            context: Shared context.
            max_history: Maximum history messages.
            skill_name: Name of the skill being executed.
        """
        self.subagent_id = subagent_id
        self.host = host
        self.model = model
        self.system_prompt = system_prompt
        self.tools_allowed = tools_allowed
        self.context = context
        self.max_history = max_history
        self.skill_name = skill_name

        # Create the underlying agent lazily with thread-safe lock
        self._agent: Agent[Any, Any] | None = None
        self._agent_lock = threading.Lock()
        self._tools_registered = False

    def _create_agent(self) -> Agent[Any, Any]:
        """Create the underlying PydanticAI agent."""
        from merlya.agent.main import AgentDependencies, AgentResponse

        agent = Agent(
            self.model,
            deps_type=AgentDependencies,
            output_type=AgentResponse,
            system_prompt=self.system_prompt,
            defer_model_check=True,
            retries=DEFAULT_TOOL_RETRIES,
        )

        # Register filtered tools
        self._register_filtered_tools(agent)

        return agent

    def _register_filtered_tools(self, agent: Agent[Any, Any]) -> None:
        """Register tools on the agent.

        SECURITY NOTE: Currently registers all tools and relies on system
        prompt to guide tool usage. This is an advisory control, not a
        hard enforcement. Tool filtering is enforced by:
        1. System prompt instructions (explicit "ONLY use these tools" guidance)
        2. Skill's tools_allowed list in prompt

        True tool-level filtering would require PydanticAI infrastructure
        changes (tool registry with selective registration). The current
        approach provides defense-in-depth through strong prompt guidance.

        For production use with untrusted inputs, consider additional
        validation at the tool execution layer.
        """
        from merlya.agent.tools import register_all_tools

        # Register all tools - filtering is done via system prompt guidance
        register_all_tools(agent)

        # Log tools guidance for debugging
        if self.tools_allowed:
            logger.debug(
                f"🔧 Subagent {self.subagent_id} tools guidance (advisory): {self.tools_allowed}"
            )
        else:
            logger.debug(f"🔧 Subagent {self.subagent_id} has no tool restrictions")

        self._tools_registered = True

    @property
    def agent(self) -> Agent[Any, Any]:
        """Get or create the underlying agent (thread-safe)."""
        # Double-checked locking pattern for thread safety
        if self._agent is None:
            with self._agent_lock:
                if self._agent is None:
                    self._agent = self._create_agent()
        return self._agent

    async def run(self, task: str, **kwargs: Any) -> SubagentRunResult:
        """
        Run the subagent with a task.

        Args:
            task: Task to execute.
            **kwargs: Additional arguments for agent.run().

        Returns:
            SubagentRunResult with output and metadata.
        """
        from pydantic_ai.settings import ModelSettings

        from merlya.agent.main import AgentDependencies

        deps = AgentDependencies(context=self.context)

        # Set model settings with request limit and timeout
        timeout = self.context.config.model.get_timeout()
        # Defensive check: get_timeout() should always return an int, but handle None just in case
        timeout_value = float(timeout) if timeout is not None else float(LLM_TIMEOUT_DEFAULT)
        model_settings = ModelSettings(
            request_limit=REQUEST_LIMIT_SKILL,  # type: ignore[typeddict-unknown-key]
            timeout=timeout_value,
        )

        try:
            result = await self.agent.run(
                task,
                deps=deps,
                model_settings=model_settings,
                **kwargs,
            )

            return SubagentRunResult(
                subagent_id=self.subagent_id,
                host=self.host,
                success=True,
                output=result.output.message if result.output else "",
                actions_taken=result.output.actions_taken if result.output else [],
                raw_response=result,
            )

        except Exception as e:
            logger.error(f"❌ Subagent {self.subagent_id} failed: {e}")
            return SubagentRunResult(
                subagent_id=self.subagent_id,
                host=self.host,
                success=False,
                error=str(e),
            )


class SubagentRunResult:
    """Result from a subagent run.

    Captures the output and metadata from a single subagent execution.
    """

    def __init__(
        self,
        subagent_id: str,
        host: str,
        success: bool,
        output: str = "",
        error: str | None = None,
        actions_taken: list[str] | None = None,
        raw_response: Any = None,
    ) -> None:
        """
        Initialize the run result.

        Args:
            subagent_id: Subagent identifier.
            host: Host identifier.
            success: Whether the run succeeded.
            output: Output message.
            error: Error message if failed.
            actions_taken: List of actions taken.
            raw_response: Raw PydanticAI response.
        """
        self.subagent_id = subagent_id
        self.host = host
        self.success = success
        self.output = output
        self.error = error
        self.actions_taken = actions_taken or []
        self.raw_response = raw_response

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "subagent_id": self.subagent_id,
            "host": self.host,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "actions_taken": self.actions_taken,
        }
