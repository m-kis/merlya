"""
Persistent store for "Skills" - learned problem-solution pairs.
Allows Athena to remember how to solve specific problems and recall them later.
"""
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from athena_ai.utils.logger import logger


@dataclass
class Skill:
    trigger: str          # The problem or question (e.g., "how to restart mongo")
    solution: str         # The solution or command (e.g., "systemctl restart mongod")
    context: str = ""     # Optional context (e.g., "production", "linux")
    created_at: float = 0.0
    usage_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Skill':
        return cls(**data)


class SkillStore:
    """
    Persistent storage for learned skills.

    Structure:
    {
        "skills": [
            {
                "trigger": "restart mongo",
                "solution": "sudo systemctl restart mongod",
                "context": "linux",
                "created_at": 1234567890,
                "usage_count": 5
            }
        ]
    }
    """

    def __init__(self, storage_path: str = "~/.athena/skills.json"):
        self.storage_path = os.path.expanduser(storage_path)
        self.skills: List[Skill] = []
        self._load_data()

    def _load_data(self):
        """Load skills from disk."""
        if not os.path.exists(self.storage_path):
            self.skills = []
            return

        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                self.skills = [Skill.from_dict(s) for s in data.get("skills", [])]
            logger.debug(f"Loaded {len(self.skills)} skills from {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to load skill store: {e}")
            self.skills = []

    def _save_data(self):
        """Save skills to disk."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            data = {
                "skills": [s.to_dict() for s in self.skills]
            }

            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save skill store: {e}")

    def add_skill(self, trigger: str, solution: str, context: str = ""):
        """
        Add a new skill.

        Args:
            trigger: The problem or question
            solution: The solution
            context: Optional context tags
        """
        # Check for duplicates (simple exact match on trigger for now)
        for skill in self.skills:
            if skill.trigger.lower() == trigger.lower():
                # Update existing
                skill.solution = solution
                skill.context = context
                skill.created_at = time.time()
                self._save_data()
                logger.info(f"Updated skill: {trigger}")
                return

        # Create new
        new_skill = Skill(
            trigger=trigger,
            solution=solution,
            context=context,
            created_at=time.time(),
            usage_count=0
        )
        self.skills.append(new_skill)
        self._save_data()
        logger.info(f"Learned new skill: {trigger}")

    def search_skills(self, query: str, limit: int = 3) -> List[Skill]:
        """
        Search for skills matching the query.
        Uses simple keyword matching for MVP.

        Args:
            query: User query
            limit: Max results

        Returns:
            List of matching skills
        """
        query_lower = query.lower()
        matches = []

        for skill in self.skills:
            # Simple scoring: count matching words
            score = 0
            trigger_lower = skill.trigger.lower()

            # Exact match bonus
            if query_lower in trigger_lower:
                score += 10

            # Word match
            query_words = set(query_lower.split())
            trigger_words = set(trigger_lower.split())
            common = query_words.intersection(trigger_words)
            score += len(common)

            if score > 0:
                matches.append((score, skill))

        # Sort by score desc
        matches.sort(key=lambda x: x[0], reverse=True)

        # Return top N skills
        return [m[1] for m in matches[:limit]]

    def get_skill_summary(self, query: str) -> str:
        """Get a formatted summary of relevant skills for a query."""
        skills = self.search_skills(query)
        if not skills:
            return ""

        lines = ["🧠 RELEVANT SKILLS:"]
        for skill in skills:
            lines.append(f"  • When '{skill.trigger}': {skill.solution}")
            # Increment usage on recall
            skill.usage_count += 1

        # Save usage counts occasionally? For now, save on every recall might be too much IO.
        # Let's save only if we found something useful.
        self._save_data()

        return "\n".join(lines)
