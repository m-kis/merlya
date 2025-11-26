"""
Error Correction Service - DDD Domain Service.

Analyzes command failures and generates intelligent corrections.
Uses ErrorAnalyzer for semantic error classification.
"""
import json
from typing import Any, Dict, Optional

from athena_ai.triage import ErrorType, get_error_analyzer
from athena_ai.utils.logger import logger


class ErrorCorrectionService:
    """
    Domain Service for analyzing command errors and suggesting corrections.

    Uses ErrorAnalyzer for semantic error classification, then:
    - Quick fixes for known patterns (permission, command not found, etc.)
    - LLM-powered analysis for complex errors
    """

    def __init__(self, llm_router):
        """
        Initialize Error Correction Service.

        Args:
            llm_router: LLMRouter instance for intelligent error analysis
        """
        self.llm_router = llm_router
        self._error_analyzer = None  # Lazy init

    @property
    def error_analyzer(self):
        """Lazy load the error analyzer."""
        if self._error_analyzer is None:
            self._error_analyzer = get_error_analyzer()
        return self._error_analyzer

    def classify_error(self, error: str) -> tuple:
        """
        Classify an error using semantic analysis.

        Args:
            error: Error message

        Returns:
            (ErrorType, confidence, analysis) tuple
        """
        analysis = self.error_analyzer.analyze(error)
        return analysis.error_type, analysis.confidence, analysis

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
        Try quick heuristic fixes based on error classification.

        Uses ErrorAnalyzer for semantic classification instead of hardcoded patterns.

        Args:
            command: Original command
            error: Error message
            exit_code: Exit code
            context: Additional context

        Returns:
            Corrected command, or None
        """
        # Use ErrorAnalyzer for classification
        error_type, confidence, _ = self.classify_error(error)

        # Only act on confident classifications
        if confidence < 0.6:
            return None

        # Permission error → add sudo
        if error_type == ErrorType.PERMISSION:
            if not command.strip().startswith("sudo "):
                logger.debug("Quick fix: Adding sudo for permission error")
                return f"sudo {command}"

        # Command not found → try alternatives
        if error_type == ErrorType.NOT_FOUND and exit_code == 127:
            alternatives = {
                "service": "systemctl",
                "ifconfig": "ip addr",
                "netstat": "ss",
                "iptables-save": "nft list ruleset",
                "mongo": "mongosh",
            }
            for old_cmd, new_cmd in alternatives.items():
                if old_cmd in command:
                    logger.debug(f"Quick fix: Replacing {old_cmd} with {new_cmd}")
                    return command.replace(old_cmd, new_cmd)

        # File not found → try path alternatives
        if error_type == ErrorType.NOT_FOUND:
            path_alternatives = {
                "/var/log/syslog": "/var/log/messages",
                "/var/log/auth.log": "/var/log/secure",
            }
            for old_path, new_path in path_alternatives.items():
                if old_path in command:
                    logger.debug(f"Quick fix: Trying {new_path} instead of {old_path}")
                    return command.replace(old_path, new_path)

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
        Determine if an error is worth retrying based on error classification.

        Uses ErrorAnalyzer instead of hardcoded patterns.

        Args:
            error: Error message
            exit_code: Exit code

        Returns:
            True if retry makes sense
        """
        error_type, confidence, _ = self.classify_error(error)

        # Low confidence → don't retry (unknown error)
        if confidence < 0.6:
            return exit_code in [1, 126, 127]

        # Don't retry network/connectivity errors (no command fix can help)
        if error_type in (ErrorType.CONNECTION, ErrorType.TIMEOUT):
            return False

        # Don't retry credential errors (need user input)
        if error_type == ErrorType.CREDENTIAL:
            return False

        # Don't retry resource errors (need system intervention)
        if error_type == ErrorType.RESOURCE:
            return False

        # Retry permission, not found, configuration errors
        return error_type in (
            ErrorType.PERMISSION,
            ErrorType.NOT_FOUND,
            ErrorType.CONFIGURATION,
        )

    def generate_natural_language_error(
        self,
        command: str,
        error: str,
        exit_code: int,
        target: str
    ) -> str:
        """
        Generate a user-friendly error message based on error classification.

        Uses ErrorAnalyzer for classification instead of hardcoded patterns.

        Args:
            command: The command that failed
            error: Error message
            exit_code: Exit code
            target: Target host

        Returns:
            Natural language error message with suggestions
        """
        error_type, confidence, analysis = self.classify_error(error)
        # Safely extract command name, handling empty or whitespace-only strings
        cmd_name = command.split()[0] if command and command.strip() else "unknown"

        # Error messages by type
        messages = {
            ErrorType.PERMISSION: f"""
❌ **Permission refusée**

La commande nécessite des privilèges élevés pour s'exécuter.

**Commande**: `{command}`
**Serveur**: {target}

**💡 Suggestions**:
• Le système a automatiquement tenté d'utiliser sudo
• Vérifiez que l'utilisateur dispose des droits sudo
• Certaines commandes nécessitent l'accès root direct
• Consultez les logs d'audit si nécessaire
""",
            ErrorType.CREDENTIAL: f"""
❌ **Authentification requise**

L'accès nécessite des identifiants valides.

**Serveur**: {target}
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Vérifiez vos identifiants (utilisateur/mot de passe)
• Le token ou la clé API peut être expiré
• Utilisez /variables pour définir les credentials
""",
            ErrorType.NOT_FOUND: f"""
❌ **Ressource introuvable**

La commande `{cmd_name}` ou le fichier spécifié n'existe pas.

**Serveur**: {target}
**Erreur**: {error[:100]}

**💡 Suggestions**:
• Le package peut ne pas être installé
• Vérifiez le chemin d'accès (sensible à la casse)
• Sur certains systèmes, les chemins varient (ex: /var/log/syslog vs /var/log/messages)
• Le système tentera des alternatives automatiquement
""",
            ErrorType.CONNECTION: f"""
❌ **Erreur de connexion**

Impossible de se connecter au serveur.

**Serveur**: {target}
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Le serveur est peut-être hors ligne ou en maintenance
• Vérifiez la connectivité réseau
• Le pare-feu peut bloquer la connexion
• Vérifiez la résolution DNS du nom d'hôte
""",
            ErrorType.TIMEOUT: f"""
❌ **Délai d'attente dépassé**

L'opération a pris trop de temps.

**Serveur**: {target}
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Le serveur peut être surchargé
• Vérifiez la latence réseau
• Augmentez le timeout si nécessaire
""",
            ErrorType.RESOURCE: f"""
❌ **Ressources insuffisantes**

Le système manque de ressources (disque, mémoire, etc.)

**Serveur**: {target}
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Vérifiez l'espace disque disponible
• Vérifiez l'utilisation mémoire
• Libérez des ressources si nécessaire
""",
            ErrorType.CONFIGURATION: f"""
❌ **Erreur de configuration**

La commande contient une erreur de syntaxe ou de configuration.

**Commande**: `{command}`
**Erreur**: {error[:150]}

**💡 Suggestions**:
• Vérifiez la syntaxe de la commande
• Consultez la documentation ou `man {cmd_name}`
""",
        }

        # Return specific message or generic one
        if error_type in messages and confidence >= 0.6:
            return messages[error_type]

        # Generic fallback
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
