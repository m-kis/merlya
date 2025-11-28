"""
Relation Classifier LLM Logic.
"""

import json
import re
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger

from .models import RelationSuggestion


class LLMRelationExtractor:
    """LLM-based relation discovery."""

    RELATION_TYPES = [
        "cluster_member",
        "database_replica",
        "depends_on",
        "backup_of",
        "load_balanced",
        "related_service",
    ]

    # Maximum response length to parse (100KB) - prevents DoS from huge LLM responses
    _MAX_PARSE_LENGTH = 100_000

    def __init__(self, llm_router: Any):
        """Initialize with LLM router."""
        self.llm = llm_router

    def extract_relations(self, hosts: List[Dict]) -> List[RelationSuggestion]:
        """Use LLM to discover complex relations."""
        suggestions = []

        if not self.llm:
            return suggestions

        # Build map of lowercase -> original hostname for preserving casing
        original_hostnames: Dict[str, str] = {}
        for host in hosts:
            hostname = host.get("hostname", "")
            if hostname:
                original_hostnames[hostname.lower()] = hostname

        # Prepare host summary for LLM
        host_summary = []
        for host in hosts[:50]:  # Limit to 50 hosts
            entry = host.get("hostname", "")
            if host.get("environment"):
                entry += f" (env: {host['environment']})"
            if host.get("groups"):
                entry += f" (groups: {', '.join(host['groups'][:3])})"
            if host.get("service"):
                entry += f" (service: {host['service']})"
            host_summary.append(entry)

        prompt = f"""Analyze these server hostnames and suggest relationships between them.

Hostnames:
{chr(10).join(host_summary)}

For each relationship, identify:
1. Source hostname
2. Target hostname
3. Relationship type: cluster_member, database_replica, depends_on, backup_of, load_balanced, related_service
4. Confidence (0.5-1.0)
5. Reason

Return ONLY a JSON array with objects containing: source, target, type, confidence, reason

Example:
[{{"source": "web-01", "target": "web-02", "type": "cluster_member", "confidence": 0.8, "reason": "Same naming pattern"}}]

Return ONLY valid JSON, no explanations. Return empty array [] if no clear relationships found."""

        try:
            response = self.llm.generate(prompt, task="synthesis")

            # Parse JSON from response using robust extraction
            data = self._extract_json_array(response)
            if data is not None:
                for item in data:
                    if isinstance(item, dict) and item.get("source") and item.get("target"):
                        # Validate relation_type against allowed types
                        relation_type = item.get("type", "related_service")
                        if relation_type not in self.RELATION_TYPES:
                            logger.debug(f"Invalid relation type from LLM: {relation_type}, defaulting to related_service")
                            relation_type = "related_service"
                        # Preserve original hostname casing using the map
                        source = item["source"]
                        target = item["target"]

                        # Skip suggestions for non-existent hosts (LLM hallucination guard)
                        if source.lower() not in original_hostnames or target.lower() not in original_hostnames:
                            logger.debug(f"Skipping LLM suggestion with non-existent host: {source} -> {target}")
                            continue

                        source_hostname = original_hostnames[source.lower()]
                        target_hostname = original_hostnames[target.lower()]

                        # Parse confidence safely (LLM may return non-numeric values)
                        try:
                            raw_conf = float(item.get("confidence", 0.5))
                            confidence = max(0.0, min(raw_conf, 0.75))  # Clamp to [0, 0.75]
                        except (ValueError, TypeError):
                            confidence = 0.5

                        suggestions.append(RelationSuggestion(
                            source_hostname=source_hostname,
                            target_hostname=target_hostname,
                            relation_type=relation_type,
                            confidence=confidence,
                            reason=item.get("reason", "LLM suggestion"),
                            metadata={"source": "llm"},
                        ))

        except Exception as e:
            logger.debug(f"LLM relation discovery failed: {e}")

        return suggestions

    def _extract_json_array(self, response: str) -> Optional[List[Any]]:
        """Extract a JSON array from LLM response with robust parsing.

        Tries multiple strategies:
        1. Parse entire response as JSON
        2. Find and parse the first valid JSON array using bracket matching
        3. Use regex as fallback with validation

        Returns None if no valid JSON array found.
        """
        response = response.strip()

        # Limit response length to prevent DoS
        if len(response) > self._MAX_PARSE_LENGTH:
            logger.warning(
                f"LLM response too long ({len(response)} bytes), truncating to {self._MAX_PARSE_LENGTH}. "
                "Some relation suggestions may be lost."
            )
            # Truncate at last complete JSON object to preserve structure
            truncated = response[:self._MAX_PARSE_LENGTH]
            last_brace = truncated.rfind('}')
            if last_brace > self._MAX_PARSE_LENGTH * 0.8:
                response = truncated[:last_brace + 1] + ']'
            else:
                response = truncated

        # Strategy 1: Try parsing entire response as JSON
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # Strategy 2: Find first '[' and parse from there using bracket matching
        start_idx = response.find('[')
        if start_idx != -1:
            # Find matching closing bracket using stack-based matching
            depth = 0
            in_string = False
            escape_next = False

            for i, char in enumerate(response[start_idx:], start=start_idx):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\' and in_string:
                    escape_next = True
                    continue
                if char == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue

                if char == '[':
                    depth += 1
                elif char == ']':
                    depth -= 1
                    if depth == 0:
                        # Found matching bracket
                        candidate = response[start_idx:i + 1]
                        try:
                            data = json.loads(candidate)
                            if isinstance(data, list):
                                return data
                        except json.JSONDecodeError:
                            pass
                        break

        # Strategy 3: Regex fallback - find all potential arrays and try each
        # Limit iterations to prevent O(n²) DoS on pathological input
        MAX_BRACKET_SEARCHES = 50  # Stop after checking this many '[' positions
        MAX_END_SEARCHES_PER_BRACKET = 100  # Limit ']' searches per '[' position

        bracket_count = 0
        for match in re.finditer(r'\[', response):
            bracket_count += 1
            if bracket_count > MAX_BRACKET_SEARCHES:
                logger.debug(
                    f"Too many brackets ({bracket_count}) in response, stopping JSON extraction"
                )
                break

            start = match.start()
            # Try increasingly longer substrings, but with a limit
            end_searches = 0
            for end in range(start + 2, len(response) + 1):
                if response[end - 1] == ']':
                    end_searches += 1
                    if end_searches > MAX_END_SEARCHES_PER_BRACKET:
                        break  # Move to next '[' position

                    candidate = response[start:end]
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, list):
                            return data
                    except json.JSONDecodeError:
                        continue

        logger.debug("Failed to extract valid JSON array from LLM response")
        return None
