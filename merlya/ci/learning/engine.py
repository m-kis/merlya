"""
CI Learning Engine - Orchestrates CI/CD learning and analysis.

Combines:
- Error classification (semantic via embeddings)
- Memory routing (SkillStore + IncidentMemory)
- Pattern recognition
- Fix suggestions
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merlya.ci.analysis.error_classifier import CIErrorClassifier
from merlya.ci.learning.memory_router import CIMemoryRouter
from merlya.ci.models import CIErrorType, FailureAnalysis, Run, RunLogs


@dataclass
class LearningInsight:
    """Insight derived from CI failure analysis."""

    error_type: CIErrorType
    confidence: float
    summary: str
    suggestions: List[str] = field(default_factory=list)
    similar_incidents: List[Dict[str, Any]] = field(default_factory=list)
    learned_fix: Optional[str] = None
    pattern_matches: List[str] = field(default_factory=list)


class CILearningEngine:
    """
    Main orchestrator for CI learning.

    Provides:
    - Unified analysis pipeline
    - Learning from failures
    - Pattern detection
    - Fix suggestions
    """

    def __init__(
        self,
        classifier: Optional[CIErrorClassifier] = None,
        memory_router: Optional[CIMemoryRouter] = None,
    ):
        """
        Initialize learning engine.

        Args:
            classifier: Error classifier (creates default if not provided)
            memory_router: Memory router (creates default if not provided)
        """
        self._classifier = classifier
        self._memory_router = memory_router

    @property
    def classifier(self) -> CIErrorClassifier:
        """Get or create error classifier."""
        if self._classifier is None:
            self._classifier = CIErrorClassifier()
        return self._classifier

    @property
    def memory_router(self) -> CIMemoryRouter:
        """Get or create memory router."""
        if self._memory_router is None:
            self._memory_router = CIMemoryRouter()
        return self._memory_router

    def analyze_failure(
        self,
        run: Run,
        logs: RunLogs,
        platform: str = "unknown",
    ) -> FailureAnalysis:
        """
        Perform comprehensive failure analysis.

        Args:
            run: The failed run
            logs: Run logs
            platform: CI platform name

        Returns:
            Complete failure analysis
        """
        # Extract error text
        error_text = self._extract_error_text(logs)

        # Classify using semantic analysis
        classification = self.classifier.classify(error_text)

        # Get base suggestions from classifier
        suggestions = self.classifier.get_suggestions(
            classification.error_type,
            error_text,
        )

        # Check for learned fixes
        learned_fix = self.memory_router.suggest_fix(
            FailureAnalysis(
                run_id=run.id,
                error_type=classification.error_type,
                summary=error_text[:200],
                raw_error=error_text,
            ),
            platform=platform,
        )

        if learned_fix:
            suggestions.insert(0, f"Learned fix: {learned_fix}")

        # Find similar past failures
        similar = self.memory_router.find_similar_failures(
            FailureAnalysis(
                run_id=run.id,
                error_type=classification.error_type,
                summary=error_text[:200],
                raw_error=error_text,
            ),
            platform=platform,
            limit=3,
        )

        # Build summary
        summary = self._build_summary(run, classification.error_type, error_text, similar)

        # Extract failed jobs
        failed_jobs = []
        if run.jobs:
            failed_jobs = [j.name for j in run.jobs if j.conclusion == "failure"]

        return FailureAnalysis(
            run_id=run.id,
            error_type=classification.error_type,
            summary=summary,
            raw_error=error_text[:5000],  # Limit size
            confidence=classification.confidence,
            failed_jobs=failed_jobs,
            suggestions=suggestions,
            matched_pattern=classification.matched_pattern,
        )

    def learn_from_resolution(
        self,
        run: Run,
        analysis: FailureAnalysis,
        resolution: str,
        commands: Optional[List[str]] = None,
        platform: str = "unknown",
    ) -> bool:
        """
        Learn from a successful resolution.

        Args:
            run: The run that was fixed
            analysis: Original failure analysis
            resolution: Description of the fix
            commands: Commands used
            platform: CI platform

        Returns:
            True if learned successfully
        """
        # Record the failure first
        incident_id = self.memory_router.record_failure(run, analysis, platform)

        # Then record the resolution
        return self.memory_router.record_resolution(
            incident_id=incident_id,
            resolution=resolution,
            commands=commands,
        )

    def get_insights(
        self,
        run: Run,
        logs: RunLogs,
        platform: str = "unknown",
    ) -> LearningInsight:
        """
        Get comprehensive learning insights for a failure.

        Args:
            run: The failed run
            logs: Run logs
            platform: CI platform

        Returns:
            Learning insight with all available information
        """
        # Analyze the failure
        analysis = self.analyze_failure(run, logs, platform)

        # Find similar incidents
        similar = self.memory_router.find_similar_failures(analysis, platform)

        # Check for learned fix
        learned_fix = self.memory_router.suggest_fix(analysis, platform)

        # Detect patterns
        patterns = self._detect_patterns(analysis, similar)

        return LearningInsight(
            error_type=analysis.error_type,
            confidence=analysis.confidence,
            summary=analysis.summary,
            suggestions=analysis.suggestions,
            similar_incidents=similar,
            learned_fix=learned_fix,
            pattern_matches=patterns,
        )

    def _extract_error_text(self, logs: RunLogs) -> str:
        """Extract meaningful error text from logs."""
        # Start with raw logs
        text = logs.raw_logs

        # If we have job-specific logs with failures, prioritize those
        if logs.job_logs:
            error_sections = []
            for job_name, job_log in logs.job_logs.items():
                # Look for error indicators
                if any(indicator in job_log.lower() for indicator in
                       ["error", "failed", "exception", "fatal"]):
                    error_sections.append(f"=== {job_name} ===\n{job_log}")

            if error_sections:
                text = "\n\n".join(error_sections)

        # Limit size for classification
        return text[:10000]

    def _build_summary(
        self,
        run: Run,
        error_type: CIErrorType,
        error_text: str,
        similar: List[Dict[str, Any]],
    ) -> str:
        """Build a human-readable summary."""
        parts = [f"Run '{run.name}' failed with {error_type.value}"]

        # Add failed jobs
        if run.jobs:
            failed_jobs = [j.name for j in run.jobs if j.conclusion == "failure"]
            if failed_jobs:
                parts.append(f"Failed jobs: {', '.join(failed_jobs)}")

        # Add first error line
        first_line = error_text.split("\n")[0][:150]
        if first_line:
            parts.append(f"Error: {first_line}")

        # Add similar incident info
        if similar:
            parts.append(f"Found {len(similar)} similar past incidents")

        return ". ".join(parts)

    def _detect_patterns(
        self,
        analysis: FailureAnalysis,
        similar: List[Dict[str, Any]],
    ) -> List[str]:
        """Detect patterns from failure and similar incidents."""
        patterns = []

        # Same error type recurring
        if similar:
            same_type_count = sum(
                1 for s in similar
                if s.get("error_type") == analysis.error_type.value
            )
            if same_type_count >= 2:
                patterns.append(
                    f"Recurring {analysis.error_type.value} failure "
                    f"({same_type_count} similar incidents)"
                )

        # Same failed jobs
        if analysis.failed_jobs and similar:
            for s in similar:
                similar_jobs = s.get("failed_jobs", [])
                common_jobs = set(analysis.failed_jobs) & set(similar_jobs)
                if common_jobs:
                    patterns.append(f"Jobs {', '.join(common_jobs)} fail frequently")
                    break

        return patterns

    def get_statistics(self) -> Dict[str, Any]:
        """Get learning engine statistics."""
        return {
            "classifier_available": self._classifier is not None,
            "memory_stats": self.memory_router.get_statistics(),
        }
