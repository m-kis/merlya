"""
Tool Selector Service - AI-powered tool selection.

Uses sentence-transformers for semantic similarity to intelligently
select the most appropriate tool based on context (error type, intent, etc.).

Falls back to heuristic rules when embeddings are unavailable.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from merlya.triage import ErrorType, Intent
from merlya.utils.logger import logger

# Reuse EmbeddingCache from smart_classifier (DRY principle)
try:
    from merlya.triage.smart_classifier import HAS_EMBEDDINGS, EmbeddingCache
except ImportError:
    HAS_EMBEDDINGS = False
    EmbeddingCache = None  # type: ignore

if HAS_EMBEDDINGS:
    import numpy as np


class ToolAction(Enum):
    """Actions that can be recommended by the selector."""
    REQUEST_ELEVATION = "request_elevation"
    REQUEST_CREDENTIALS = "request_credentials"
    ASK_USER = "ask_user"
    RETRY_WITH_SUDO = "retry_with_sudo"
    RETRY_ALTERNATE_PATH = "retry_alternate_path"
    RETRY_ALTERNATE_COMMAND = "retry_alternate_command"
    PROVIDE_CREDENTIALS = "provide_credentials"  # Deprecated, use REQUEST_CREDENTIALS
    NO_ACTION = "no_action"


@dataclass
class ToolRecommendation:
    """Result of tool selection."""
    action: ToolAction
    confidence: float
    tool_name: Optional[str]
    tool_params: Dict[str, Any]
    reason: str


class ToolSelector:
    """
    AI-powered tool selector using semantic similarity.

    Determines the best tool/action based on:
    - Error type (permission, credential, not_found, etc.)
    - Triage intent (query, action, analysis)
    - System context (permissions, OS, etc.)

    Uses local embeddings (sentence-transformers) for fast, offline inference.
    Falls back to heuristic rules when embeddings unavailable.
    """

    def __init__(self, use_embeddings: bool = True):
        """
        Initialize the tool selector.

        Args:
            use_embeddings: Whether to use embeddings (requires sentence-transformers)
        """
        self._use_embeddings = use_embeddings and HAS_EMBEDDINGS
        self._embedding_cache: Optional["EmbeddingCache"] = None

        if self._use_embeddings and HAS_EMBEDDINGS:
            self._embedding_cache = EmbeddingCache()
            logger.debug("✅ ToolSelector initialized with embeddings")
        else:
            logger.debug("⚠️ ToolSelector using heuristic fallback (no embeddings)")

        # Reference patterns for semantic matching
        self._action_patterns = self._build_action_patterns()
        self._action_embeddings_cache: Dict[ToolAction, Tuple[List[str], Any]] = {}

    def _build_action_patterns(self) -> Dict[ToolAction, List[str]]:
        """Build reference patterns for each action type."""
        return {
            ToolAction.REQUEST_ELEVATION: [
                "permission denied",
                "operation not permitted",
                "access denied",
                "insufficient privileges",
                "must be root",
                "requires elevated privileges",
                "sudo required",
                "EACCES",
                "EPERM",
                "cannot write to",
                "read-only file system",
            ],
            ToolAction.PROVIDE_CREDENTIALS: [
                "authentication failed",
                "invalid password",
                "login failed",
                "unauthorized",
                "access denied for user",
                "password authentication failed",
                "invalid credentials",
                "token expired",
                "invalid api key",
            ],
            ToolAction.RETRY_ALTERNATE_PATH: [
                "no such file or directory",
                "file not found",
                "ENOENT",
                "/var/log/syslog not found",
                "/var/log/messages not found",
                "path does not exist",
            ],
            ToolAction.RETRY_ALTERNATE_COMMAND: [
                "command not found",
                "service command not found",
                "unknown command",
                "executable not found",
                "program not found",
            ],
            ToolAction.ASK_USER: [
                "which host",
                "please specify",
                "need more information",
                "unclear request",
                "ambiguous",
                "multiple options",
                "choose one",
            ],
        }

    def _get_action_embeddings(self, action: ToolAction) -> Tuple[List[str], Optional[Any]]:
        """Get cached embeddings for an action type."""
        if not self._use_embeddings or not self._embedding_cache:
            return [], None

        if action in self._action_embeddings_cache:
            return self._action_embeddings_cache[action]

        patterns = self._action_patterns.get(action, [])
        if not patterns:
            return [], None

        embeddings = self._embedding_cache.get_embeddings_batch(patterns)
        result = (patterns, np.array(embeddings))
        self._action_embeddings_cache[action] = result
        return result

    def _semantic_action_scores(self, context_text: str) -> Dict[ToolAction, float]:
        """
        Calculate semantic similarity scores for each action.

        Returns dict of action -> similarity score (0-1).
        """
        if not self._use_embeddings or not self._embedding_cache:
            return {}

        try:
            context_embedding = self._embedding_cache.get_embedding(context_text)
            scores: Dict[ToolAction, float] = {}

            for action in ToolAction:
                if action == ToolAction.NO_ACTION:
                    continue

                patterns, ref_embeddings = self._get_action_embeddings(action)
                if ref_embeddings is None or len(ref_embeddings) == 0:
                    continue

                # Cosine similarity with zero-norm protection
                context_norm = np.linalg.norm(context_embedding)
                if context_norm == 0:
                    continue

                ref_norms = np.linalg.norm(ref_embeddings, axis=1)
                valid_mask = ref_norms > 0
                if not np.any(valid_mask):
                    continue

                similarities = np.dot(ref_embeddings[valid_mask], context_embedding) / (
                    ref_norms[valid_mask] * context_norm
                )
                scores[action] = float(np.max(similarities))

            return scores

        except Exception as e:
            logger.warning(f"⚠️ Semantic scoring failed: {e}")
            return {}

    def _detect_service_from_context(
        self, context: Dict[str, Any], error_lower: str
    ) -> str:
        """
        Detect service type from context and error message.

        Returns service name like 'mongodb', 'mysql', 'postgresql', 'ssh', etc.
        """
        command = context.get("command", "").lower()

        # Check command patterns
        if "mongo" in command or "mongosh" in command or "mongod" in command:
            return "mongodb"
        if "mysql" in command:
            return "mysql"
        if "psql" in command or "postgres" in command:
            return "postgresql"
        if "redis" in command or "redis-cli" in command:
            return "redis"
        if "ssh" in command:
            return "ssh"

        # Check error message patterns
        if "mongo" in error_lower:
            return "mongodb"
        if "mysql" in error_lower or "mariadb" in error_lower:
            return "mysql"
        if "postgres" in error_lower or "psql" in error_lower:
            return "postgresql"
        if "redis" in error_lower:
            return "redis"
        if "ssh" in error_lower or "publickey" in error_lower:
            return "ssh"

        # Check context for service hint
        if context.get("service"):
            return context["service"]

        # Default to generic "database" or "ssh"
        if any(kw in error_lower for kw in ["database", "db", "connection refused"]):
            return "database"

        return "ssh"  # Default fallback

    def _heuristic_select(
        self,
        error_type: Optional[ErrorType],
        error_message: str,
        intent: Optional[Intent],
        context: Dict[str, Any],
    ) -> ToolRecommendation:
        """
        Heuristic-based tool selection (fallback).

        Uses deterministic rules when embeddings unavailable.
        """
        error_lower = error_message.lower() if error_message else ""

        # Permission errors → request_elevation
        if error_type == ErrorType.PERMISSION:
            can_elevate = context.get("elevation_method") not in (None, "none")
            if can_elevate:
                return ToolRecommendation(
                    action=ToolAction.REQUEST_ELEVATION,
                    confidence=0.85,
                    tool_name="request_elevation",
                    tool_params={
                        "target": context.get("target", ""),
                        "command": context.get("command", ""),
                        "error_message": error_message[:200],
                        "reason": "Permission denied - elevation required",
                    },
                    reason="Error type PERMISSION detected with elevation capability",
                )
            return ToolRecommendation(
                action=ToolAction.RETRY_WITH_SUDO,
                confidence=0.75,
                tool_name=None,
                tool_params={"prefix": "sudo"},
                reason="Permission denied - no interactive elevation available",
            )

        # Credential errors → request_credentials
        if error_type == ErrorType.CREDENTIAL:
            # Detect service type from context or error message
            service = self._detect_service_from_context(context, error_lower)
            return ToolRecommendation(
                action=ToolAction.REQUEST_CREDENTIALS,
                confidence=0.85,
                tool_name="request_credentials",
                tool_params={
                    "target": context.get("target", ""),
                    "service": service,
                    "error_message": error_message[:200],
                    "reason": "Authentication failed - credentials required",
                },
                reason="Credential error detected - use request_credentials tool",
            )

        # File not found → try alternate paths
        if error_type == ErrorType.NOT_FOUND:
            # Check for common path alternatives
            alternates = {
                "/var/log/syslog": "/var/log/messages",
                "/var/log/auth.log": "/var/log/secure",
            }
            for old_path, new_path in alternates.items():
                if old_path in error_lower:
                    return ToolRecommendation(
                        action=ToolAction.RETRY_ALTERNATE_PATH,
                        confidence=0.80,
                        tool_name=None,
                        tool_params={"old_path": old_path, "new_path": new_path},
                        reason=f"File {old_path} not found, trying {new_path}",
                    )

            # Command not found
            if "command not found" in error_lower or context.get("exit_code") == 127:
                return ToolRecommendation(
                    action=ToolAction.RETRY_ALTERNATE_COMMAND,
                    confidence=0.75,
                    tool_name=None,
                    tool_params={},
                    reason="Command not found - suggesting alternatives",
                )

        # Missing information → ask_user
        if intent == Intent.QUERY and not context.get("target"):
            return ToolRecommendation(
                action=ToolAction.ASK_USER,
                confidence=0.70,
                tool_name="ask_user",
                tool_params={"question": "Which host would you like to query?"},
                reason="Missing target information for query",
            )

        # No specific action needed
        return ToolRecommendation(
            action=ToolAction.NO_ACTION,
            confidence=0.50,
            tool_name=None,
            tool_params={},
            reason="No specific action recommended",
        )

    def select(
        self,
        error_type: Optional[ErrorType] = None,
        error_message: str = "",
        intent: Optional[Intent] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolRecommendation:
        """
        Select the best tool/action based on context.

        Uses a multi-layer approach:
        1. Semantic similarity (if embeddings available)
        2. Heuristic rules (fallback)
        3. Combine scores for final decision

        Args:
            error_type: Classified error type (from ErrorAnalyzer)
            error_message: Raw error message
            intent: Triage intent (query, action, analysis)
            context: Additional context (permissions, target, command, etc.)

        Returns:
            ToolRecommendation with action, confidence, and parameters
        """
        context = context or {}

        # Build context string for semantic matching
        context_parts = []
        if error_message:
            context_parts.append(error_message)
        if error_type:
            context_parts.append(f"error type: {error_type.value}")
        if intent:
            context_parts.append(f"intent: {intent.value}")

        context_text = " ".join(context_parts)

        # Try semantic matching first
        if self._use_embeddings and context_text:
            semantic_scores = self._semantic_action_scores(context_text)

            if semantic_scores:
                # Find best match
                best_action = max(semantic_scores, key=lambda k: semantic_scores[k])
                best_score = semantic_scores[best_action]

                # Threshold for semantic match (0.65 = reasonable match)
                if best_score >= 0.65:
                    return self._build_recommendation(
                        best_action,
                        best_score,
                        context,
                        error_message,
                        f"Semantic match: {best_score:.2f}",
                    )

        # Fallback to heuristics
        return self._heuristic_select(error_type, error_message, intent, context)

    def _enrich_alternate_path_params(
        self, context: Dict[str, Any], error_message: str
    ) -> Dict[str, Any]:
        """
        Enrich params for RETRY_ALTERNATE_PATH from available context keys.

        Checks for:
        - old_path/new_path: direct path pair
        - candidate_paths: list of alternative paths to try
        - path_suggestions: dict or list of suggested paths
        - Extracts path from error_message as fallback
        """
        # Try direct old_path/new_path pair
        old_path = context.get("old_path")
        new_path = context.get("new_path")
        if old_path and new_path:
            return {"old_path": old_path, "new_path": new_path}

        # Try candidate_paths list
        candidate_paths = context.get("candidate_paths")
        if candidate_paths and isinstance(candidate_paths, list) and len(candidate_paths) > 0:
            return {"paths": candidate_paths}

        # Try path_suggestions (could be dict or list)
        path_suggestions = context.get("path_suggestions")
        if path_suggestions:
            if isinstance(path_suggestions, dict):
                # Assume dict maps old->new
                return {"paths": path_suggestions}
            elif isinstance(path_suggestions, list) and len(path_suggestions) > 0:
                return {"paths": path_suggestions}

        # Try to extract path from error message and suggest common alternatives
        if error_message:
            error_lower = error_message.lower()
            common_alternates = {
                "/var/log/syslog": "/var/log/messages",
                "/var/log/messages": "/var/log/syslog",
                "/var/log/auth.log": "/var/log/secure",
                "/var/log/secure": "/var/log/auth.log",
            }
            for old, new in common_alternates.items():
                if old in error_lower:
                    return {"old_path": old, "new_path": new}

        # Fallback: empty paths list with descriptive message
        return {"paths": [], "note": "No alternate paths identified"}

    def _enrich_alternate_command_params(
        self, context: Dict[str, Any], error_message: str
    ) -> Dict[str, Any]:
        """
        Enrich params for RETRY_ALTERNATE_COMMAND from available context keys.

        Checks for:
        - old_command/new_command: direct command pair
        - candidate_commands: list of alternative commands
        - command_suggestions: dict or list of suggested commands
        - Extracts command from error_message/context as fallback
        """
        # Try direct old_command/new_command pair
        old_command = context.get("old_command")
        new_command = context.get("new_command")
        if old_command and new_command:
            return {"old_command": old_command, "new_command": new_command}

        # Try candidate_commands list
        candidate_commands = context.get("candidate_commands")
        if candidate_commands and isinstance(candidate_commands, list) and len(candidate_commands) > 0:
            return {"commands": candidate_commands}

        # Try command_suggestions (could be dict or list)
        command_suggestions = context.get("command_suggestions")
        if command_suggestions:
            if isinstance(command_suggestions, dict):
                return {"commands": command_suggestions}
            elif isinstance(command_suggestions, list) and len(command_suggestions) > 0:
                return {"commands": command_suggestions}

        # Try to extract command from context or error and suggest alternatives
        failed_command = context.get("command", "")
        if failed_command or error_message:
            # Common command alternatives
            common_alternates = {
                "python": ["python3", "python2"],
                "pip": ["pip3", "python -m pip", "python3 -m pip"],
                "vim": ["vi", "nano"],
                "less": ["more", "cat"],
                "service": ["systemctl"],
                "ifconfig": ["ip addr", "ip a"],
                "netstat": ["ss"],
            }
            cmd_to_check = failed_command.split()[0] if failed_command else ""
            if not cmd_to_check and error_message:
                # Try to extract command from error like "bash: foo: command not found"
                match = re.search(r"(?:bash:|sh:)\s*(\w+):", error_message)
                if match:
                    cmd_to_check = match.group(1)

            if cmd_to_check in common_alternates:
                return {
                    "old_command": cmd_to_check,
                    "alternatives": common_alternates[cmd_to_check],
                }

        # Fallback: empty commands list with descriptive message
        return {"commands": [], "note": "No alternate commands identified"}

    def _build_recommendation(
        self,
        action: ToolAction,
        confidence: float,
        context: Dict[str, Any],
        error_message: str,
        reason: str,
    ) -> ToolRecommendation:
        """Build a recommendation with appropriate parameters."""
        params: Dict[str, Any] = {}
        tool_name: Optional[str] = None

        if action == ToolAction.REQUEST_ELEVATION:
            tool_name = "request_elevation"
            params = {
                "target": context.get("target", ""),
                "command": context.get("command", ""),
                "error_message": error_message[:200] if error_message else "",
                "reason": "Elevation required based on error analysis",
            }

        elif action == ToolAction.ASK_USER:
            tool_name = "ask_user"
            params = {"question": context.get("question", "Please provide more information")}

        elif action == ToolAction.REQUEST_CREDENTIALS:
            tool_name = "request_credentials"
            service = self._detect_service_from_context(context, error_message.lower() if error_message else "")
            params = {
                "target": context.get("target", ""),
                "service": service,
                "error_message": error_message[:200] if error_message else "",
                "reason": "Credentials required based on error analysis",
            }

        elif action == ToolAction.PROVIDE_CREDENTIALS:
            # Deprecated - redirect to REQUEST_CREDENTIALS
            tool_name = "request_credentials"
            service = self._detect_service_from_context(context, error_message.lower() if error_message else "")
            params = {
                "target": context.get("target", ""),
                "service": service,
                "error_message": error_message[:200] if error_message else "",
                "reason": "Credentials required",
            }

        elif action == ToolAction.RETRY_WITH_SUDO:
            params = {"prefix": "sudo"}

        elif action == ToolAction.RETRY_ALTERNATE_PATH:
            params = context.get("alternate_paths", {})
            # Enrich params from other context keys if alternate_paths is empty
            if not params:
                params = self._enrich_alternate_path_params(context, error_message)

        elif action == ToolAction.RETRY_ALTERNATE_COMMAND:
            params = context.get("alternate_commands", {})
            # Enrich params from other context keys if alternate_commands is empty
            if not params:
                params = self._enrich_alternate_command_params(context, error_message)

        return ToolRecommendation(
            action=action,
            confidence=confidence,
            tool_name=tool_name,
            tool_params=params,
            reason=reason,
        )

    @property
    def is_ai_powered(self) -> bool:
        """Check if AI (embeddings) is being used."""
        return self._use_embeddings


# Singleton instance
_tool_selector: Optional[ToolSelector] = None


def get_tool_selector(force_new: bool = False) -> ToolSelector:
    """
    Get or create the tool selector singleton.

    Args:
        force_new: If True, create a new instance

    Returns:
        ToolSelector instance
    """
    global _tool_selector

    if force_new or _tool_selector is None:
        _tool_selector = ToolSelector()

    return _tool_selector


def reset_tool_selector() -> None:
    """Reset the tool selector singleton (for testing)."""
    global _tool_selector
    _tool_selector = None
