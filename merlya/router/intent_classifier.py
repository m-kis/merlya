"""
Merlya Router - Intent Classification (Pattern-based).

ONNX-based embedding classification has been removed in v0.8.0.
This module provides pattern-based classification only.

For advanced classification, use the CenterClassifier with mini-LLM
(Phase 5 of the architecture refactoring).
"""

from __future__ import annotations

import re
from enum import Enum

from loguru import logger


class AgentMode(str, Enum):
    """Agent operation modes."""

    DIAGNOSTIC = "diagnostic"  # Read-only investigation
    REMEDIATION = "remediation"  # Fixing, changing, deploying
    QUERY = "query"  # Questions, explanations
    CHAT = "chat"  # Greetings, general conversation


# Patterns for mode classification
MODE_PATTERNS = {
    AgentMode.DIAGNOSTIC: [
        r"\bcheck\b",
        r"\bstatus\b",
        r"\bshow\b",
        r"\blist\b",
        r"\bget\b",
        r"\bview\b",
        r"\blog[s]?\b",
        r"\bmonitor\b",
        r"\banalyze\b",
        r"\binspect\b",
        r"\bdebug\b",
        r"\bdiagnose\b",
        r"\btest\b",
        r"\bverify\b",
        r"\bvérifie\b",
        r"\baffiche\b",
        r"\bmontre\b",
    ],
    AgentMode.REMEDIATION: [
        r"\bfix\b",
        r"\brestart\b",
        r"\bdeploy\b",
        r"\binstall\b",
        r"\bupdate\b",
        r"\bupgrade\b",
        r"\bremove\b",
        r"\bdelete\b",
        r"\bconfigure\b",
        r"\bstart\b",
        r"\bstop\b",
        r"\benable\b",
        r"\bdisable\b",
        r"\bcreate\b",
        r"\bmodify\b",
        r"\brépare\b",
        r"\bredémarre\b",
        r"\binstalle\b",
        r"\bsupprime\b",
    ],
    AgentMode.QUERY: [
        r"^(what|how|why|when|where|who|which)\b",
        r"\bexplain\b",
        r"\bdescribe\b",
        r"\bhelp\b",
        r"^\?\s*",
        r"\bquest(ion)?s?\b",
        r"^(quoi|comment|pourquoi|où|qui|quel)\b",
        r"\bexplique\b",
        r"\baide\b",
    ],
    AgentMode.CHAT: [
        r"^(hi|hello|hey|bonjour|salut|coucou)\b",
        r"^(bye|goodbye|au revoir|à plus)\b",
        r"^(thanks?|merci)\b",
        r"^(yes|no|ok|oui|non|d'accord)\b",
    ],
}

# Tool-related patterns
TOOL_PATTERNS = {
    "system": [r"\b(cpu|memory|disk|process|service|uptime|load)\b"],
    "files": [r"\b(file|config|log|read|write|edit|cat|grep)\b"],
    "security": [r"\b(port|firewall|ssh|ssl|tls|cert|permission)\b"],
    "docker": [r"\b(docker|container|image|volume)\b"],
    "kubernetes": [r"\b(k8s|kubernetes|kubectl|pod|deployment|service|namespace)\b"],
    "network": [r"\b(network|ip|dns|ping|curl|wget|http)\b"],
}

# Entity extraction patterns
ENTITY_PATTERNS = {
    "hosts": r"@([a-zA-Z0-9_.-]+)",
    "services": r"\b(nginx|apache|mysql|postgres|redis|mongo|docker)\b",
    "paths": r"(/[a-zA-Z0-9_./-]+)",
    "ports": r":(\d{2,5})\b",
}

# Delegation patterns
DELEGATION_PATTERNS = {
    "ssh": [r"\bssh\b", r"\bremote\b", r"\bdistant\b"],
    "docker": [r"\bdocker\b", r"\bcontainer\b"],
    "kubernetes": [r"\bk8s\b", r"\bkubernetes\b", r"\bkubectl\b"],
}


class IntentClassifier:
    """Pattern-based intent classifier (ONNX removed in v0.8.0)."""

    CONFIDENCE_THRESHOLD = 0.6

    def __init__(
        self,
        use_embeddings: bool = False,
        model_id: str | None = None,
        tier: str | None = None,
    ) -> None:
        """Initialize classifier."""
        # ONNX parameters are kept for backward compatibility but ignored
        _ = use_embeddings, model_id, tier
        self._model_loaded = False
        self._embedding_dim: int | None = None
        logger.debug("IntentClassifier initialized (pattern-based only)")

    async def load_model(self) -> bool:
        """Load model (no-op, kept for backward compatibility)."""
        logger.debug("ONNX model loading skipped (removed in v0.8.0)")
        return False

    @property
    def model_loaded(self) -> bool:
        """Return False - ONNX model is not used."""
        return False

    @property
    def embedding_dim(self) -> int | None:
        """Return None - no embeddings available."""
        return None

    def classify_patterns(self, text: str) -> tuple[AgentMode, float]:
        """Classify intent using regex patterns."""
        text_lower = text.lower()

        best_mode = AgentMode.CHAT
        best_score = 0.0

        for mode, patterns in MODE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    score += 1

            # Normalize score
            normalized = min(score / max(len(patterns) * 0.3, 1), 1.0)
            if normalized > best_score:
                best_score = normalized
                best_mode = mode

        # Default confidence for pattern matching
        confidence = max(best_score, 0.5) if best_score > 0 else 0.4

        return best_mode, confidence

    async def classify_embeddings(self, text: str) -> tuple[AgentMode, float]:
        """Classify using embeddings (falls back to patterns - ONNX removed)."""
        return self.classify_patterns(text.lower())

    def extract_entities(self, text: str) -> dict[str, list[str]]:
        """Extract entities from text using patterns."""
        entities: dict[str, list[str]] = {}

        for entity_type, pattern in ENTITY_PATTERNS.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                entities[entity_type] = list(set(matches))

        return entities

    def determine_tools(self, text: str, entities: dict[str, list[str]]) -> list[str]:
        """Determine which tools are relevant."""
        tools = ["core"]  # Always include core

        for tool, patterns in TOOL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    if tool not in tools:
                        tools.append(tool)
                    break

        # Add tools based on entities
        if entities.get("hosts") and "ssh" not in tools:
            tools.append("ssh")

        return tools

    def check_delegation(self, text: str) -> str | None:
        """Check if request should be delegated to a specialist."""
        for delegate, patterns in DELEGATION_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return delegate
        return None


# Backward compatibility aliases
INTENT_PATTERNS = MODE_PATTERNS
TOOL_KEYWORDS = TOOL_PATTERNS
