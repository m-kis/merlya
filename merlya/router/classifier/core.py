"""
Merlya Router - Core classification logic.

Contains the core classification and routing logic for IntentRouter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.router.intent_classifier import AgentMode
from merlya.router.models import RouterResult

from .heuristic import detect_jump_host
from .llm_classifier import (
    classify_with_llm,
    match_skill_embeddings,
    match_skill_with_llm,
)

if TYPE_CHECKING:
    from merlya.router.intent_classifier import IntentClassifier
    from merlya.router.smart_extractor import SmartExtractor


async def classify_input(
    text: str,
    smart_extractor: SmartExtractor | None,
    classifier: IntentClassifier,
) -> RouterResult:
    """
    Classify user input using SmartExtractor (fast LLM) or pattern matching fallback.

    Args:
        text: User input text.
        smart_extractor: SmartExtractor instance (or None).
        classifier: IntentClassifier for fallback.

    Returns:
        RouterResult with mode, tools, and entities.
    """
    text_lower = text.lower()

    # Try SmartExtractor first (fast LLM for semantic understanding)
    if smart_extractor:
        try:
            extraction = await smart_extractor.extract(text)

            # Convert SmartExtractor result to RouterResult format
            entities: dict[str, list[str]] = {}
            if extraction.entities.hosts:
                entities["hosts"] = extraction.entities.hosts
            if extraction.entities.services:
                entities["services"] = extraction.entities.services
            if extraction.entities.paths:
                entities["paths"] = extraction.entities.paths
            if extraction.entities.ports:
                entities["ports"] = [str(p) for p in extraction.entities.ports]

            # Map center classification to AgentMode
            center = extraction.intent.center.upper()
            if center == "CHANGE":
                mode = AgentMode.REMEDIATION
            elif center == "DIAGNOSTIC":
                mode = AgentMode.DIAGNOSTIC
            else:
                mode = AgentMode.QUERY

            confidence = extraction.intent.confidence

            # Jump host from extraction or fallback to regex
            jump_host = extraction.entities.jump_host or detect_jump_host(text)

            # Determine tools based on entities
            tools = classifier.determine_tools(text_lower, entities)

            # Check for delegation
            delegate_to = classifier.check_delegation(text_lower)

            logger.debug(
                f"SmartExtractor: mode={mode.value}, hosts={entities.get('hosts', [])}, "
                f"confidence={confidence:.2f}"
            )

            return RouterResult(
                mode=mode,
                tools=tools,
                entities=entities,
                confidence=confidence,
                delegate_to=delegate_to,
                jump_host=jump_host,
            )

        except Exception as e:
            logger.warning(f"SmartExtractor failed, falling back to regex: {e}")

    # Fallback: Extract entities using regex
    entities = classifier.extract_entities(text)

    # Detect jump host from patterns
    jump_host = detect_jump_host(text)
    if jump_host:
        logger.debug(f"Detected jump host: {jump_host}")

    # Try embedding-based classification (deprecated)
    if classifier.model_loaded:
        mode, confidence = await classifier.classify_embeddings(text)
    else:
        # Fallback to pattern matching
        mode, confidence = classifier.classify_patterns(text_lower)

    # Determine active tools
    tools = classifier.determine_tools(text_lower, entities)

    # Check for delegation to specialized agent
    delegate_to = classifier.check_delegation(text_lower)

    return RouterResult(
        mode=mode,
        tools=tools,
        entities=entities,
        confidence=confidence,
        delegate_to=delegate_to,
        jump_host=jump_host,
    )


async def handle_skill_matching(
    user_input: str,
    result: RouterResult,
    classifier: IntentClassifier,
    llm_model: str | None,
    check_skills: bool,
    skip_skills: bool,
) -> RouterResult:
    """
    Handle skill matching for a classification result.

    Args:
        user_input: User input text.
        result: Current RouterResult.
        classifier: IntentClassifier instance.
        llm_model: LLM model string or None.
        check_skills: Whether to check skills.
        skip_skills: Whether to skip skill matching.

    Returns:
        Updated RouterResult.
    """
    # SKILL AUTO-MATCHING DISABLED
    # Skills caused too many false positives (e.g., "config cloudflared" -> service_check at 0.88)
    # The main LLM agent handles all requests better with full tool access.
    # Skills are still available via explicit invocation: /skill run <name> @hosts
    #
    # To re-enable, set check_skills=True and uncomment below:
    _ = check_skills  # Suppress unused variable warning
    if False and check_skills and not skip_skills:  # noqa: SIM223
        try:
            # Only use semantic embeddings for skill matching
            # Regex fallback is DISABLED - it causes too many false positives
            if classifier.model_loaded:
                skill_match, skill_confidence = await match_skill_embeddings(classifier, user_input)

                # Log ALL matches for debugging (even below threshold)
                if skill_match:
                    logger.info(f"Skill candidate: {skill_match} ({skill_confidence:.2f})")

                # Require higher confidence (0.88) to avoid false positives
                # Lower values cause skills like service_check to trigger for config queries
                # Example: "config cloudflared" scores 0.87 for service_check (false positive)
                if skill_match and skill_confidence >= 0.88:
                    result.skill_match = skill_match
                    result.skill_confidence = skill_confidence
                    logger.info(f"Skill activated: {skill_match} ({skill_confidence:.2f})")
            elif llm_model:
                # ONNX not loaded but LLM fallback is configured
                # Use LLM to match skills (slower but accurate)
                skill_match, skill_confidence = await match_skill_with_llm(llm_model, user_input)
                if skill_match and skill_confidence >= 0.7:
                    result.skill_match = skill_match
                    result.skill_confidence = skill_confidence
                    logger.debug(f"Skill match (LLM): {skill_match} ({skill_confidence:.2f})")
            else:
                # ONNX not loaded and no LLM fallback - skip skill matching entirely
                # This prevents regex patterns from causing false matches
                logger.debug("Skill matching disabled - ONNX not loaded, no LLM fallback")
        except Exception as e:
            logger.warning(f"Skill matching failed: {e}")

    return result


async def handle_llm_fallback(
    user_input: str,
    result: RouterResult,
    classifier: IntentClassifier,
    llm_model: str | None,
    detect_jump_host_func: object,
) -> RouterResult:
    """
    Handle LLM fallback classification when confidence is low.

    Args:
        user_input: User input text.
        result: Current RouterResult.
        classifier: IntentClassifier instance.
        llm_model: LLM model string or None.
        detect_jump_host_func: Function to detect jump hosts.

    Returns:
        Updated RouterResult.
    """
    if result.confidence < classifier.CONFIDENCE_THRESHOLD and llm_model:
        llm_result = await classify_with_llm(
            llm_model,
            user_input,
            classifier,
            detect_jump_host_func,
        )
        if llm_result:
            # Preserve skill match from earlier
            if result.skill_match:
                llm_result.skill_match = result.skill_match
                llm_result.skill_confidence = result.skill_confidence
            # Preserve entities if LLM didn't extract them (LLM often misses custom hostnames)
            if result.entities and not llm_result.entities:
                llm_result.entities = result.entities
                logger.debug("Preserving entities from SmartExtractor (LLM fallback missed them)")
            result = llm_result

    return result


__all__ = [
    "classify_input",
    "handle_llm_fallback",
    "handle_skill_matching",
]
