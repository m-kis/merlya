import json
from typing import Any, Dict

from athena_ai.agents.base import BaseAgent
from athena_ai.utils.logger import logger


class MonitoringAgent(BaseAgent):
    def __init__(self, context_manager):
        super().__init__(context_manager)
        self.name = "MonitoringAgent"

    def run(self, task: str, target: str = "local", confirm: bool = False, dry_run: bool = False) -> Dict[str, Any]:  # type: ignore[override]
        logger.info(f"MonitoringAgent starting task: {task} on {target}")

        # 1. Plan Monitoring
        plan_prompt = f"""
        Task: {task}
        Target: {target}

        Propose a list of monitoring commands to check health/status.
        Focus on read-only commands (e.g. top, df, systemctl status).

        Return ONLY a JSON list of strings.
        """
        system_prompt = "You are an expert infrastructure monitoring agent. Return only raw JSON."

        try:
            plan_response = self.llm.generate(plan_prompt, system_prompt)
            plan_response = plan_response.replace("```json", "").replace("```", "").strip()
            commands = json.loads(plan_response)
        except Exception as e:
            logger.error(f"Failed to generate monitoring plan: {e}")
            return {"error": "Planning failed"}

        if dry_run:
            return {"plan": commands, "analysis": "Dry run mode.", "results": {}}

        # 2. Execute
        results = {}
        for cmd in commands:
            res = self.executor.execute(target, cmd)
            results[cmd] = res

        # 3. Analyze Health
        analysis_prompt = f"""
        Task: {task}
        Results: {json.dumps(results, indent=2)}

        Analyze these results. Is the system healthy?
        Return a JSON object:
        {{
            "healthy": boolean,
            "issues": ["issue1", "issue2"],
            "metrics": {{ "cpu": "...", "disk": "..." }}
        }}
        """

        try:
            analysis_response = self.llm.generate(analysis_prompt, system_prompt)
            analysis_response = analysis_response.replace("```json", "").replace("```", "").strip()
            analysis = json.loads(analysis_response)
        except Exception as e:
            analysis = {"healthy": False, "issues": ["Analysis failed"], "error": str(e)}

        return {
            "plan": commands,
            "results": results,
            "health_report": analysis
        }
