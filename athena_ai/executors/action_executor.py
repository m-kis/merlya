import re
import subprocess
from typing import Any, Dict

from athena_ai.executors.ssh import SSHManager
from athena_ai.security.risk_assessor import RiskAssessor
from athena_ai.utils.logger import logger


class ActionExecutor:
    def __init__(self):
        self.ssh_manager = SSHManager()
        self.risk_assessor = RiskAssessor()

    @staticmethod
    def redact_sensitive_info(command: str) -> str:
        """
        Redact sensitive information (passwords, tokens, keys) from commands for logging.

        Patterns redacted:
        - -p 'password' or -p "password" or -p password
        - --password='password' or --password="password" or --password password
        - --pass, --passwd, --secret, --token, --api-key, etc.

        Args:
            command: Original command with potential sensitive data

        Returns:
            Command with sensitive values replaced by [REDACTED]
        """
        redacted = command

        # Pattern 1: -p 'value' or -p "value" (single letter flags with quotes)
        redacted = re.sub(r"(-p\s+['\"])([^'\"]+)(['\"])", r"\1[REDACTED]\3", redacted)

        # Pattern 2: -p value (single letter flags without quotes, stops at next flag or space)
        redacted = re.sub(r"(-p\s+)(\S+)", r"\1[REDACTED]", redacted)

        # Pattern 3: --password='value' or --password="value" (long flags with = and quotes)
        password_flags = ['password', 'passwd', 'pass', 'pwd', 'secret', 'token', 'api-key',
                         'apikey', 'auth', 'credential', 'key']
        for flag in password_flags:
            redacted = re.sub(rf"(--{flag}[=\s]+['\"])([^'\"]+)(['\"])", r"\1[REDACTED]\3", redacted, flags=re.IGNORECASE)
            redacted = re.sub(rf"(--{flag}[=\s]+)(\S+)", r"\1[REDACTED]", redacted, flags=re.IGNORECASE)

        return redacted

    def execute(self, target: str, command: str, action_type: str = "shell", confirm: bool = False, timeout: int = 60) -> Dict[str, Any]:
        """
        Execute an action on a target.
        Target can be 'local', 'localhost', a hostname, or an IP.

        Args:
            target: Target host ('local', 'localhost', hostname, or IP)
            command: Shell command to execute
            action_type: Type of action (default: 'shell')
            confirm: Skip risk confirmation if True
            timeout: Command timeout in seconds (default: 60)

        Returns:
            Dict with success, exit_code, stdout, stderr
        """
        risk = self.risk_assessor.assess(command)
        # Log command with sensitive info redacted
        redacted_command = self.redact_sensitive_info(command)
        logger.info(f"Executing {action_type} on {target}: {redacted_command} (Risk: {risk['level']})")

        if self.risk_assessor.requires_confirmation(risk['level']) and not confirm:
            return {
                "success": False,
                "error": f"Action requires confirmation (Risk: {risk['level']}). Run with --confirm.",
                "risk": risk
            }

        if target in ["local", "localhost"]:
            return self._execute_local(command, timeout=timeout)
        else:
            return self._execute_remote(target, command, timeout=timeout)

    def _execute_local(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "success": result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout}s")
            return {"success": False, "error": f"Command timed out after {timeout} seconds"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_remote(self, host: str, command: str, timeout: int = 60) -> Dict[str, Any]:
        exit_code, stdout, stderr = self.ssh_manager.execute(host, command, timeout=timeout)
        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "success": exit_code == 0
        }
