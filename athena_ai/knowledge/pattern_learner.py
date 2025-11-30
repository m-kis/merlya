"""
Pattern Learner for Athena.

Learns patterns from:
- Resolved incidents
- Successful commands
- User corrections

Uses these patterns to:
- Recognize similar situations
- Suggest solutions proactively
- Improve over time
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

from .storage_manager import StorageManager


@dataclass
class Pattern:
    """A learned pattern."""
    id: Optional[int] = None
    name: str = ""
    description: str = ""
    symptoms: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    service: str = ""
    environment: str = ""
    suggested_solution: str = ""
    suggested_commands: List[str] = field(default_factory=list)
    times_matched: int = 0
    times_successful: int = 0
    confidence: float = 0.0
    last_matched: str = ""


@dataclass
class PatternMatch:
    """A pattern that matched a situation."""
    pattern: Pattern
    score: float
    matched_keywords: List[str]
    matched_symptoms: List[str]


class PatternLearner:
    """
    Learns and matches patterns for infrastructure incidents.

    Patterns are extracted from:
    1. Resolved incidents with known root causes
    2. Successful command sequences
    3. Manual pattern definitions
    """

    def __init__(self, storage: StorageManager):
        self.storage = storage
        self._patterns: Dict[int, Pattern] = {}
        self._keyword_index: Dict[str, List[int]] = defaultdict(list)
        self._loaded = False

    def _ensure_loaded(self):
        """Load patterns from storage."""
        if self._loaded:
            return

        with self.storage.sqlite._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patterns")

            for row in cursor.fetchall():
                pattern = Pattern(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"] or "",
                    symptoms=self._parse_list(row["symptoms"]),
                    keywords=self._parse_list(row["keywords"]),
                    suggested_solution=row["suggested_solution"] or "",
                    times_matched=row["times_matched"] or 0,
                    last_matched=row["last_matched"] or "",
                )

                # Calculate confidence based on usage
                if pattern.times_matched > 0:
                    pattern.confidence = min(0.9, 0.5 + (pattern.times_matched * 0.1))

                self._patterns[pattern.id] = pattern

                # Build keyword index
                for keyword in pattern.keywords:
                    self._keyword_index[keyword.lower()].append(pattern.id)

        self._loaded = True
        logger.debug(f"PatternLearner loaded {len(self._patterns)} patterns")

    def _parse_list(self, json_str: str) -> List[str]:
        """Parse a JSON list string."""
        if not json_str:
            return []
        try:
            import json
            return json.loads(json_str)
        except Exception:
            return []

    def add_pattern(
        self,
        name: str,
        description: str = "",
        symptoms: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        service: str = "",
        suggested_solution: str = "",
        suggested_commands: Optional[List[str]] = None,
    ) -> int:
        """
        Add a new pattern.

        Returns:
            Pattern ID
        """
        import json

        with self.storage.sqlite._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO patterns
                (name, description, symptoms, keywords, suggested_solution, times_matched)
                VALUES (?, ?, ?, ?, ?, 0)
            """, (
                name,
                description,
                json.dumps(symptoms or []),
                json.dumps(keywords or []),
                suggested_solution,
            ))
            conn.commit()
            pattern_id = cursor.lastrowid

        # Add to memory
        pattern = Pattern(
            id=pattern_id,
            name=name,
            description=description,
            symptoms=symptoms or [],
            keywords=keywords or [],
            service=service,
            suggested_solution=suggested_solution,
            suggested_commands=suggested_commands or [],
            confidence=0.5,
        )
        self._patterns[pattern_id] = pattern

        # Update keyword index
        for keyword in pattern.keywords:
            self._keyword_index[keyword.lower()].append(pattern_id)

        logger.info(f"Added pattern {pattern_id}: {name}")
        return pattern_id

    def learn_from_incident(
        self,
        incident_id: str,
        min_symptom_count: int = 2,
    ) -> Optional[int]:
        """
        Learn a pattern from a resolved incident.

        Only creates a pattern if:
        - Incident has root cause identified
        - Incident has solution
        - Sufficient symptoms to generalize

        Returns:
            Pattern ID if created, None otherwise
        """
        incident = self.storage.get_incident(incident_id)
        if not incident:
            return None

        # Check if incident is suitable for learning
        if incident.get("status") != "resolved":
            logger.debug(f"Incident {incident_id} not resolved, skipping")
            return None

        if not incident.get("root_cause"):
            logger.debug(f"Incident {incident_id} has no root cause, skipping")
            return None

        if not incident.get("solution"):
            logger.debug(f"Incident {incident_id} has no solution, skipping")
            return None

        symptoms = incident.get("symptoms", [])
        if len(symptoms) < min_symptom_count:
            logger.debug(f"Incident {incident_id} has too few symptoms, skipping")
            return None

        # Extract keywords from incident
        keywords = self._extract_keywords(incident)

        # Create pattern
        pattern_name = f"pattern_from_{incident_id}"

        # Check for existing similar pattern
        similar = self.match_patterns(
            text=incident.get("title", ""),
            symptoms=symptoms,
            service=incident.get("service") or "",
        )

        if similar and similar[0].score > 0.7:
            # Update existing pattern instead
            existing = similar[0].pattern
            if existing.id is not None:
                self._update_pattern_stats(existing.id, success=True)
            logger.debug(f"Updated existing pattern {existing.id} instead of creating new")
            return existing.id

        # Create new pattern
        pattern_id = self.add_pattern(
            name=pattern_name,
            description=f"Learned from incident: {incident.get('title', '')}",
            symptoms=symptoms,
            keywords=keywords,
            service=incident.get("service", ""),
            suggested_solution=incident.get("solution", ""),
            suggested_commands=incident.get("commands", []),
        )

        return pattern_id

    def _extract_keywords(self, incident: Dict) -> List[str]:
        """Extract keywords from incident text."""
        keywords = set()

        # From title
        title = incident.get("title", "")
        keywords.update(self._tokenize(title))

        # From description
        description = incident.get("description", "")
        keywords.update(self._tokenize(description))

        # From root cause
        root_cause = incident.get("root_cause", "")
        keywords.update(self._tokenize(root_cause))

        # Add service and environment if present
        service = incident.get("service")
        if service:
            keywords.add(service.lower())

        env = incident.get("environment")
        if env:
            keywords.add(env.lower())

        # Filter common words
        stopwords = {
            "the", "a", "an", "is", "was", "were", "are", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "to", "of", "in", "for", "on", "with", "at",
            "by", "from", "as", "into", "through", "during", "before",
            "after", "above", "below", "between", "under", "again",
            "further", "then", "once", "here", "there", "when", "where",
            "why", "how", "all", "each", "few", "more", "most", "other",
            "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "just", "and", "but", "if",
            "or", "because", "while", "until", "that", "which", "who",
            "this", "these", "those", "it", "its",
        }

        return [k for k in keywords if k not in stopwords and len(k) > 2]

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into keywords."""
        if not text:
            return []
        # Split on non-alphanumeric, lowercase
        tokens = re.findall(r'[a-zA-Z0-9]+', text.lower())
        return tokens

    def match_patterns(
        self,
        text: str = "",
        symptoms: Optional[List[str]] = None,
        service: Optional[str] = None,
        environment: Optional[str] = None,
        min_score: float = 0.3,
        limit: int = 5,
    ) -> List[PatternMatch]:
        """
        Find patterns matching the given situation.

        Returns:
            List of PatternMatch sorted by score
        """
        self._ensure_loaded()

        if not self._patterns:
            return []

        candidates: Dict[int, Dict] = {}  # pattern_id -> match info

        # Match by keywords in text
        if text:
            text_keywords = set(self._tokenize(text))
            for keyword in text_keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in self._keyword_index:
                    for pattern_id in self._keyword_index[keyword_lower]:
                        if pattern_id not in candidates:
                            candidates[pattern_id] = {
                                "score": 0,
                                "keywords": [],
                                "symptoms": [],
                            }
                        candidates[pattern_id]["score"] += 0.15
                        candidates[pattern_id]["keywords"].append(keyword)

        # Match by symptoms
        if symptoms:
            symptom_keywords = set()
            for symptom in symptoms:
                symptom_keywords.update(self._tokenize(symptom))

            for pattern_id, pattern in self._patterns.items():
                pattern_symptom_keywords = set()
                for s in pattern.symptoms:
                    pattern_symptom_keywords.update(self._tokenize(s))

                overlap = symptom_keywords & pattern_symptom_keywords
                if overlap:
                    if pattern_id not in candidates:
                        candidates[pattern_id] = {
                            "score": 0,
                            "keywords": [],
                            "symptoms": [],
                        }
                    # Score based on overlap ratio
                    overlap_score = len(overlap) / max(len(pattern_symptom_keywords), 1)
                    candidates[pattern_id]["score"] += overlap_score * 0.4
                    candidates[pattern_id]["symptoms"].extend(list(overlap)[:3])

        # Match by service
        if service:
            for pattern_id, pattern in self._patterns.items():
                if pattern.service and pattern.service.lower() == service.lower():
                    if pattern_id not in candidates:
                        candidates[pattern_id] = {
                            "score": 0,
                            "keywords": [],
                            "symptoms": [],
                        }
                    candidates[pattern_id]["score"] += 0.2

        # Build results
        results = []
        for pattern_id, match_info in candidates.items():
            if match_info["score"] >= min_score:
                pattern = self._patterns[pattern_id]

                # Boost by pattern confidence
                final_score = match_info["score"] * (0.5 + pattern.confidence * 0.5)

                results.append(PatternMatch(
                    pattern=pattern,
                    score=min(final_score, 1.0),
                    matched_keywords=match_info["keywords"],
                    matched_symptoms=match_info["symptoms"],
                ))

        # Sort by score
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def record_match(self, pattern_id: int, success: bool = True):
        """
        Record that a pattern was matched and whether it helped.

        This improves pattern confidence over time.
        """
        self._update_pattern_stats(pattern_id, success)

    def _update_pattern_stats(self, pattern_id: int, success: bool):
        """Update pattern statistics."""

        with self.storage.sqlite._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE patterns
                SET times_matched = times_matched + 1,
                    last_matched = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), pattern_id))
            conn.commit()

        # Update in memory
        if pattern_id in self._patterns:
            pattern = self._patterns[pattern_id]
            pattern.times_matched += 1
            if success:
                pattern.times_successful += 1
            pattern.last_matched = datetime.now().isoformat()

            # Recalculate confidence
            if pattern.times_matched > 0:
                base_confidence = 0.5 + min(pattern.times_matched * 0.05, 0.3)
                if pattern.times_successful > 0:
                    success_rate = pattern.times_successful / pattern.times_matched
                    pattern.confidence = base_confidence * (0.5 + success_rate * 0.5)
                else:
                    pattern.confidence = base_confidence

    def get_top_patterns(self, limit: int = 10) -> List[Pattern]:
        """Get most frequently matched patterns."""
        self._ensure_loaded()

        patterns = list(self._patterns.values())
        patterns.sort(key=lambda p: p.times_matched, reverse=True)
        return patterns[:limit]

    def suggest_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Get solution suggestion from text.

        Returns:
            Suggestion dict with solution, commands, confidence, pattern
        """
        matches = self.match_patterns(text=text, min_score=0.4, limit=1)

        if not matches:
            return None

        match = matches[0]
        return {
            "solution": match.pattern.suggested_solution,
            "commands": match.pattern.suggested_commands,
            "confidence": match.score,
            "pattern_name": match.pattern.name,
            "pattern_id": match.pattern.id,
            "matched_keywords": match.matched_keywords,
        }

    def export_patterns(self) -> List[Dict]:
        """Export all patterns for backup/review."""
        self._ensure_loaded()

        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "symptoms": p.symptoms,
                "keywords": p.keywords,
                "service": p.service,
                "suggested_solution": p.suggested_solution,
                "times_matched": p.times_matched,
                "confidence": p.confidence,
            }
            for p in self._patterns.values()
        ]
