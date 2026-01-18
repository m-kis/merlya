"""
Center integration for the orchestrator.

Contains functions for registering and converting center results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from .models import DelegationResult

if TYPE_CHECKING:
    from merlya.centers.base import CenterResult
    from merlya.core.context import SharedContext


def ensure_centers_registered(
    registry: object,
    ctx: SharedContext,
) -> None:
    """
    Ensure centers are registered in the registry.

    This follows the OCP principle - new centers can be added without
    modifying the delegation tools.

    Args:
        registry: The CenterRegistry instance.
        ctx: SharedContext to use for center instantiation.
    """
    from merlya.centers.base import CenterMode
    from merlya.centers.change import ChangeCenter
    from merlya.centers.diagnostic import DiagnosticCenter
    from merlya.centers.registry import CenterRegistry

    # Type narrowing for mypy
    if not isinstance(registry, CenterRegistry):
        return

    # Set context (clears instances if changed)
    registry.set_context(ctx)

    # Register centers if not already registered
    if not registry.is_registered(CenterMode.DIAGNOSTIC):
        registry.register(CenterMode.DIAGNOSTIC, DiagnosticCenter)
        logger.debug("Registered DiagnosticCenter")

    if not registry.is_registered(CenterMode.CHANGE):
        registry.register(CenterMode.CHANGE, ChangeCenter)
        logger.debug("Registered ChangeCenter")


def convert_center_result(result: CenterResult, specialist: str) -> DelegationResult:
    """
    Convert a CenterResult to a DelegationResult.

    Args:
        result: CenterResult from a Center execution.
        specialist: Name of the specialist/center.

    Returns:
        DelegationResult for orchestrator consumption.
    """
    # Build output message with context
    output_parts = [result.message]

    if result.data:
        # Include the specialist agent's output (most important for user)
        agent_output = result.data.get("output")
        if agent_output:
            output_parts.append(f"\n{agent_output}")

        # Add relevant metadata
        evidence = result.data.get("evidence")
        if evidence and isinstance(evidence, list):
            output_parts.append(f"\nEvidence collected: {len(evidence)} items")
        if result.data.get("pipeline"):
            output_parts.append(f"\nPipeline: {result.data['pipeline']}")
        if result.data.get("hitl_approved") is not None:
            status = "approved" if result.data["hitl_approved"] else "declined"
            output_parts.append(f"\nHITL: {status}")

        # Include error if present
        if result.data.get("error"):
            output_parts.append(f"\nError: {result.data['error']}")

    return DelegationResult(
        success=result.success,
        output="\n".join(output_parts),
        specialist=specialist,
        complete=result.success,
    )
