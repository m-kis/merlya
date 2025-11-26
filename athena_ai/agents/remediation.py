import json
from typing import Any, Dict

from athena_ai.agents.base import BaseAgent
from athena_ai.remediation.rollback import RollbackManager
from athena_ai.utils.logger import logger


class RemediationAgent(BaseAgent):
    def __init__(self, context_manager):
        super().__init__(context_manager)
        self.name = "RemediationAgent"
        self.rollback_manager = RollbackManager()

    def run(self, task: str, target: str = "local", confirm: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        logger.info(f"RemediationAgent starting task: {task} on {target}")

        context = self.context_manager.get_context()

        # 1. Plan Remediation
        plan_prompt = f"""
        Task: {task}
        Target: {target}
        Context: {json.dumps(context.get('local', {}), indent=2)}

        Propose a list of remediation actions.
        Each action should be a JSON object with:
        - "command": string
        - "type": "shell" | "edit_file"
        - "details": dict (e.g. path for edit_file)

        Return ONLY a JSON list of objects.
        """
        system_prompt = "You are an expert infrastructure remediation agent. Return only raw JSON."

        try:
            plan_response = self.llm.generate(plan_prompt, system_prompt)
            plan_response = plan_response.replace("```json", "").replace("```", "").strip()
            actions = json.loads(plan_response)
        except Exception as e:
            logger.error(f"Failed to generate remediation plan: {e}")
            return {"error": "Planning failed"}

        if dry_run:
            return {
                "plan": actions,
                "analysis": "Dry run: Remediation actions planned but not executed.",
                "results": {}
            }

        # 2. Execute with Rollback Prep
        results = {}
        rollbacks = []

        for action in actions:
            cmd = action.get("command")
            action_type = action.get("type", "shell")
            details = action.get("details", {})

            # Prepare Rollback
            rollback_plan = self.rollback_manager.prepare_rollback(target, action_type, details)
            if rollback_plan["type"] != "none":
                rollbacks.append(rollback_plan)

            # Execute
            res = self.executor.execute(target, cmd, confirm=confirm)
            results[cmd] = res

            if not res["success"]:
                logger.error(f"Action failed: {cmd}. Initiating rollback...")
                # Trigger rollback of previous actions if needed
                # For MVP, we just stop. Real implementation would rollback stack.
                break

        return {
            "plan": actions,
            "results": results,
            "rollbacks_created": rollbacks
        }
