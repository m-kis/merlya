"""
Merlya Health - Skill checks module.

Provides skills registry health checks.
"""

from __future__ import annotations

from merlya.core.types import CheckStatus, HealthCheck
from merlya.skills.registry import get_registry as get_skills_registry


def check_skills_registry(tier: str | None = None) -> HealthCheck:
    """Check if Skills registry is properly initialized and populated."""
    try:
        registry = get_skills_registry()
        stats = registry.get_stats()

        total = stats.get("total", 0)
        enabled = stats.get("enabled", 0)

        if total == 0:
            return HealthCheck(
                name="skills",
                status=CheckStatus.WARNING,
                message="⚠️ No skills loaded (registry empty)",
                details={"stats": stats},
            )

        # Check if registry has been loaded with files
        loaded = stats.get("loaded", False)

        if not loaded:
            return HealthCheck(
                name="skills",
                status=CheckStatus.WARNING,
                message=f"⚠️ Skills registry loaded but skills not parsed ({total} skills found)",
                details={"stats": stats},
            )

        message = f"✅ Skills registry ready ({enabled}/{total} enabled)"

        return HealthCheck(
            name="skills",
            status=CheckStatus.OK,
            message=message,
            details={
                "stats": stats,
                "tier": tier or "auto",
            },
        )

    except Exception as e:
        return HealthCheck(
            name="skills",
            status=CheckStatus.WARNING,
            message=f"⚠️ Skills registry error: {str(e)[:50]}",
            details={"error": str(e)},
        )
