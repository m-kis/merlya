"""
Error Correction Service - DDD Domain Service.

Analyzes command failures and generates intelligent corrections.
"""
import json
from typing import Dict, Any, Optional, List
from athena_ai.utils.logger import logger


class ErrorCorrectionService:
    """
    Domain Service for analyzing command errors and suggesting corrections.

    Uses LLM-powered analysis to intelligently fix common error patterns:
    - Permission denied → add sudo/su
    - Command not found → suggest alternatives
    - File not found → check paths
    - Connection timeout → retry with backoff
    """

    def __init__(self, llm_router):
        """
        Initialize Error Correction Service.

        Args:
            llm_router: LLMRouter instance for intelligent error analysis
        """
        self.llm_router = llm_router

    def analyze_and_correct(
        self,
        original_command: str,
        error_message: str,
        exit_code: int,
        target: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Analyze a command failure and suggest a correction.

        Args:
            original_command: The command that failed
            error_message: Error message from stderr
            exit_code: Command exit code
            target: Target host
            context: Additional context (permissions, OS info, etc.)

        Returns:
            Corrected command string, or None if no correction possible
        """
        logger.info(f"Analyzing command failure: {original_command}")

        # Quick heuristic fixes (fast, no LLM needed)
        quick_fix = self._try_quick_fix(original_command, error_message, exit_code, context)
        if quick_fix:
            logger.info(f"Applied quick fix: {quick_fix}")
            return quick_fix

        # LLM-powered intelligent correction for complex errors
        llm_fix = self._try_llm_correction(
            original_command,
            error_message,
            exit_code,
            target,
            context
        )
        if llm_fix:
            logger.info(f"Applied LLM correction: {llm_fix}")
            return llm_fix

        logger.info("No correction found for this error")
        return None

    def _try_quick_fix(
        self,
        command: str,
        error: str,
        exit_code: int,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Try quick heuristic fixes for common error patterns.

        Args:
            command: Original command
            error: Error message
            exit_code: Exit code
            context: Additional context

        Returns:
            Corrected command, or None
        """
        error_lower = error.lower()

        # Pattern 1: Permission denied (exit code 126 or error contains "permission denied")
        if exit_code == 126 or "permission denied" in error_lower:
            # Don't add sudo if already present
            if not command.strip().startswith("sudo "):
                logger.debug("Quick fix: Adding sudo for permission error")
                return f"sudo {command}"

        # Pattern 2: Command not found (exit code 127)
        if exit_code == 127 or "command not found" in error_lower:
            # Common alternatives
            alternatives = {
                "service": "systemctl",
                "ifconfig": "ip addr",
                "netstat": "ss",
                "iptables-save": "nft list ruleset",
            }

            for old_cmd, new_cmd in alternatives.items():
                if old_cmd in command:
                    logger.debug(f"Quick fix: Replacing {old_cmd} with {new_cmd}")
                    return command.replace(old_cmd, new_cmd)

        # Pattern 3: No such file or directory - check common typos
        if "no such file or directory" in error_lower:
            # Try common path corrections
            if "/var/log/syslog" in command and context:
                # Maybe it's a Red Hat system (uses /var/log/messages)
                logger.debug("Quick fix: Trying /var/log/messages instead of /var/log/syslog")
                return command.replace("/var/log/syslog", "/var/log/messages")

        return None

    def _try_llm_correction(
        self,
        command: str,
        error: str,
        exit_code: int,
        target: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Use LLM to analyze error and suggest correction.

        Args:
            command: Original command
            error: Error message
            exit_code: Exit code
            target: Target host
            context: Additional context

        Returns:
            Corrected command, or None
        """
        try:
            # Build context info
            context_info = ""
            if context:
                if "os_info" in context:
                    context_info += f"\nOS: {context['os_info']}"
                if "permissions_info" in context:
                    perms = context['permissions_info']
                    context_info += f"\nPermissions: is_root={perms.get('is_root')}, elevation={perms.get('elevation_method')}"

            # Build prompt for LLM
            prompt = f"""A shell command failed on host "{target}". Analyze the error and suggest a correction.

ORIGINAL COMMAND: {command}
EXIT CODE: {exit_code}
ERROR MESSAGE: {error}
{context_info}

TASK: Suggest EXACTLY ONE corrected command that would fix this error.

Common fixes:
- Permission denied → Add sudo/su if not root
- Command not found → Suggest alternative command (e.g., systemctl instead of service)
- File not found → Check if path exists, suggest alternative paths
- Network timeout → No command fix possible (return null)
- Syntax error → Fix the syntax

RESPOND WITH VALID JSON ONLY:
{{
  "corrected_command": "the fixed command" OR null if no fix possible,
  "reason": "brief explanation why this fix should work"
}}

Examples:
- Original: "service nginx status" (exit 127) → {{"corrected_command": "systemctl status nginx", "reason": "systemctl is the modern alternative to service"}}
- Original: "cat /var/log/auth.log" (exit 1, permission denied) → {{"corrected_command": "sudo cat /var/log/auth.log", "reason": "auth.log requires root privileges"}}
- Original: "ping -c 1 8.8.8.8" (timeout error) → {{"corrected_command": null, "reason": "Network timeout cannot be fixed by changing command"}}
"""

            # Call LLM
            response = self.llm_router.generate(
                prompt=prompt,
                system_prompt="You are an expert DevOps engineer specializing in debugging shell commands. Always respond with valid JSON.",
                task="correction"
            )

            # Parse response
            correction = self._parse_correction_response(response)
            return correction

        except Exception as e:
            logger.error(f"LLM correction failed: {e}")
            return None

    def _parse_correction_response(self, response: str) -> Optional[str]:
        """
        Parse LLM correction response.

        Args:
            response: JSON response from LLM

        Returns:
            Corrected command, or None
        """
        try:
            # Extract JSON from markdown if present
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()
            else:
                json_str = response.strip()

            data = json.loads(json_str)
            corrected = data.get("corrected_command")
            reason = data.get("reason", "")

            if corrected:
                logger.info(f"LLM correction reason: {reason}")
                return corrected
            else:
                logger.info(f"LLM determined no correction possible: {reason}")
                return None

        except Exception as e:
            logger.error(f"Failed to parse correction response: {e}")
            logger.debug(f"Response was: {response[:200]}")
            return None

    def should_retry(self, error: str, exit_code: int) -> bool:
        """
        Determine if an error is worth retrying.

        Args:
            error: Error message
            exit_code: Exit code

        Returns:
            True if retry makes sense
        """
        # Don't retry network/connectivity errors (no command fix can help)
        no_retry_patterns = [
            "connection timeout",
            "connection refused",
            "no route to host",
            "network unreachable",
            "host unreachable",
        ]

        error_lower = error.lower()
        for pattern in no_retry_patterns:
            if pattern in error_lower:
                return False

        # Retry permission errors, command not found, file not found
        return exit_code in [1, 126, 127] or any(
            pattern in error_lower
            for pattern in ["permission denied", "command not found", "no such file"]
        )

    def generate_natural_language_error(
        self,
        command: str,
        error: str,
        exit_code: int,
        target: str
    ) -> str:
        """
        Generate a user-friendly error message with troubleshooting suggestions.

        Args:
            command: The command that failed
            error: Error message
            exit_code: Exit code
            target: Target host

        Returns:
            Natural language error message with suggestions
        """
        error_lower = error.lower()

        # Pattern 1: Permission denied
        if exit_code == 126 or "permission denied" in error_lower:
            return f"""
❌ **Permission refusée**

La commande nécessite des privilèges élevés pour s'exécuter.

**Commande**: `{command}`
**Serveur**: {target}

**💡 Suggestions**:
• Le système a automatiquement tenté d'utiliser sudo
• Vérifiez que l'utilisateur dispose des droits sudo
• Certaines commandes nécessitent l'accès root direct
• Consultez les logs d'audit si nécessaire
"""

        # Pattern 2: Command not found
        if exit_code == 127 or "command not found" in error_lower:
            # Extract command name
            cmd_name = command.split()[0] if command else "unknown"
            return f"""
❌ **Commande introuvable**

La commande `{cmd_name}` n'est pas disponible sur ce serveur.

**Serveur**: {target}
**Erreur**: {error[:100]}

**💡 Suggestions**:
• Le package contenant cette commande n'est peut-être pas installé
• Essayez une alternative (ex: `systemctl` au lieu de `service`)
• Vérifiez le PATH si la commande existe dans un répertoire non standard
• Le système tentera automatiquement des commandes alternatives
"""

        # Pattern 3: File not found
        if "no such file or directory" in error_lower:
            return f"""
❌ **Fichier ou répertoire introuvable**

Le fichier ou répertoire spécifié n'existe pas sur le serveur.

**Serveur**: {target}
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Vérifiez le chemin d'accès (sensible à la casse)
• Le fichier peut avoir été déplacé ou supprimé
• Sur certains systèmes, les chemins peuvent varier (ex: /var/log/syslog vs /var/log/messages)
• Utilisez `find` pour localiser le fichier
"""

        # Pattern 4: Connection errors
        if any(p in error_lower for p in ["connection timeout", "connection refused", "unreachable"]):
            return f"""
❌ **Erreur de connexion**

Impossible de se connecter au serveur.

**Serveur**: {target}
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Le serveur est peut-être hors ligne ou en maintenance
• Vérifiez la connectivité réseau
• Le pare-feu peut bloquer la connexion SSH
• Vérifiez la résolution DNS du nom d'hôte
"""

        # Pattern 5: Generic error with troubleshooting
        return f"""
❌ **Erreur d'exécution**

Une erreur s'est produite lors de l'exécution de la commande.

**Commande**: `{command}`
**Serveur**: {target}
**Code de sortie**: {exit_code}
**Erreur**: {error[:200]}

**💡 Prochaines étapes**:
• Le système a tenté automatiquement de corriger l'erreur
• Vérifiez les logs du serveur pour plus de détails
• Contactez l'équipe système si le problème persiste
"""

    def explain_error_to_user(
        self,
        command: str,
        error: str,
        exit_code: int,
        target: str,
        attempted_correction: Optional[str] = None
    ) -> str:
        """
        Generate complete user-facing error explanation.

        Args:
            command: Failed command
            error: Error message
            exit_code: Exit code
            target: Target host
            attempted_correction: Correction that was attempted (if any)

        Returns:
            Complete formatted error explanation
        """
        # Get natural language error
        nl_error = self.generate_natural_language_error(command, error, exit_code, target)

        # Add correction info if attempted
        if attempted_correction:
            nl_error += f"""

🔄 **Tentative de correction automatique**

Le système a tenté la commande corrigée suivante:
```bash
{attempted_correction}
```
"""

        return nl_error
