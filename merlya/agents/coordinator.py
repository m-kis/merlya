"""
Agent Coordinator - Orchestrates multiple specialized agents.

Refactored to use AgentRegistry (OCP) instead of hard-coded if/elif chains.
Adding new agents requires only registration, not code modification here.
"""
import json
import re
from typing import Any, Dict

from merlya.context.manager import ContextManager
from merlya.core.registry import get_registry, register_builtin_agents
from merlya.llm.router import LLMRouter
from merlya.utils.logger import logger


class AgentCoordinator:
    """
    Coordinates multiple agents to fulfill complex requests.

    Uses AgentRegistry for dynamic agent lookup (OCP principle).
    The coordinator doesn't need modification when new agents are added.
    """

    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager
        self.llm = LLMRouter()
        self._registry = get_registry()

        # Ensure built-in agents are registered
        if not self._registry.list_all():
            register_builtin_agents()

    def coordinate(
        self,
        user_query: str,
        target: str = "local",
        confirm: bool = False,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Coordinate multiple agents to fulfill a request.

        Args:
            user_query: The user's request
            target: Target host
            confirm: Auto-confirm actions
            dry_run: Preview without executing

        Returns:
            Coordination results with plan and step outcomes
        """
        logger.info(f"Coordinating request: {user_query}")

        # Get context for environment awareness
        context = self.context_manager.get_context()
        inventory = context.get("inventory", {})
        local_info = context.get("local", {})

        # Get available agents from registry
        available_agents = self._registry.list_with_descriptions()

        # 1. Decompose Task via LLM
        plan = self._create_plan(user_query, target, inventory, local_info, available_agents)

        if "error" in plan:
            return plan

        # 2. Execute Plan Steps
        results = self._execute_plan(plan, target, confirm, dry_run)

        return {
            "coordination_plan": plan,
            "step_results": results
        }

    def _create_plan(
        self,
        user_query: str,
        target: str,
        inventory: Dict,
        local_info: Dict,
        available_agents: Dict[str, str]
    ) -> Dict[str, Any]:
        """Create execution plan using LLM."""
        # Format available agents for prompt
        agents_list = "\n".join(
            f"- {name}: {desc}" for name, desc in available_agents.items()
        )

        plan_prompt = f"""
        User Query: {user_query}
        Target: {target}

        Environment Context:
        - Inventory (Hosts): {json.dumps(inventory, indent=2)}
        - Local System: {local_info.get('hostname')} ({local_info.get('os')})

        Decide which agents to call and in what order.
        Available Agents:
        {agents_list}

        Return a JSON plan:
        {{
            "steps": [
                {{ "agent": "DiagnosticAgent", "task": "..." }},
                {{ "agent": "CloudAgent", "task": "..." }}
            ]
        }}
        """
        system_prompt = "You are an expert agent coordinator. Return only raw JSON."

        try:
            plan_response = self.llm.generate(plan_prompt, system_prompt)
            logger.debug(f"Raw LLM Plan Response: {plan_response}")

            # Robust JSON extraction
            json_match = re.search(r'\{.*\}', plan_response, re.DOTALL)
            if json_match:
                plan_response = json_match.group(0)

            return json.loads(plan_response)

        except Exception as e:
            plan_str = plan_response if 'plan_response' in locals() else 'None'
            logger.error(f"Coordination planning failed: {e}. Response: {plan_str}")
            return {"error": "Coordination failed"}

    def _execute_plan(
        self,
        plan: Dict[str, Any],
        target: str,
        confirm: bool,
        dry_run: bool
    ) -> list[Dict[str, Any]]:
        """Execute plan steps using registry for agent lookup."""
        results = []

        for step in plan.get("steps", []):
            agent_name = step["agent"]
            task = step["task"]

            logger.info(f"Dispatching to {agent_name}: {task}")

            step_result = self._dispatch_to_agent(
                agent_name, task, target, confirm, dry_run
            )

            results.append({
                "agent": agent_name,
                "task": task,
                "result": step_result
            })

        return results

    def _dispatch_to_agent(
        self,
        agent_name: str,
        task: str,
        target: str,
        confirm: bool,
        dry_run: bool
    ) -> Dict[str, Any]:
        """
        Dispatch task to agent using registry lookup.

        OCP: New agents only need registration, not code changes here.
        """
        if not self._registry.has(agent_name):
            available = ", ".join(self._registry.list_all())
            return {
                "error": f"Unknown agent '{agent_name}'. Available: {available}"
            }

        try:
            # Get agent from registry
            agent = self._registry.get(
                agent_name,
                context_manager=self.context_manager
            )

            # Execute with standard interface
            return agent.run(task, target, confirm, dry_run)

        except Exception as e:
            logger.error(f"Agent {agent_name} failed: {e}")
            return {"error": str(e)}
