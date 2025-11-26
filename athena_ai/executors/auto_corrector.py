"""
Auto-correction system for failed commands.
Intelligent debugging loop that analyzes errors and fixes commands automatically.
KISS + DRY implementation.
"""
from typing import Any, Dict, Optional, Tuple

from athena_ai.utils.logger import logger


class AutoCorrector:
    """
    Intelligent command auto-correction for DevOps tasks.
    Analyzes errors and suggests fixes like an experienced SRE.
    """

    def __init__(self, llm_router, executor, context_manager):
        self.llm = llm_router
        self.executor = executor
        self.context = context_manager

    def execute_with_retry(self, target: str, command: str,
                          action_context: Dict[str, Any],
                          max_retries: int = 2) -> Tuple[Dict[str, Any], Optional[Dict]]:
        """
        Execute command with intelligent auto-correction on errors.

        Args:
            target: Target host or 'local'
            command: Command to execute
            action_context: Original action dict with context
            max_retries: Maximum retry attempts

        Returns:
            (result, retry_info) tuple
        """
        current_cmd = command
        corrections = []

        for attempt in range(1, max_retries + 2):  # +1 for initial attempt
            result = self.executor.execute(target, current_cmd, confirm=True)

            if result['success']:
                retry_info = {"attempts": attempt, "corrections": corrections} if attempt > 1 else None
                return result, retry_info

            # Failed - try to auto-correct
            if attempt > max_retries:
                return result, {"attempts": attempt, "corrections": corrections}

            logger.info(f"Auto-correcting failed command (attempt {attempt}/{max_retries})")

            # Get correction from AI
            corrected_cmd = self._get_correction(
                original=command,
                failed=current_cmd,
                error=result.get('stderr', result.get('error', 'Unknown')),
                target=target,
                context=action_context
            )

            if not corrected_cmd or corrected_cmd == current_cmd:
                logger.warning("No different fix available")
                return result, {"attempts": attempt, "corrections": corrections}

            # Log and retry
            corrections.append({
                "attempt": attempt,
                "failed": current_cmd,
                "error": result.get('stderr', '')[:200],
                "fix": corrected_cmd
            })

            # Redact sensitive info before logging
            from athena_ai.executors.action_executor import ActionExecutor
            redacted_cmd = ActionExecutor.redact_sensitive_info(corrected_cmd)
            logger.info(f"Retrying with: {redacted_cmd}")
            current_cmd = corrected_cmd

        return result, {"attempts": max_retries + 1, "corrections": corrections}

    def _get_correction(self, original: str, failed: str, error: str,
                       target: str, context: Dict[str, Any]) -> str:
        """
        Ask AI to fix the failed command.
        Fast, focused correction using haiku model.
        """
        # Get host context
        host_info = self._get_host_info(target)

        # Don't try to fix sudo password prompts - elevation should handle this
        if "password" in error.lower() and ("sudo" in error.lower() or "sudo" in failed):
            logger.info("Skipping auto-correction for sudo password prompt (elevation issue, not command issue)")
            return failed

        prompt = f"""FIX THIS COMMAND

Goal: {context.get('reason', 'Execute command')}
Failed: {failed}
Error: {error}
Host: {target} ({host_info.get('os', 'unknown')})

Common fixes:
- mongo → mongosh (MongoDB 6+)
- systemctl → service (non-systemd)
- apt-get → dnf/yum (on RHEL/Fedora)
- not found → check path/installation

CRITICAL RULES:
1. NEVER add sudo, su, doas, or any privilege elevation prefix
2. Privilege elevation is handled automatically by the system
3. If error is "permission denied", return the EXACT original command unchanged
4. Only fix actual command syntax errors (typos, wrong binary names, wrong flags)

Return ONLY the corrected command. No explanation. No sudo/su/doas.
If permission error or unfixable, return original command exactly.
"""

        try:
            response = self.llm.generate(
                prompt,
                "Expert DevOps engineer. Return only corrected command.",
                task="correction"  # Use fast model for corrections
            )
            return self._extract_command(response)
        except Exception as e:
            logger.error(f"Correction failed: {e}")
            return failed

    def _get_host_info(self, target: str) -> Dict[str, Any]:
        """Get cached host context."""
        if target in ["local", "localhost"]:
            return {}

        remote_hosts = self.context.cache.cache.get("remote_hosts", {}).get("data", {})
        return remote_hosts.get(target, {})

    def _extract_command(self, ai_response: str) -> str:
        """Extract clean command from AI response and filter out sudo/su suggestions."""
        lines = [l.strip() for l in ai_response.split('\n') if l.strip()]

        for line in lines:
            # Skip markdown, comments
            if line.startswith(('#', '//', '```')):
                continue
            if line:
                # Safety filter: reject commands starting with sudo/su/doas
                # Privilege elevation is handled by PermissionManager
                if line.strip().startswith(('sudo ', 'su ', 'doas ', 'su-')):
                    logger.warning(f"Auto-corrector tried to suggest sudo/su command, ignoring: {line[:50]}")
                    continue
                return line

        return ai_response.strip()
