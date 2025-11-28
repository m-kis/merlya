"""
Relation Classifier Models.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class RelationSuggestion:
    """A suggested relation between two hosts."""

    source_hostname: str
    target_hostname: str
    relation_type: str
    confidence: float
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "source_hostname": self.source_hostname,
            "target_hostname": self.target_hostname,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "metadata": self.metadata,
        }
