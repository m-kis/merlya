"""
Merlya Health - Startup checks module.

Provides startup health checks orchestration.
"""

from __future__ import annotations

import asyncio

from merlya.core.types import CheckStatus, HealthCheck

from .startup_health import StartupHealth


async def run_startup_checks(
    include_optional: bool = True,
    tier: str | None = None,
) -> StartupHealth:
    """
    Run all startup health checks and return overall status.

    This is a CRITICAL function: if it returns ERROR status, Merlya should not start
    unless --force-startup is used.

    The check order is designed to fail fast on critical infrastructure issues
    (RAM/disk) before checking more complex services.

    Args:
        include_optional: Run optional checks too (connectivity, etc.).
        tier: Tier override for checks that support it.

    Returns:
        StartupHealth object with check results and overall status.
    """
    # Import all check functions locally to avoid import issues
    from merlya.health.connectivity import check_llm_provider
    from merlya.health.infrastructure import check_keyring, check_ssh_available
    from merlya.health.mcp_checks import check_mcp_servers
    from merlya.health.service_checks import check_parser_service, check_session_manager
    from merlya.health.system_checks import check_disk_space, check_ram

    results: list[HealthCheck] = []
    model_tier = None

    # 1. CRITICAL: System resources first (fast failures)
    # This should run in a tight loop to avoid expensive checks if resources are insufficient
    logger = None
    try:
        from loguru import logger as loguru_logger

        logger = loguru_logger
    except ImportError:
        pass

    ram_check, model_tier = check_ram()
    effective_tier = tier or model_tier
    # `check_ram()` may return "llm_fallback" for extremely constrained environments.
    # Tiered local components (parser/router ONNX) should treat that as lightweight.
    if effective_tier == "llm_fallback":
        effective_tier = "lightweight"
    results.append(ram_check)
    results.append(check_disk_space())

    # Stop if critical system checks failed
    critical_errors = [r for r in results if r.status == CheckStatus.ERROR]
    if critical_errors and logger:
        for check in critical_errors:
            logger.error(f"❌ Critical startup check failed: {check.name} - {check.message}")

    # 2. REQUIRED: Infrastructure checks
    results.append(check_ssh_available())
    results.append(check_keyring())

    # 3. OPTIONAL: Services and connectivity
    if include_optional:
        # Run async checks concurrently
        try:
            service_results = await asyncio.gather(
                check_parser_service(effective_tier),
                check_llm_provider(timeout=5.0),  # Short timeout for startup
                return_exceptions=True,
            )
            for result in service_results:
                if isinstance(result, BaseException):
                    if logger:
                        logger.warning(f"⚠️ Optional check failed with exception: {result}")
                    results.append(
                        HealthCheck(
                            name="startup_optional",
                            status=CheckStatus.WARNING,
                            message=f"⚠️ Optional check failed: {str(result)[:50]}",
                            details={"error": str(result)},
                        )
                    )
                else:
                    results.append(result)
        except Exception as e:
            if logger:
                logger.warning(f"⚠️ Optional checks failed: {e}")

        # Add sync checks separately
        results.append(check_session_manager())
        results.append(check_mcp_servers(effective_tier))

        # Note: ONNX model check removed - Orchestrator doesn't need ONNX

    return StartupHealth(checks=results, model_tier=model_tier)
