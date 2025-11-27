"""
Diagnostic Agent - Infrastructure problem investigation.

Follows DIP: Uses injected console from DisplayManager singleton.
"""
import json
from typing import Any, Dict

from athena_ai.agents.base import BaseAgent
from athena_ai.utils.display import get_display_manager
from athena_ai.utils.logger import logger


class DiagnosticAgent(BaseAgent):
    """Agent for diagnosing infrastructure issues."""

    def __init__(self, context_manager, **kwargs):
        super().__init__(context_manager, **kwargs)
        self.name = "DiagnosticAgent"
        # DIP: Use injected display manager instead of global Console
        self._display = get_display_manager()

    def run(self, task: str, target: str = "local", confirm: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        logger.info(f"DiagnosticAgent starting task: {task} on {target}")

        # 1. Gather Context
        context = self.context_manager.get_context()
        inventory = context.get("inventory", {})
        local_info = context.get("local", {})

        # 2. Plan (via LLM)
        plan_prompt = f"""
        Task: {task}
        Target: {target}
        Context:
        - Local: {json.dumps(local_info, indent=2)}
        - Inventory: {json.dumps(inventory, indent=2)}

        Propose a list of diagnostic commands to run.
        Return ONLY a JSON list of strings, e.g. ["command1", "command2"].
        """
        system_prompt = "You are an expert infrastructure diagnostic agent. Return only raw JSON."

        try:
            plan_response = self.llm.generate(plan_prompt, system_prompt)
            # Clean up response if needed (remove markdown blocks)
            plan_response = plan_response.replace("```json", "").replace("```", "").strip()
            commands = json.loads(plan_response)
        except Exception as e:
            logger.error(f"Failed to generate plan: {e}")
            return {"error": "Planning failed"}

        if dry_run:
            return {
                "plan": commands,
                "analysis": "Dry run mode: Commands were planned but not executed.",
                "results": {}
            }

        # Interactive Confirmation
        if not confirm:
            self._display.console.print("\n[bold]Proposed Diagnostic Plan:[/bold]")
            for i, cmd in enumerate(commands, 1):
                self._display.console.print(f"  {i}. [cyan]{cmd}[/cyan]")

            import click
            if not click.confirm("\nDo you want to execute these commands?", default=False):
                logger.info("User cancelled execution.")
                return {
                    "plan": commands,
                    "analysis": "User cancelled execution.",
                    "results": {}
                }
            # If confirmed here, we treat it as confirmed for ActionExecutor
            confirm = True

        # 3. Execute
        results = {}
        for cmd in commands:
            res = self.executor.execute(target, cmd, confirm=confirm)
            results[cmd] = res

        # 4. Analyze (via LLM)
        analysis_prompt = f"""
        Task: {task}
        Results: {json.dumps(results, indent=2)}

        Analyze these results and provide a root cause and recommendations.
        """
        analysis = self.llm.generate(analysis_prompt, system_prompt)

        return {
            "plan": commands,
            "results": results,
            "analysis": analysis
        }
