from typing import Dict, Any
from athena_ai.context.manager import ContextManager
from athena_ai.agents.diagnostic import DiagnosticAgent
from athena_ai.agents.remediation import RemediationAgent
from athena_ai.agents.monitoring import MonitoringAgent
from athena_ai.agents.provisioning import ProvisioningAgent
from athena_ai.agents.cloud import CloudAgent
from athena_ai.llm.router import LLMRouter
from athena_ai.utils.logger import logger
import json

class AgentCoordinator:
    def __init__(self, context_manager: ContextManager):
        self.context_manager = context_manager
        self.llm = LLMRouter()
        self.diagnostic_agent = DiagnosticAgent(context_manager)
        self.remediation_agent = RemediationAgent(context_manager)
        self.monitoring_agent = MonitoringAgent(context_manager)
        self.provisioning_agent = ProvisioningAgent(context_manager)
        self.cloud_agent = CloudAgent(context_manager)

    def coordinate(self, user_query: str, target: str = "local", confirm: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        """
        Coordinate multiple agents to fulfill a request.
        """
        logger.info(f"Coordinating request: {user_query}")
        
        # Get context to provide awareness of environment
        context = self.context_manager.get_context()
        inventory = context.get("inventory", {})
        local_info = context.get("local", {})
        
        # 1. Decompose Task
        plan_prompt = f"""
        User Query: {user_query}
        Target: {target}
        
        Environment Context:
        - Inventory (Hosts): {json.dumps(inventory, indent=2)}
        - Local System: {local_info.get('hostname')} ({local_info.get('os')})
        
        Decide which agents to call and in what order.
        Available Agents:
        - DiagnosticAgent: For troubleshooting and finding root causes.
        - RemediationAgent: For fixing issues (restarts, config edits).
        - MonitoringAgent: For checking health and metrics.
        - ProvisioningAgent: For Ansible playbooks and Terraform.
        - CloudAgent: For AWS and Kubernetes tasks.
        
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
            import re
            json_match = re.search(r'\{.*\}', plan_response, re.DOTALL)
            if json_match:
                plan_response = json_match.group(0)
            
            plan = json.loads(plan_response)
        except Exception as e:
            logger.error(f"Coordination planning failed: {e}. Response was: {plan_response if 'plan_response' in locals() else 'None'}")
            return {"error": "Coordination failed"}

        results = []
        for step in plan.get("steps", []):
            agent_name = step["agent"]
            task = step["task"]
            
            logger.info(f"Dispatching to {agent_name}: {task}")
            
            step_result = {}
            if agent_name == "DiagnosticAgent":
                step_result = self.diagnostic_agent.run(task, target, confirm, dry_run)
            elif agent_name == "RemediationAgent":
                step_result = self.remediation_agent.run(task, target, confirm, dry_run)
            elif agent_name == "MonitoringAgent":
                step_result = self.monitoring_agent.run(task, target, confirm, dry_run)
            elif agent_name == "ProvisioningAgent":
                step_result = self.provisioning_agent.run(task, target, confirm, dry_run)
            elif agent_name == "CloudAgent":
                step_result = self.cloud_agent.run(task, target, confirm, dry_run)
            
            results.append({
                "agent": agent_name,
                "task": task,
                "result": step_result
            })
            
            # Simple logic: if diagnostic found no issue, maybe skip remediation?
            # For MVP, we just execute the plan linearly.

        return {
            "coordination_plan": plan,
            "step_results": results
        }
