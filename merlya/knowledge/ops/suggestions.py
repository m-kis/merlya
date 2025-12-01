from typing import Any, Dict, List, Optional

from merlya.knowledge.ops.risk import RiskAssessor
from merlya.utils.logger import logger


class SuggestionEngine:
    """Engine for generating suggestions and remediations."""

    def __init__(self, incidents, patterns, storage):
        self.incidents = incidents
        self.patterns = patterns
        self.storage = storage
        self.risk_assessor = RiskAssessor()

    def get_suggestion(
        self,
        text: str = "",
        symptoms: Optional[List[str]] = None,
        service: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a solution suggestion based on patterns and past incidents.
        """
        # Try patterns first (faster, more precise)
        pattern_suggestion = self.patterns.suggest_from_text(text)
        if pattern_suggestion and pattern_suggestion.get("confidence", 0) >= 0.5:
            return {
                "solution": pattern_suggestion["solution"],
                "commands": pattern_suggestion.get("commands", []),
                "confidence": pattern_suggestion["confidence"],
                "source": "pattern",
                "source_id": pattern_suggestion["pattern_id"],
                "source_name": pattern_suggestion["pattern_name"],
            }

        # Try incident memory
        incident_suggestion = self.incidents.suggest_solution(
            symptoms=symptoms,
            service=service,
            environment=environment,
        )
        if incident_suggestion and incident_suggestion.get("confidence", 0) >= 0.3:
            return {
                "solution": incident_suggestion["solution"],
                "commands": incident_suggestion.get("commands", []),
                "confidence": incident_suggestion["confidence"],
                "source": "incident",
                "source_id": incident_suggestion["source_incident"],
                "source_name": incident_suggestion["source_title"],
                "root_cause": incident_suggestion.get("root_cause"),
            }

        return None

    def get_remediation_for_incident(
        self,
        incident_id: Optional[str] = None,
        symptoms: Optional[List[str]] = None,
        service: Optional[str] = None,
        environment: Optional[str] = None,
        title: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Get remediation suggestion for an incident.
        """
        # If incident_id provided, load its details
        if incident_id:
            incident = self.storage.get_incident(incident_id)
            if incident:
                symptoms = symptoms or incident.get("symptoms", [])
                service = service or incident.get("service")
                environment = environment or incident.get("environment")
                title = title or incident.get("title", "")

        # First try pattern matching (faster, more reliable)
        pattern_matches = self.patterns.match_patterns(
            text=title,
            symptoms=symptoms,
            service=service,
            environment=environment,
            min_score=0.4,
            limit=3,
        )

        if pattern_matches:
            best_match = pattern_matches[0]
            pattern = best_match.pattern

            # Assess risk level based on commands
            commands = pattern.suggested_commands or []
            risk_level, auto_executable = self.risk_assessor.assess_command_risk(commands)

            return {
                "remediation": pattern.suggested_solution,
                "commands": commands,
                "confidence": best_match.score,
                "source": "pattern",
                "source_id": pattern.id,
                "source_name": pattern.name,
                "matched_keywords": best_match.matched_keywords,
                "matched_symptoms": best_match.matched_symptoms,
                "risk_level": risk_level,
                "auto_executable": auto_executable,
            }

        # Try incident memory
        incident_suggestion = self.incidents.suggest_solution(
            symptoms=symptoms,
            service=service,
            environment=environment,
        )

        if incident_suggestion and incident_suggestion.get("confidence", 0) >= 0.3:
            commands = incident_suggestion.get("commands", [])
            risk_level, auto_executable = self.risk_assessor.assess_command_risk(commands)

            return {
                "remediation": incident_suggestion["solution"],
                "commands": commands,
                "confidence": incident_suggestion["confidence"],
                "source": "incident",
                "source_id": incident_suggestion["source_incident"],
                "source_name": incident_suggestion["source_title"],
                "root_cause": incident_suggestion.get("root_cause"),
                "matching_features": incident_suggestion.get("matching_features", []),
                "risk_level": risk_level,
                "auto_executable": auto_executable,
            }

        return None

    def record_feedback(self, source: str, source_id: Any, helpful: bool):
        """Record feedback for a suggestion."""
        if source == "pattern" and source_id:
            self.patterns.record_match(source_id, success=helpful)
            logger.debug(f"Recorded pattern feedback: {source_id} -> {helpful}")
