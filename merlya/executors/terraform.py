import os
from typing import Any, Dict

from python_terraform import Terraform

from merlya.utils.logger import logger


class TerraformExecutor:
    def __init__(self):
        pass

    def plan(self, working_dir: str) -> Dict[str, Any]:
        """Run terraform plan."""
        logger.info(f"Running terraform plan in {working_dir}")

        if not os.path.exists(working_dir):
            return {"success": False, "error": f"Directory not found: {working_dir}"}

        try:
            tf = Terraform(working_dir=working_dir)
            return_code, stdout, stderr = tf.plan(capture_output=True)

            return {
                "success": return_code == 0 or return_code == 2, # 2 means changes present
                "stdout": stdout,
                "stderr": stderr,
                "rc": return_code
            }
        except Exception as e:
            logger.error(f"Terraform plan failed: {e}")
            return {"success": False, "error": str(e)}

    def apply(self, working_dir: str) -> Dict[str, Any]:
        """Run terraform apply."""
        logger.info(f"Running terraform apply in {working_dir}")

        if not os.path.exists(working_dir):
            return {"success": False, "error": f"Directory not found: {working_dir}"}

        try:
            tf = Terraform(working_dir=working_dir)
            return_code, stdout, stderr = tf.apply(skip_plan=True, capture_output=True)

            return {
                "success": return_code == 0,
                "stdout": stdout,
                "stderr": stderr,
                "rc": return_code
            }
        except Exception as e:
            logger.error(f"Terraform apply failed: {e}")
            return {"success": False, "error": str(e)}
