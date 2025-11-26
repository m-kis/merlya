"""
Ops Knowledge Manager - Unified facade for all knowledge systems.

Provides a single entry point for:
- Incident memory (recording, finding similar incidents)
- Pattern learning (extracting and matching patterns)
- CVE monitoring (vulnerability checks)
- Storage management (SQLite + FalkorDB)

This is the main interface that the orchestrator uses.
"""

from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

from .cve_monitor import CVE, CVEMonitor, VulnerabilityCheck
from .incident_memory import IncidentMemory, SimilarityMatch
from .ops.suggestions import SuggestionEngine
from .pattern_learner import PatternLearner, PatternMatch
from .storage_manager import AuditEntry, StorageManager


class OpsKnowledgeManager:
    """
    Unified knowledge management facade.

    Usage:
        knowledge = OpsKnowledgeManager()

        # Record an incident
        incident_id = knowledge.record_incident(
            title="MongoDB down on prod",
            priority="P0",
            service="mongodb",
            symptoms=["connection refused", "no response"]
        )

        # Find similar past incidents
        similar = knowledge.find_similar_incidents(
            symptoms=["connection refused"],
            service="mongodb"
        )

        # Check for CVEs
        vulns = knowledge.check_package("requests", "2.28.0")

        # Get suggestion for a problem
        suggestion = knowledge.get_suggestion(
            text="nginx high latency",
            service="nginx"
        )
    """

    def __init__(
        self,
        sqlite_path: Optional[str] = None,
        enable_falkordb: bool = True,
        cve_cache_hours: int = 24,
    ):
        # Initialize storage
        self.storage = StorageManager(
            sqlite_path=sqlite_path,
            enable_falkordb=enable_falkordb,
        )

        # Initialize subsystems
        self.incidents = IncidentMemory(self.storage)
        self.patterns = PatternLearner(self.storage)
        self.cve_monitor = CVEMonitor(cache_ttl_hours=cve_cache_hours)

        # Initialize suggestion engine
        self.suggestion_engine = SuggestionEngine(
            self.incidents,
            self.patterns,
            self.storage
        )

        # Session tracking
        self._current_session_id: Optional[str] = None

    # =========================================================================
    # Session Management
    # =========================================================================

    def start_session(self, session_id: str, env: str = "dev", metadata: Dict = None):
        """Start a new session for tracking."""
        self._current_session_id = session_id
        self.storage.create_session(session_id, env, metadata)
        logger.debug(f"Knowledge session started: {session_id}")

    def end_session(self):
        """End the current session."""
        if self._current_session_id:
            self.storage.end_session(self._current_session_id)
            self._current_session_id = None

    # =========================================================================
    # Incident Management
    # =========================================================================

    def record_incident(
        self,
        title: str,
        priority: str,
        description: str = "",
        environment: str = "",
        service: str = "",
        host: str = "",
        symptoms: List[str] = None,
        tags: List[str] = None,
    ) -> str:
        """
        Record a new incident.

        Args:
            title: Incident title/summary
            priority: Priority level (P0, P1, P2, P3)
            description: Detailed description
            environment: Environment (prod, staging, dev)
            service: Affected service (nginx, mongodb, etc.)
            host: Affected hostname
            symptoms: List of symptoms observed
            tags: Optional tags for categorization

        Returns:
            Incident ID
        """
        incident_id = self.incidents.record_incident(
            title=title,
            priority=priority,
            description=description,
            environment=environment,
            service=service,
            host=host,
            symptoms=symptoms,
            tags=tags,
        )

        # Update session stats
        if self._current_session_id:
            self.storage.update_session_stats(
                self._current_session_id,
                incidents=1,
            )

        return incident_id

    def resolve_incident(
        self,
        incident_id: str,
        root_cause: str,
        solution: str,
        commands_executed: List[str] = None,
        learn_pattern: bool = True,
    ) -> bool:
        """
        Resolve an incident and optionally learn from it.

        Args:
            incident_id: ID of incident to resolve
            root_cause: What caused the incident
            solution: How it was resolved
            commands_executed: Commands that fixed it
            learn_pattern: Whether to create a pattern from this

        Returns:
            Success status
        """
        success = self.incidents.resolve_incident(
            incident_id=incident_id,
            root_cause=root_cause,
            solution=solution,
            commands_executed=commands_executed,
        )

        # Try to learn a pattern from this incident
        if success and learn_pattern:
            pattern_id = self.patterns.learn_from_incident(incident_id)
            if pattern_id:
                logger.info(f"Learned pattern {pattern_id} from incident {incident_id}")

        return success

    def find_similar_incidents(
        self,
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
        limit: int = 5,
    ) -> List[SimilarityMatch]:
        """
        Find similar past incidents.

        Returns:
            List of similar incidents with match scores
        """
        return self.incidents.find_similar(
            symptoms=symptoms,
            service=service,
            environment=environment,
            limit=limit,
        )

    # =========================================================================
    # Pattern Matching
    # =========================================================================

    def match_patterns(
        self,
        text: str = "",
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
        limit: int = 5,
    ) -> List[PatternMatch]:
        """
        Find patterns matching the current situation.

        Returns:
            List of matching patterns with scores
        """
        return self.patterns.match_patterns(
            text=text,
            symptoms=symptoms,
            service=service,
            environment=environment,
            limit=limit,
        )

    def add_pattern(
        self,
        name: str,
        description: str = "",
        symptoms: List[str] = None,
        keywords: List[str] = None,
        service: str = "",
        suggested_solution: str = "",
        suggested_commands: List[str] = None,
    ) -> int:
        """
        Add a manual pattern definition.

        Returns:
            Pattern ID
        """
        return self.patterns.add_pattern(
            name=name,
            description=description,
            symptoms=symptoms,
            keywords=keywords,
            service=service,
            suggested_solution=suggested_solution,
            suggested_commands=suggested_commands,
        )

    # =========================================================================
    # Suggestion Engine
    # =========================================================================

    def get_suggestion(
        self,
        text: str = "",
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get a solution suggestion based on patterns and past incidents.

        This is the main "intelligent" interface that combines:
        - Pattern matching
        - Similar incident lookup
        - Solution recommendation

        Returns:
            Suggestion dict with:
            - solution: Suggested solution text
            - commands: Suggested commands
            - confidence: Confidence score (0-1)
            - source: Where suggestion came from
            - source_id: ID of pattern or incident
        """
        return self.suggestion_engine.get_suggestion(
            text=text,
            symptoms=symptoms,
            service=service,
            environment=environment,
        )

    def record_suggestion_feedback(
        self,
        source: str,
        source_id: Any,
        helpful: bool,
    ):
        """
        Record whether a suggestion was helpful.

        This improves future suggestions.
        """
        self.suggestion_engine.record_feedback(source, source_id, helpful)

    def get_remediation_for_incident(
        self,
        incident_id: str = None,
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
        title: str = "",
    ) -> Optional[Dict[str, Any]]:
        """
        Get remediation suggestion for an incident.

        This is the main self-healing interface that:
        1. Finds similar past incidents
        2. Matches patterns from learned resolutions
        3. Returns actionable remediation steps

        Can be called with:
        - An existing incident_id to find remediation for it
        - Symptoms/service/environment to find remediation proactively

        Args:
            incident_id: Optional existing incident ID
            symptoms: Observed symptoms
            service: Affected service
            environment: Environment (prod, staging, dev)
            title: Incident title or description

        Returns:
            Dict with:
            - remediation: Recommended remediation steps
            - commands: Suggested commands to execute
            - confidence: Confidence score (0-1)
            - source: Where suggestion came from (pattern|incident)
            - source_id: ID of pattern or incident
            - risk_level: Estimated risk (low, medium, high)
            - auto_executable: Whether commands are safe for auto-execution
        """
        return self.suggestion_engine.get_remediation_for_incident(
            incident_id=incident_id,
            symptoms=symptoms,
            service=service,
            environment=environment,
            title=title,
        )

    # =========================================================================
    # CVE Monitoring
    # =========================================================================

    def check_package(
        self,
        package: str,
        version: str,
        ecosystem: str = "PyPI",
    ) -> VulnerabilityCheck:
        """
        Check a package for vulnerabilities.

        Args:
            package: Package name
            version: Package version
            ecosystem: Package ecosystem (PyPI, npm, Go, etc.)

        Returns:
            VulnerabilityCheck result
        """
        return self.cve_monitor.check_package(package, version, ecosystem)

    def check_requirements(self, content: str) -> Dict[str, Any]:
        """
        Check a requirements.txt file for vulnerabilities.

        Returns:
            Summary with vulnerable packages and recommendations
        """
        checks = self.cve_monitor.check_requirements_txt(content)
        return self.cve_monitor.get_summary(checks)

    def get_cve(self, cve_id: str) -> Optional[CVE]:
        """Get details for a specific CVE."""
        return self.cve_monitor.get_cve(cve_id)

    # =========================================================================
    # Audit Logging
    # =========================================================================

    def log_action(
        self,
        action: str,
        target: str = "",
        command: str = "",
        result: str = "success",
        details: str = "",
        priority: str = "",
    ):
        """
        Log an action to the audit trail.

        Args:
            action: Action type (e.g., "execute_command", "scan_host")
            target: Target of the action (hostname, service)
            command: Command executed
            result: Result (success, failure, error)
            details: Additional details
            priority: Priority level if applicable
        """
        entry = AuditEntry(
            action=action,
            target=target,
            command=command,
            result=result,
            details=details,
            session_id=self._current_session_id or "",
            priority=priority,
        )

        self.storage.log_audit(entry)

        # Update session stats if command was executed
        if action == "execute_command" and self._current_session_id:
            self.storage.update_session_stats(
                self._current_session_id,
                commands=1,
            )

    def get_audit_log(
        self,
        session_id: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[AuditEntry]:
        """Get audit log entries with filters."""
        return self.storage.get_audit_log(
            session_id=session_id or self._current_session_id,
            action=action,
            since=since,
            limit=limit,
        )

    # =========================================================================
    # Statistics & Health
    # =========================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive knowledge system statistics.

        Returns:
            Dict with stats from all subsystems
        """
        storage_stats = self.storage.get_stats()

        resolution_stats = self.incidents.get_resolution_stats()

        pattern_count = len(self.patterns._patterns) if self.patterns._loaded else "not loaded"

        return {
            "storage": storage_stats,
            "incidents": {
                **resolution_stats,
                "common_symptoms": self.incidents.get_common_symptoms(limit=5),
            },
            "patterns": {
                "count": pattern_count,
                "top_patterns": [
                    {"name": p.name, "matches": p.times_matched}
                    for p in self.patterns.get_top_patterns(limit=3)
                ],
            },
            "cve_cache_size": len(self.cve_monitor._cache),
        }

    def sync_knowledge(self) -> Dict[str, int]:
        """
        Sync knowledge to FalkorDB if available.

        Returns:
            Dict with sync counts
        """
        return self.storage.sync_to_falkordb()


# Singleton instance
_default_manager: Optional[OpsKnowledgeManager] = None


def get_knowledge_manager() -> OpsKnowledgeManager:
    """Get the default OpsKnowledgeManager instance."""
    global _default_manager

    if _default_manager is None:
        _default_manager = OpsKnowledgeManager()

    return _default_manager
