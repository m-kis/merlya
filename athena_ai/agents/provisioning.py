from typing import Dict, Any, List
from athena_ai.agents.base import BaseAgent
from athena_ai.executors.ansible import AnsibleExecutor
from athena_ai.executors.terraform import TerraformExecutor
from athena_ai.utils.logger import logger
import json
import os

class ProvisioningAgent(BaseAgent):
    def __init__(self, context_manager):
        super().__init__(context_manager)
        self.name = "ProvisioningAgent"
        self.ansible = AnsibleExecutor()
        self.terraform = TerraformExecutor()

    def run(self, task: str, target: str = "local", confirm: bool = False, dry_run: bool = False) -> Dict[str, Any]:
        logger.info(f"ProvisioningAgent starting task: {task}")
        
        # 1. Plan Provisioning
        plan_prompt = f"""
        Task: {task}
        Target: {target}
        
        Determine if this is an Ansible or Terraform task.
        
        If Ansible:
        Return JSON: {{ "tool": "ansible", "playbook": "/path/to/playbook.yml" }}
        
        If Terraform:
        Return JSON: {{ "tool": "terraform", "dir": "/path/to/tf/dir", "action": "plan|apply" }}
        
        If neither or unclear, return {{ "error": "Unclear task" }}
        """
        system_prompt = "You are an expert infrastructure provisioning agent. Return only raw JSON."
        
        try:
            plan_response = self.llm.generate(plan_prompt, system_prompt)
            plan_response = plan_response.replace("```json", "").replace("```", "").strip()
            plan = json.loads(plan_response)
        except Exception as e:
            logger.error(f"Failed to generate provisioning plan: {e}")
            return {"error": "Planning failed"}

        if "error" in plan:
            return plan

        if dry_run:
            return {"plan": plan, "analysis": "Dry run mode.", "results": {}}

        # 2. Execute
        tool = plan.get("tool")
        result = {}
        
        if tool == "ansible":
            playbook = plan.get("playbook")
            # For MVP, we assume inventory is handled or passed. 
            # In real world, we'd generate it from context.
            if confirm: # Only run if confirmed for now, as playbooks are powerful
                result = self.ansible.run_playbook(playbook)
            else:
                return {"error": "Ansible execution requires confirmation"}
                
        elif tool == "terraform":
            directory = plan.get("dir")
            action = plan.get("action")
            
            if action == "plan":
                result = self.terraform.plan(directory)
            elif action == "apply":
                if confirm:
                    result = self.terraform.apply(directory)
                else:
                    return {"error": "Terraform apply requires confirmation"}
        
        return {
            "plan": plan,
            "results": result
        }
