"""
CI Memory Router - Route CI events to appropriate memory systems.

Bridges CI/CD events with Merlya's existing memory infrastructure:
- SkillStore: Problem-solution pairs (e.g., "npm install fails" -> "clear cache")
- IncidentMemory: Full incident records for pattern analysis
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from merlya.ci.models import CIErrorType, FailureAnalysis, Run
from merlya.utils.logger import logger


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

    # Resource limits to prevent unbounded memory growth
    MAX_PENDING_INCIDENTS = 100
    INCIDENT_TTL_HOURS = 24  # Auto-expire unresolved incidents after 24h

    def __init__(
        self,
        skill_store: Optional[Any] = None,
        incident_memory: Optional[Any] = None,
        max_pending: int = MAX_PENDING_INCIDENTS,
    ):
        """
        Initialize router.

        Args:
            skill_store: Merlya's SkillStore instance
            incident_memory: Merlya's IncidentMemory instance
            max_pending: Maximum number of pending incidents to keep
        """
        self._skill_store = skill_store
        self._incident_memory = incident_memory
        self._pending_incidents: Dict[str, CIIncident] = {}
        self._max_pending = max_pending

    @property
    def skill_store(self) -> Optional[Any]:
        """Lazy load SkillStore."""
        if self._skill_store is None:
            try:
                from merlya.memory.skill_store import SkillStore
                self._skill_store = SkillStore()
            except ImportError:
                logger.warning("SkillStore not available")
        return self._skill_store

    @property
    def incident_memory(self) -> Optional[Any]:
        """Lazy load IncidentMemory."""
        if self._incident_memory is None:
            try:
                from merlya.knowledge.incident_memory import IncidentMemory
                from merlya.knowledge.storage_manager import StorageManager
                storage = StorageManager()
                self._incident_memory = IncidentMemory(storage)
            except ImportError:
                logger.warning("IncidentMemory not available")
        return self._incident_memory

    def _cleanup_expired_incidents(self) -> None:
        """Remove expired pending incidents to prevent memory exhaustion."""
        now = datetime.utcnow()
        expired_ids = []

        for incident_id, incident in self._pending_incidents.items():
            try:
                created = datetime.fromisoformat(incident.created_at)
                age_hours = (now - created).total_seconds() / 3600
                if age_hours > self.INCIDENT_TTL_HOURS:
                    expired_ids.append(incident_id)
            except (ValueError, TypeError):
                # Invalid timestamp - mark for removal
                expired_ids.append(incident_id)

        for incident_id in expired_ids:
            del self._pending_incidents[incident_id]
            logger.debug(f"Expired pending CI incident: {incident_id}")

    def _enforce_pending_limit(self) -> None:
        """Enforce maximum pending incidents limit (FIFO eviction)."""
        if len(self._pending_incidents) < self._max_pending:
            return

        # Sort by created_at and remove oldest
        sorted_incidents = sorted(
            self._pending_incidents.items(),
            key=lambda x: x[1].created_at,
        )

        # Remove oldest until under limit
        to_remove = len(self._pending_incidents) - self._max_pending + 1
        for incident_id, _ in sorted_incidents[:to_remove]:
            del self._pending_incidents[incident_id]
            logger.debug(f"Evicted old CI incident due to limit: {incident_id}")

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
        # Cleanup before adding new incident
        self._cleanup_expired_incidents()
        self._enforce_pending_limit()

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
