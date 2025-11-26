from typing import Any, Dict

from athena_ai.context.manager import ContextManager
from athena_ai.executors.action_executor import ActionExecutor
from athena_ai.llm.router import LLMRouter


class BaseAgent:
    def __init__(self, context_manager: ContextManager):
        self.llm = LLMRouter()
        self.context_manager = context_manager
        self.executor = ActionExecutor()
        self.name = "BaseAgent"

    def run(self, task: str) -> Dict[str, Any]:
        """Execute the agent's main logic."""
        raise NotImplementedError("Agents must implement run()")

    def _get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        return "You are an AI assistant."
