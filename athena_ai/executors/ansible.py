import os
from typing import Any, Dict

import ansible_runner

from athena_ai.utils.logger import logger


class AnsibleExecutor:
    def __init__(self):
        pass

    def run_playbook(self, playbook_path: str, inventory: Dict[str, Any] = None, extra_vars: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Run an Ansible playbook.
        """
        logger.info(f"Running playbook: {playbook_path}")

        if not os.path.exists(playbook_path):
            return {"success": False, "error": f"Playbook not found: {playbook_path}"}

        try:
            # Prepare runner args
            runner_config = {
                'private_data_dir': '/tmp/ansible_runner', # Temp dir for runner
                'playbook': playbook_path,
                'extravars': extra_vars or {},
                'quiet': True
            }

            if inventory:
                runner_config['inventory'] = inventory

            # Run
            r = ansible_runner.run(**runner_config)

            return {
                "success": r.rc == 0,
                "status": r.status,
                "stats": r.stats,
                "rc": r.rc
            }
        except Exception as e:
            logger.error(f"Ansible execution failed: {e}")
            return {"success": False, "error": str(e)}
