import re
import subprocess
from typing import Any, Dict, Optional

from athena_ai.executors.ssh import SSHManager
from athena_ai.security.credentials import CredentialManager
from athena_ai.security.risk_assessor import RiskAssessor
from athena_ai.triage import ErrorAnalysis, get_error_analyzer
from athena_ai.utils.logger import logger


class ActionExecutor:
    def __init__(self, credential_manager: Optional[CredentialManager] = None):
        self.ssh_manager = SSHManager()
        self.risk_assessor = RiskAssessor()
        self.credentials = credential_manager or CredentialManager()
        self._error_analyzer = None  # Lazy init to avoid loading model at startup

    @property
    def error_analyzer(self):
        """Lazy load the error analyzer."""
        if self._error_analyzer is None:
            self._error_analyzer = get_error_analyzer()
        return self._error_analyzer

    def analyze_error(self, error_text: str) -> Optional[ErrorAnalysis]:
        """
        Analyze an error message to determine its type and suggested action.

        Args:
            error_text: The error message to analyze

        Returns:
            ErrorAnalysis with type, confidence, and suggested action
        """
        if not error_text:
            return None
        return self.error_analyzer.analyze(error_text)

    def needs_credentials(self, result: Dict[str, Any]) -> bool:
        """
        Check if a result indicates credentials are needed.

        Args:
            result: Execution result dict

        Returns:
            True if credentials are needed
        """
        error_analysis = result.get("error_analysis")
        if error_analysis:
            return error_analysis.get("needs_credentials", False)
        return False

    def prompt_credentials(
        self,
        service: str,
        host: str,
        prompt_message: Optional[str] = None,
    ) -> Optional[tuple]:
        """
        Prompt user for credentials.

        Args:
            service: Service name (e.g., "mysql", "mongodb", "ssh")
            host: Target host
            prompt_message: Optional custom prompt message

        Returns:
            (username, password) tuple or None if cancelled
        """
        try:
            return self.credentials.get_db_credentials(host, service)
        except (KeyboardInterrupt, EOFError):
            logger.info("Credential prompt cancelled")
            return None

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
            proc_result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            result = {
                "exit_code": proc_result.returncode,
                "stdout": proc_result.stdout.strip(),
                "stderr": proc_result.stderr.strip(),
                "success": proc_result.returncode == 0,
            }

            # Analyze errors on failure
            if proc_result.returncode != 0 and proc_result.stderr:
                analysis = self.analyze_error(proc_result.stderr)
                if analysis and analysis.confidence >= 0.6:
                    result["error_analysis"] = {
                        "type": analysis.error_type.value,
                        "confidence": analysis.confidence,
                        "needs_credentials": analysis.needs_credentials,
                        "suggested_action": analysis.suggested_action,
                        "matched_pattern": analysis.matched_pattern,
                    }

            return result
        except subprocess.TimeoutExpired:
            logger.error(f"Command timed out after {timeout}s")
            return {"success": False, "error": f"Command timed out after {timeout} seconds"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_remote(self, host: str, command: str, timeout: int = 60) -> Dict[str, Any]:
        exit_code, stdout, stderr = self.ssh_manager.execute(host, command, timeout=timeout)

        result = {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "success": exit_code == 0,
        }

        # Analyze errors on failure
        if exit_code != 0 and stderr:
            analysis = self.analyze_error(stderr)
            if analysis and analysis.confidence >= 0.6:
                result["error_analysis"] = {
                    "type": analysis.error_type.value,
                    "confidence": analysis.confidence,
                    "needs_credentials": analysis.needs_credentials,
                    "suggested_action": analysis.suggested_action,
                    "matched_pattern": analysis.matched_pattern,
                }
                logger.debug(
                    f"Error classified as {analysis.error_type.value} "
                    f"(confidence: {analysis.confidence:.2f})"
                )

        return result
