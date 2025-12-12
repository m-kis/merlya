"""
Merlya Parser - Incident extractor.

High-level incident extraction with confidence checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.parser.service import ParserService

if TYPE_CHECKING:
    from merlya.parser.models import IncidentInput, IncidentParsingResult


async def extract_incident(
    text: str,
    min_confidence: float = 0.5,
    tier: str | None = None,
) -> tuple[IncidentInput | None, IncidentParsingResult]:
    """
    Extract incident information from text.

    Args:
        text: Raw incident description.
        min_confidence: Minimum confidence threshold.
        tier: Optional tier override.

    Returns:
        Tuple of (IncidentInput if confident, full result).

    Example:
        incident, result = await extract_incident(
            "Production web-01 is down, OOM errors in logs",
            min_confidence=0.6
        )
        if incident:
            print(f"Hosts: {incident.affected_hosts}")
            print(f"Severity: {incident.severity}")
        else:
            print(f"Low confidence ({result.confidence}), need clarification")
    """
    service = ParserService.get_instance(tier=tier)
    if not service.is_initialized:
        await service.initialize()

    result = await service.parse_incident(text)

    if result.confidence >= min_confidence:
        logger.debug(
            f"✅ Incident extracted (confidence={result.confidence:.2f}): "
            f"{len(result.incident.affected_hosts)} hosts, "
            f"severity={result.incident.severity}"
        )
        return result.incident, result

    logger.debug(f"⚠️ Low confidence incident parsing ({result.confidence:.2f} < {min_confidence})")
    return None, result


async def is_incident_text(text: str, threshold: float = 0.4) -> bool:
    """
    Quick check if text appears to be an incident description.

    Args:
        text: Text to check.
        threshold: Confidence threshold.

    Returns:
        True if text looks like an incident.
    """
    service = ParserService.get_instance()
    if not service.is_initialized:
        await service.initialize()

    result = await service.parse_incident(text)

    # Check for incident indicators
    has_errors = len(result.incident.error_messages) > 0
    has_symptoms = len(result.incident.symptoms) > 0
    has_hosts = len(result.incident.affected_hosts) > 0

    # Require minimum confidence even when indicators are present
    # Indicators can lower the threshold but not bypass it entirely
    min_confidence = threshold * 0.5  # Allow half the threshold if strong indicators
    has_strong_indicators = has_errors or (has_symptoms and has_hosts)

    if result.confidence >= threshold:
        return True
    return bool(has_strong_indicators and result.confidence >= min_confidence)
