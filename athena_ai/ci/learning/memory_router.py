"""
CI Memory Router - Route CI events to appropriate memory systems.

Bridges CI/CD events with Athena's existing memory infrastructure:
- SkillStore: Problem-solution pairs (e.g., "npm install fails" -> "clear cache")
- IncidentMemory: Full incident records for pattern analysis
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.ci.models import CIErrorType, FailureAnalysis, Run
from athena_ai.utils.logger import logger


@dataclass
class CIIncident:
    """CI-specific incident for memory storage."""

    id: str
    run_id: str
    workflow_name: str
    error_type: CIErrorType
    summary: str
    raw_error: str
    platform: str
    branch: str = ""
    commit_sha: str = ""
    failed_jobs: List[str] = field(default_factory=list)
    resolution: str = ""
    resolution_commands: List[str] = field(default_factory=list)
    created_at: str = ""
    resolved_at: str = ""
    auto_resolved: bool = False


@dataclass
class CISkill:
    """CI-specific skill (learned fix)."""

    trigger: str  # Error pattern (e.g., "npm ERR! ERESOLVE")
    solution: str  # Fix command or action
    error_type: CIErrorType
    platform: str
    success_count: int = 0
    failure_count: int = 0
    last_used: str = ""


class CIMemoryRouter:
    """
    Routes CI events to appropriate memory systems.

    Features:
    - Records CI failures as incidents
    - Learns fixes as skills
    - Finds similar past failures
    - Suggests fixes based on history
    """

    def __init__(
        self,
        skill_store: Optional[Any] = None,
        incident_memory: Optional[Any] = None,
    ):
        """
        Initialize router.

        Args:
            skill_store: Athena's SkillStore instance
            incident_memory: Athena's IncidentMemory instance
        """
        self._skill_store = skill_store
        self._incident_memory = incident_memory
        self._pending_incidents: Dict[str, CIIncident] = {}

    @property
    def skill_store(self) -> Optional[Any]:
        """Lazy load SkillStore."""
        if self._skill_store is None:
            try:
                from athena_ai.memory.skill_store import SkillStore
                self._skill_store = SkillStore()
            except ImportError:
                logger.warning("SkillStore not available")
        return self._skill_store

    @property
    def incident_memory(self) -> Optional[Any]:
        """Lazy load IncidentMemory."""
        if self._incident_memory is None:
            try:
                from athena_ai.knowledge.incident_memory import IncidentMemory
                from athena_ai.knowledge.storage_manager import StorageManager
                storage = StorageManager()
                self._incident_memory = IncidentMemory(storage)
            except ImportError:
                logger.warning("IncidentMemory not available")
        return self._incident_memory

    def record_failure(
        self,
        run: Run,
        analysis: FailureAnalysis,
        platform: str = "unknown",
    ) -> str:
        """
        Record a CI failure for learning.

        Args:
            run: The failed run
            analysis: Failure analysis
            platform: CI platform name

        Returns:
            Incident ID
        """
        incident_id = f"ci-{run.id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        incident = CIIncident(
            id=incident_id,
            run_id=run.id,
            workflow_name=run.workflow_name or run.name,
            error_type=analysis.error_type,
            summary=analysis.summary,
            raw_error=analysis.raw_error,
            platform=platform,
            branch=run.branch,
            commit_sha=run.commit_sha or "",
            failed_jobs=analysis.failed_jobs,
            created_at=datetime.utcnow().isoformat(),
        )

        # Store for later resolution
        self._pending_incidents[incident_id] = incident

        # Record in IncidentMemory if available
        if self.incident_memory:
            try:
                self.incident_memory.record_incident(
                    title=f"CI Failure: {run.workflow_name or run.name}",
                    priority="P2" if analysis.error_type != CIErrorType.FLAKY_TEST else "P3",
                    description=analysis.summary,
                    symptoms=[analysis.error_type.value] + analysis.failed_jobs,
                    service=f"ci/{platform}",
                    tags=[platform, analysis.error_type.value, "ci-failure"],
                )
                logger.debug(f"Recorded CI incident: {incident_id}")
            except Exception as e:
                logger.warning(f"Failed to record incident: {e}")

        return incident_id

    def record_resolution(
        self,
        incident_id: str,
        resolution: str,
        commands: Optional[List[str]] = None,
        auto_resolved: bool = False,
    ) -> bool:
        """
        Record how a CI failure was resolved.

        Args:
            incident_id: The incident ID
            resolution: Description of the fix
            commands: Commands used to fix
            auto_resolved: Whether it was auto-resolved (retry, etc.)

        Returns:
            True if recorded successfully
        """
        incident = self._pending_incidents.get(incident_id)
        if not incident:
            logger.warning(f"Incident {incident_id} not found")
            return False

        incident.resolution = resolution
        incident.resolution_commands = commands or []
        incident.resolved_at = datetime.utcnow().isoformat()
        incident.auto_resolved = auto_resolved

        # Learn as a skill if we have a concrete fix
        if commands and self.skill_store:
            try:
                # Create skill trigger from error pattern
                trigger = self._create_skill_trigger(incident)
                solution = " && ".join(commands) if len(commands) > 1 else commands[0]

                self.skill_store.add_skill(
                    trigger=trigger,
                    solution=solution,
                    context=f"ci/{incident.platform}/{incident.error_type.value}",
                )
                logger.debug(f"Learned CI skill: {trigger[:50]}...")
            except Exception as e:
                logger.warning(f"Failed to learn skill: {e}")

        # Clean up pending
        del self._pending_incidents[incident_id]
        return True

    def find_similar_failures(
        self,
        analysis: FailureAnalysis,
        platform: str = "",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Find similar past CI failures.

        Args:
            analysis: Current failure analysis
            platform: Filter by platform
            limit: Max results

        Returns:
            List of similar incidents
        """
        if not self.incident_memory:
            return []

        try:
            # Search by symptoms (error type + failed jobs)
            symptoms = [analysis.error_type.value] + analysis.failed_jobs

            matches = self.incident_memory.find_similar(
                symptoms=symptoms,
                service=f"ci/{platform}" if platform else "",
                limit=limit,
            )

            return [
                {
                    "id": m.incident.id if hasattr(m, "incident") else m.get("id", ""),
                    "title": m.incident.title if hasattr(m, "incident") else m.get("title", ""),
                    "solution": m.incident.solution if hasattr(m, "incident") else m.get("solution", ""),
                    "score": m.score if hasattr(m, "score") else 0.0,
                }
                for m in matches
            ]
        except Exception as e:
            logger.warning(f"Failed to find similar incidents: {e}")
            return []

    def suggest_fix(
        self,
        analysis: FailureAnalysis,
        platform: str = "",
    ) -> Optional[str]:
        """
        Suggest a fix based on learned skills.

        Args:
            analysis: Failure analysis
            platform: CI platform

        Returns:
            Suggested fix command, or None
        """
        if not self.skill_store:
            return None

        try:
            # Create search query from error
            query = f"{analysis.error_type.value} {analysis.summary[:100]}"

            # Search skills (method is search_skills in SkillStore)
            matches = self.skill_store.search_skills(query=query, limit=3)

            # Filter by CI context if available
            if platform:
                ci_matches = [
                    m for m in matches
                    if hasattr(m, "context") and f"ci/{platform}" in (m.context or "")
                ]
                if ci_matches:
                    matches = ci_matches

            if matches:
                best_match = matches[0]
                return best_match.solution if hasattr(best_match, "solution") else None

        except Exception as e:
            logger.warning(f"Failed to suggest fix: {e}")

        return None

    def _create_skill_trigger(self, incident: CIIncident) -> str:
        """Create a skill trigger from an incident."""
        parts = [incident.error_type.value]

        # Add first failed job if available
        if incident.failed_jobs:
            parts.append(incident.failed_jobs[0])

        # Add key words from summary
        summary_words = incident.summary.split()[:5]
        parts.extend(summary_words)

        return " ".join(parts)

    def get_statistics(self) -> Dict[str, Any]:
        """Get CI learning statistics."""
        stats = {
            "pending_incidents": len(self._pending_incidents),
            "skill_store_available": self.skill_store is not None,
            "incident_memory_available": self.incident_memory is not None,
        }

        if self.skill_store:
            try:
                ci_skills = [
                    s for s in self.skill_store.skills
                    if "ci/" in (s.context if hasattr(s, "context") else "")
                ]
                stats["ci_skills_count"] = len(ci_skills)
            except Exception:
                pass

        return stats
