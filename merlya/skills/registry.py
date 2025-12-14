"""
Merlya Skills - Registry.

Thread-safe singleton registry for managing skills.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.skills.models import SkillConfig

# Constants
MAX_USER_INPUT_LENGTH = 10_000  # 10KB max for intent matching
CONFIDENCE_BOOST = 0.3  # Boost for longer pattern matches
LOG_TRUNCATE_LENGTH = 100  # Max chars in log messages
MIN_PATTERN_SPECIFICITY = 3  # Minimum characters a pattern must match to be useful

# Patterns that are too generic and should be rejected
FORBIDDEN_PATTERNS = frozenset(
    {
        r".*",
        r".+",
        r"^.*$",
        r"^.+$",
        r"[\s\S]*",
        r"[\s\S]+",
    }
)

# Singleton instance with thread-safety
_registry_instance: SkillRegistry | None = None
_registry_lock = threading.Lock()


class SkillRegistry:
    """Thread-safe registry for skills.

    Maintains a collection of registered skills and provides
    lookup by name or intent pattern matching.

    Example:
        >>> registry = get_registry()
        >>> registry.register(skill_config)
        >>> skill = registry.get("disk_audit")
        >>> matched = registry.match_intent("check disk usage on web-01")
    """

    def __init__(self) -> None:
        """Initialize the registry."""
        self._skills: dict[str, SkillConfig] = {}
        self._lock = threading.Lock()
        self._intent_patterns: dict[str, list[re.Pattern[str]]] = {}
        logger.debug("📚 SkillRegistry initialized")

    def register(self, skill: SkillConfig) -> None:
        """
        Register a skill.

        Args:
            skill: Skill configuration to register.

        Raises:
            ValueError: If a skill with the same name is already registered.
        """
        with self._lock:
            if skill.name in self._skills:
                existing = self._skills[skill.name]
                # Allow overwrite if same source or newer version
                if existing.source_path != skill.source_path:
                    logger.warning(
                        f"⚠️ Overwriting skill '{skill.name}' "
                        f"(v{existing.version} -> v{skill.version})"
                    )

            self._skills[skill.name] = skill

            # Compile intent patterns with safety limits
            patterns: list[re.Pattern[str]] = []
            for pattern in skill.intent_patterns:
                # Reject catch-all patterns that would match everything
                if pattern in FORBIDDEN_PATTERNS:
                    logger.warning(
                        f"⚠️ Rejecting catch-all pattern '{pattern}' in skill '{skill.name}' - "
                        "use specific patterns like 'git.*flow' instead of '.*'"
                    )
                    continue

                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                    patterns.append(compiled)
                except re.error as e:
                    # Truncate pattern in log for safety
                    safe_pattern = (
                        pattern[:LOG_TRUNCATE_LENGTH] + "..."
                        if len(pattern) > LOG_TRUNCATE_LENGTH
                        else pattern
                    )
                    logger.warning(
                        f"⚠️ Invalid pattern '{safe_pattern}' in skill '{skill.name}': {e}"
                    )

            self._intent_patterns[skill.name] = patterns

            logger.debug(f"📚 Registered skill: {skill.name} v{skill.version}")

    def unregister(self, name: str) -> bool:
        """
        Unregister a skill by name.

        Args:
            name: Skill name to remove.

        Returns:
            True if the skill was removed, False if not found.
        """
        with self._lock:
            if name in self._skills:
                del self._skills[name]
                del self._intent_patterns[name]
                logger.debug(f"📚 Unregistered skill: {name}")
                return True
            return False

    def get(self, name: str) -> SkillConfig | None:
        """
        Get a skill by name.

        Args:
            name: Skill name.

        Returns:
            SkillConfig or None if not found.
        """
        with self._lock:
            return self._skills.get(name)

    def get_all(self) -> list[SkillConfig]:
        """
        Get all registered skills.

        Returns:
            List of all skill configurations.
        """
        with self._lock:
            return list(self._skills.values())

    def get_builtin(self) -> list[SkillConfig]:
        """
        Get all builtin skills.

        Returns:
            List of builtin skill configurations.
        """
        with self._lock:
            return [s for s in self._skills.values() if s.builtin]

    def get_user(self) -> list[SkillConfig]:
        """
        Get all user-defined skills.

        Returns:
            List of user skill configurations.
        """
        with self._lock:
            return [s for s in self._skills.values() if not s.builtin]

    def match_intent(self, user_input: str) -> list[tuple[SkillConfig, float]]:
        """
        Match user input against skill intent patterns.

        Args:
            user_input: User message to match (truncated if > 10KB).

        Returns:
            List of (skill, confidence) tuples, sorted by confidence descending.
        """
        # Validate and truncate input
        if not user_input:
            return []

        safe_input = user_input
        if len(user_input) > MAX_USER_INPUT_LENGTH:
            logger.warning(f"⚠️ Input too long for matching ({len(user_input)} chars), truncating")
            safe_input = user_input[:MAX_USER_INPUT_LENGTH]

        # Copy data under lock, then release for matching
        with self._lock:
            skills_copy = dict(self._skills)
            patterns_copy = dict(self._intent_patterns)

        matches: list[tuple[SkillConfig, float]] = []

        for name, patterns in patterns_copy.items():
            skill = skills_copy[name]
            max_confidence = 0.0

            for pattern in patterns:
                try:
                    match = pattern.search(safe_input)
                    if match:
                        match_len = len(match.group())
                        # Reject matches that are too short/generic
                        if match_len < MIN_PATTERN_SPECIFICITY:
                            continue

                        # Calculate confidence based on match length relative to input
                        input_len = len(safe_input.strip())
                        if input_len > 0:
                            confidence = min(match_len / input_len, 1.0)
                            # Boost confidence for longer matches
                            confidence = min(confidence + CONFIDENCE_BOOST, 1.0)
                            max_confidence = max(max_confidence, confidence)
                except (re.error, RuntimeError) as e:
                    logger.warning(f"⚠️ Pattern matching error for '{name}': {e}")
                    continue

            if max_confidence > 0:
                matches.append((skill, max_confidence))

        # Sort by confidence descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def find_by_tag(self, tag: str) -> list[SkillConfig]:
        """
        Find skills by tag.

        Args:
            tag: Tag to search for.

        Returns:
            List of matching skills.
        """
        tag_lower = tag.lower()
        with self._lock:
            return [s for s in self._skills.values() if tag_lower in [t.lower() for t in s.tags]]

    def has(self, name: str) -> bool:
        """
        Check if a skill is registered.

        Args:
            name: Skill name.

        Returns:
            True if registered.
        """
        with self._lock:
            return name in self._skills

    def count(self) -> int:
        """
        Get the number of registered skills.

        Returns:
            Number of skills.
        """
        with self._lock:
            return len(self._skills)

    def clear(self) -> None:
        """Clear all registered skills (mainly for testing)."""
        with self._lock:
            self._skills.clear()
            self._intent_patterns.clear()
            logger.debug("📚 Registry cleared")

    def get_stats(self) -> dict[str, int]:
        """
        Get registry statistics.

        Returns:
            Dictionary with stats.
        """
        with self._lock:
            total = len(self._skills)
            builtin = sum(1 for s in self._skills.values() if s.builtin)
            user_defined = total - builtin
            return {
                "total": total,
                "builtin": builtin,
                "user": user_defined,
                # Backward/forward compatibility keys used by health checks and UI.
                "user_defined": user_defined,
                "enabled": total,  # no per-skill disable flag yet
                "loaded": 1 if total > 0 else 0,
            }


def get_registry() -> SkillRegistry:
    """
    Get the global skill registry singleton (thread-safe).

    Returns:
        SkillRegistry instance.
    """
    global _registry_instance

    # Double-checked locking pattern
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = SkillRegistry()

    return _registry_instance


def reset_registry() -> None:
    """Reset the registry singleton (for testing)."""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
