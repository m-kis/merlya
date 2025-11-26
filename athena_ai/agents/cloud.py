from typing import Dict, Any, List
from athena_ai.agents.base import BaseAgent
from athena_ai.executors.aws import AWSExecutor
from athena_ai.executors.k8s import K8sExecutor
from athena_ai.utils.logger import logger
import json

class CloudAgent(BaseAgent):
    def __init__(self, context_manager):
        super().__init__(context_manager)
        self.name = "CloudAgent"
        self.aws = AWSExecutor()
        self.k8s = K8sExecutor()

    def run(self, task: str, target: str = "local", confirm: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        logger.info(f"CloudAgent starting task: {task}")
        
        # 1. Plan Cloud Action
        plan_prompt = f"""
        Task: {task}
        
        Determine if this is an AWS or K8s task.
        
        If AWS:
        Return JSON: {{ "provider": "aws", "action": "list_instances|start|stop", "resource_id": "..." }}
        
        If K8s:
        Return JSON: {{ "provider": "k8s", "action": "list_pods|logs", "namespace": "default", "resource_name": "..." }}
        
        If neither, return {{ "error": "Unclear task" }}
        """
        system_prompt = "You are an expert cloud infrastructure agent. Return only raw JSON."
        
        try:
            plan_response = self.llm.generate(plan_prompt, system_prompt)
            plan_response = plan_response.replace("```json", "").replace("```", "").strip()
            plan = json.loads(plan_response)
        except Exception as e:
            logger.error(f"Failed to generate cloud plan: {e}")
            return {"error": "Planning failed"}

        if "error" in plan:
            return plan

        if dry_run:
            return {"plan": plan, "analysis": "Dry run mode.", "results": {}}

        # 2. Execute
        provider = plan.get("provider")
        action = plan.get("action")
        result = {}
        
        if provider == "aws":
            if action == "list_instances":
                result = self.aws.list_instances()
            elif action == "start":
                if confirm:
                    result = self.aws.start_instance(plan.get("resource_id"))
                else:
                    return {"error": "Start instance requires confirmation"}
            elif action == "stop":
                if confirm:
                    result = self.aws.stop_instance(plan.get("resource_id"))
                else:
                    return {"error": "Stop instance requires confirmation"}
                    
        elif provider == "k8s":
            namespace = plan.get("namespace", "default")
            if action == "list_pods":
                result = self.k8s.list_pods(namespace)
            elif action == "logs":
                result = self.k8s.get_pod_logs(plan.get("resource_name"), namespace)
        
        return {
            "plan": plan,
            "results": result
        }
