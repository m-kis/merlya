"""
Merlya Health - Service checks module.

Provides service health checks (parser, session manager).
"""

from __future__ import annotations

from merlya.core.types import CheckStatus, HealthCheck
from merlya.parser.service import ParserService
from merlya.session.manager import SessionManager


async def check_parser_service(tier: str | None = None) -> HealthCheck:
    """Check if Parser service is properly initialized."""
    try:
        # Reset if instance exists with different tier to ensure correct backend
        existing = ParserService._instance
        if existing and tier and existing._tier != tier:
            ParserService.reset_instance()

        # Pass tier to ensure correct backend selection
        parser = ParserService.get_instance(tier=tier)

        # Initialize the backend (required before use)
        await parser.initialize()

        backend_name = type(parser._backend).__name__

        return HealthCheck(
            name="parser",
            status=CheckStatus.OK,
            message=f"✅ Parser service ready ({backend_name})",
            details={
                "backend": backend_name,
                "tier": tier or "auto",
            },
        )
    except Exception as e:
        return HealthCheck(
            name="parser",
            status=CheckStatus.WARNING,
            message=f"⚠️ Parser not initialized: {str(e)[:50]}",
            details={"error": str(e)},
        )


def check_session_manager() -> HealthCheck:
    """Check if Session manager is available."""
    try:
        manager = SessionManager.get_instance()
        if manager is None:
            return HealthCheck(
                name="session",
                status=CheckStatus.WARNING,
                message="⚠️ Session manager not initialized",
                details={"error": "No instance created yet"},
            )

        tier = manager.current_tier.value if manager.current_tier else "auto"
        max_tokens = getattr(manager, "max_tokens", None) or manager.limits.max_tokens

        return HealthCheck(
            name="session",
            status=CheckStatus.OK,
            message=f"✅ Session manager ready (tier={tier})",
            details={
                "tier": tier,
                "max_tokens": max_tokens,
            },
        )
    except Exception as e:
        return HealthCheck(
            name="session",
            status=CheckStatus.WARNING,
            message=f"⚠️ Session manager not initialized: {str(e)[:50]}",
            details={"error": str(e)},
        )
