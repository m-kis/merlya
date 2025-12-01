"""
Base Agent - Abstract base class for all Athena agents.

Follows Dependency Inversion Principle (DIP):
- Dependencies are injected, not instantiated internally
- Allows for testing with mocks
- Enables different implementations per context
"""
from typing import Any, Dict, Optional

from athena_ai.context.manager import ContextManager
from athena_ai.executors.action_executor import ActionExecutor
from athena_ai.llm.router import LLMRouter


class BaseAgent:
    """
    Abstract base class for all Athena agents.

    Dependencies (llm, executor) should be injected for proper DIP compliance.
    If not provided, defaults are created for backward compatibility.
    """

    def __init__(
        self,
        context_manager: ContextManager,
        llm: Optional[LLMRouter] = None,
        executor: Optional[ActionExecutor] = None,
    ):
        """
        Initialize BaseAgent with dependencies.

        Args:
            context_manager: Context manager for environment info (required)
            llm: LLM router for AI interactions (optional, creates default if None)
            executor: Action executor for commands (optional, creates default if None)
        """
        self.context_manager = context_manager
        # DIP: Accept injected dependencies, fall back to defaults for compatibility
        self.llm = llm if llm is not None else LLMRouter()
        self.executor = executor if executor is not None else ActionExecutor()
        self.name = "BaseAgent"

    def run(self, task: str, **kwargs: Any) -> Any:
        """Execute the agent's main logic."""
        raise NotImplementedError("Agents must implement run()")

    def _get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return "You are an AI assistant."
