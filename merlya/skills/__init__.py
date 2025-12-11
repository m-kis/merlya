"""
Merlya Skills - Reusable workflow system.

Skills are structured workflows that can be executed on hosts.
"""

from merlya.skills.executor import SkillExecutor
from merlya.skills.loader import SkillLoader, load_all_skills
from merlya.skills.models import HostResult, SkillConfig, SkillResult, SkillStatus
from merlya.skills.registry import SkillRegistry, get_registry, reset_registry
from merlya.skills.wizard import SkillWizard, generate_skill_template

__all__ = [
    "HostResult",
    "SkillConfig",
    "SkillExecutor",
    "SkillLoader",
    "SkillRegistry",
    "SkillResult",
    "SkillStatus",
    "SkillWizard",
    "generate_skill_template",
    "get_registry",
    "load_all_skills",
    "reset_registry",
]
