"""
Incident Memory for Athena.

Provides:
- Incident recording and retrieval
- Pattern extraction from incidents
- Similar incident matching
- Learning from resolutions
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from athena_ai.utils.logger import logger

from .storage_manager import StorageManager


@dataclass
class Incident:
    """An infrastructure incident."""
    id: str
    title: str
    priority: str  # P0, P1, P2, P3
    status: str = "open"  # open, investigating, resolved, closed
    description: str = ""
    environment: str = ""
    service: str = ""
    host: str = ""
    symptoms: List[str] = field(default_factory=list)
    root_cause: str = ""
    solution: str = ""
    commands_executed: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    resolved_at: str = ""
    ttd: int = 0  # Time to detect (seconds)
    ttr: int = 0  # Time to resolve (seconds)


@dataclass
class SimilarityMatch:
    """A similar incident match."""
    incident: Incident
    score: float
    matching_features: List[str]


class IncidentMemory:
    """
    Memory system for incidents.

    Learns from past incidents to:
    - Find similar past incidents
    - Suggest solutions based on history
    - Track patterns over time
    """

    def __init__(self, storage: StorageManager):
        self.storage = storage
        self._symptom_index: Dict[str, List[str]] = {}  # symptom -> incident_ids
        self._service_index: Dict[str, List[str]] = {}  # service -> incident_ids
        self._loaded = False

    def _ensure_loaded(self):
        """Ensure indexes are loaded from storage."""
        if self._loaded:
            return

        # Load existing incidents and build indexes
        incidents = self.storage.find_similar_incidents(limit=1000)
        for inc in incidents:
            inc_id = inc.get("id", "")
            if not inc_id:
                continue

            # Index symptoms
            for symptom in inc.get("symptoms", []):
                symptom_key = self._normalize_symptom(symptom)
                if symptom_key not in self._symptom_index:
                    self._symptom_index[symptom_key] = []
                self._symptom_index[symptom_key].append(inc_id)

            # Index service
            service = inc.get("service", "")
            if service:
                if service not in self._service_index:
                    self._service_index[service] = []
                self._service_index[service].append(inc_id)

        self._loaded = True
        logger.debug(f"IncidentMemory loaded {len(incidents)} incidents")

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

        Returns:
            Incident ID
        """
        incident_id = self.storage.store_incident({
            "title": title,
            "priority": priority,
            "description": description,
            "environment": environment,
            "service": service,
            "host": host,
            "symptoms": symptoms or [],
            "tags": tags or [],
            "status": "open",
        })

        # Update indexes
        for symptom in (symptoms or []):
            symptom_key = self._normalize_symptom(symptom)
            if symptom_key not in self._symptom_index:
                self._symptom_index[symptom_key] = []
            self._symptom_index[symptom_key].append(incident_id)

        if service:
            if service not in self._service_index:
                self._service_index[service] = []
            self._service_index[service].append(incident_id)

        logger.info(f"Recorded incident {incident_id}: {title}")
        return incident_id

    def resolve_incident(
        self,
        incident_id: str,
        root_cause: str,
        solution: str,
        commands_executed: List[str] = None,
    ) -> bool:
        """
        Mark an incident as resolved and record the solution.

        This information is crucial for learning.
        """
        incident = self.storage.get_incident(incident_id)
        if not incident:
            logger.warning(f"Incident {incident_id} not found")
            return False

        # Calculate TTR
        created_at = incident.get("created_at", "")
        ttr = 0
        if created_at:
            try:
                start = datetime.fromisoformat(created_at)
                ttr = int((datetime.now() - start).total_seconds())
            except (ValueError, TypeError):
                pass

        # Update incident
        import json
        with self.storage._sqlite_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE incidents
                SET status = 'resolved',
                    resolved_at = ?,
                    root_cause = ?,
                    solution = ?,
                    commands = ?
                WHERE id = ?
            """, (
                datetime.now().isoformat(),
                root_cause,
                solution,
                json.dumps(commands_executed or []),
                incident_id,
            ))
            conn.commit()

        logger.info(f"Resolved incident {incident_id} (TTR: {ttr}s)")
        return True

    def find_similar(
        self,
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
        title: str = None,
        limit: int = 5,
    ) -> List[SimilarityMatch]:
        """
        Find similar past incidents.

        Uses multiple signals:
        - Symptom overlap
        - Same service
        - Same environment
        - Title/description similarity
        """
        self._ensure_loaded()

        candidates: Dict[str, float] = {}
        matching_features: Dict[str, List[str]] = {}

        # Score by symptom matches
        if symptoms:
            for symptom in symptoms:
                symptom_key = self._normalize_symptom(symptom)
                if symptom_key in self._symptom_index:
                    for inc_id in self._symptom_index[symptom_key]:
                        candidates[inc_id] = candidates.get(inc_id, 0) + 0.3
                        if inc_id not in matching_features:
                            matching_features[inc_id] = []
                        matching_features[inc_id].append(f"symptom:{symptom_key}")

        # Score by service match
        if service and service in self._service_index:
            for inc_id in self._service_index[service]:
                candidates[inc_id] = candidates.get(inc_id, 0) + 0.25
                if inc_id not in matching_features:
                    matching_features[inc_id] = []
                matching_features[inc_id].append(f"service:{service}")

        # Get full incident data for top candidates
        sorted_candidates = sorted(
            candidates.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit * 2]  # Get more than needed, filter later

        results = []
        for inc_id, score in sorted_candidates:
            incident_data = self.storage.get_incident(inc_id)
            if incident_data and incident_data.get("status") == "resolved":
                # Bonus for same environment
                if environment and incident_data.get("environment") == environment:
                    score += 0.15
                    matching_features.setdefault(inc_id, []).append(f"env:{environment}")

                incident = Incident(
                    id=incident_data.get("id", ""),
                    title=incident_data.get("title", ""),
                    priority=incident_data.get("priority", "P3"),
                    status=incident_data.get("status", "resolved"),
                    description=incident_data.get("description", ""),
                    environment=incident_data.get("environment", ""),
                    service=incident_data.get("service", ""),
                    host=incident_data.get("host", ""),
                    symptoms=incident_data.get("symptoms", []),
                    root_cause=incident_data.get("root_cause", ""),
                    solution=incident_data.get("solution", ""),
                )

                results.append(SimilarityMatch(
                    incident=incident,
                    score=min(score, 1.0),  # Cap at 1.0
                    matching_features=matching_features.get(inc_id, []),
                ))

        # Sort and limit
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def suggest_solution(
        self,
        symptoms: List[str] = None,
        service: str = None,
        environment: str = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Suggest a solution based on similar past incidents.

        Returns:
            Dict with suggested solution, confidence, and source incident
        """
        similar = self.find_similar(
            symptoms=symptoms,
            service=service,
            environment=environment,
            limit=3,
        )

        if not similar:
            return None

        # Take the best match with a solution
        for match in similar:
            if match.incident.solution and match.score >= 0.3:
                return {
                    "solution": match.incident.solution,
                    "root_cause": match.incident.root_cause,
                    "commands": match.incident.commands_executed,
                    "confidence": match.score,
                    "source_incident": match.incident.id,
                    "source_title": match.incident.title,
                    "matching_features": match.matching_features,
                }

        return None

    def _normalize_symptom(self, symptom: str) -> str:
        """Normalize a symptom string for indexing."""
        # Lowercase, remove numbers, normalize whitespace
        normalized = symptom.lower()
        normalized = re.sub(r'\d+', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    def get_common_symptoms(self, service: str = None, limit: int = 10) -> List[Tuple[str, int]]:
        """
        Get the most common symptoms.

        Returns:
            List of (symptom, count) tuples
        """
        self._ensure_loaded()

        symptom_counts = Counter()

        if service and service in self._service_index:
            # Only count symptoms from incidents with this service
            for inc_id in self._service_index[service]:
                incident = self.storage.get_incident(inc_id)
                if incident:
                    for symptom in incident.get("symptoms", []):
                        symptom_counts[self._normalize_symptom(symptom)] += 1
        else:
            # Count all symptoms
            for symptom_key, incident_ids in self._symptom_index.items():
                symptom_counts[symptom_key] = len(incident_ids)

        return symptom_counts.most_common(limit)

    def get_resolution_stats(self, service: str = None) -> Dict[str, Any]:
        """Get resolution statistics."""
        with self.storage._sqlite_connection() as conn:
            cursor = conn.cursor()

            if service:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved,
                        AVG(CASE WHEN root_cause IS NOT NULL THEN 1 ELSE 0 END) as has_root_cause
                    FROM incidents
                    WHERE service = ?
                """, (service,))
            else:
                cursor.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) as resolved,
                        AVG(CASE WHEN root_cause IS NOT NULL THEN 1 ELSE 0 END) as has_root_cause
                    FROM incidents
                """)

            row = cursor.fetchone()
            return {
                "total_incidents": row[0] or 0,
                "resolved": row[1] or 0,
                "resolution_rate": (row[1] or 0) / max(row[0] or 1, 1),
                "has_root_cause_rate": row[2] or 0,
            }
