"""
Merlya Router - LLM-based classification.

Uses SmartExtractor with fast LLM model for semantic understanding.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel

from merlya.router.intent_classifier import AgentMode
from merlya.router.models import RouterResult
from merlya.router.router_primitives import (
    _LLMClassification,
    _LLMSkillMatch,
    extract_json_dict,
)

if TYPE_CHECKING:
    from merlya.router.intent_classifier import IntentClassifier

# Timeout for LLM classification calls (in seconds)
LLM_CLASSIFICATION_TIMEOUT = 15.0

# Security limit for LLM response size
MAX_LLM_RESPONSE_SIZE = 100_000  # 100KB


async def match_skill_embeddings(
    classifier: IntentClassifier,
    user_input: str,
) -> tuple[str | None, float]:
    """
    Match user input against registered skills using semantic embeddings.

    This is the preferred method - uses ONNX embeddings for semantic understanding.

    Args:
        classifier: IntentClassifier instance.
        user_input: User input text.

    Returns:
        Tuple of (skill_name, confidence) or (None, 0.0).
    """
    if classifier.model_loaded:
        skill_name, confidence = await classifier.get_best_skill_match(user_input)  # type: ignore[attr-defined]
        if skill_name:
            return skill_name, confidence
    return None, 0.0


async def match_skill_with_llm(
    llm_model: str | None,
    user_input: str,
) -> tuple[str | None, float]:
    """
    Match user input against registered skills using LLM.

    This is the fallback method when ONNX is not available.
    Slower but accurate for skill matching.

    Args:
        llm_model: LLM model string (e.g., "openai:gpt-4o-mini").
        user_input: User input text.

    Returns:
        Tuple of (skill_name, confidence) or (None, 0.0).
    """
    if not llm_model:
        return None, 0.0

    try:
        from pydantic_ai import Agent

        from merlya.skills.registry import get_registry

        registry = get_registry()
        skills = registry.get_all()

        if not skills:
            return None, 0.0

        # Build skills description for LLM
        skills_info = []
        for skill in skills:
            skills_info.append(f"- {skill.name}: {skill.description}")

        skills_list = "\n".join(skills_info)

        system_prompt = f"""You are a skill matcher. Given a user request and a list of available skills,
determine if any skill matches the request.

Available skills:
{skills_list}

Respond in JSON format:
{{"skill": "skill_name or null", "confidence": 0.0-1.0, "reason": "brief explanation"}}

Rules:
- Only match if the request clearly fits the skill's purpose
- Return null if no skill matches or if it's a general question
- Confidence should be 0.7+ only for clear matches
- Don't match skills for questions about configuration or setup"""

        agent = Agent(
            llm_model,
            system_prompt=system_prompt,
            output_type=_LLMSkillMatch,
            retries=1,
        )

        # Add timeout to prevent indefinite hangs
        run_result = await asyncio.wait_for(
            agent.run(f"Does any skill match this request? '{user_input}'"),
            timeout=LLM_CLASSIFICATION_TIMEOUT,
        )
        match = run_result.output
        skill_name = match.skill
        confidence = float(match.confidence)

        if skill_name and confidence >= 0.5:
            # Verify skill exists
            if registry.get(skill_name):
                logger.debug(
                    f"LLM skill match: {skill_name} ({confidence:.2f}) - {match.reason or ''}"
                )
                return skill_name, confidence
            else:
                logger.warning(f"LLM matched non-existent skill: {skill_name}")

    except TimeoutError:
        logger.warning(f"LLM skill matching timed out after {LLM_CLASSIFICATION_TIMEOUT}s")
    except Exception as e:
        logger.warning(f"LLM skill matching failed: {e}")

    return None, 0.0


async def classify_with_llm(
    llm_model: str | None,
    user_input: str,
    classifier: IntentClassifier,
    detect_jump_host_func: Any,
) -> RouterResult | None:
    """
    Use LLM for intent classification when embedding confidence is low.

    Args:
        llm_model: LLM model string.
        user_input: User input text.
        classifier: IntentClassifier for entity extraction.
        detect_jump_host_func: Function to detect jump hosts.

    Returns:
        RouterResult or None if LLM fails.
    """
    if not llm_model:
        return None

    try:
        from pydantic_ai import Agent

        logger.debug(f"LLM classification starting with {llm_model}")

        # Create classification prompt
        system_prompt = """You are an intent classifier for an infrastructure management AI.
Classify the user's input into one of these modes:
- diagnostic: Checking status, monitoring, analyzing, listing, viewing
- remediation: Fixing, changing, deploying, configuring, restarting
- query: Asking questions, seeking explanations, learning
- chat: Greetings, thanks, general conversation

Also identify which tool categories are relevant:
- system: CPU, memory, disk, processes, services
- files: File operations, configurations, logs
- security: Ports, firewall, SSH, certificates
- docker: Container operations
- kubernetes: K8s operations
- credentials_required: true/false if auth credentials are needed
- elevation_required: true/false if admin/root is needed

Respond in JSON format:
{"mode": "diagnostic|remediation|query|chat", "tools": ["core", "system", ...], "credentials_required": false, "elevation_required": false, "reasoning": "brief explanation"}"""

        agent = Agent(
            llm_model,
            system_prompt=system_prompt,
            output_type=_LLMClassification,
            retries=1,
        )

        # Add timeout to prevent indefinite hangs
        response = await asyncio.wait_for(
            agent.run(f"Classify this input: {user_input}"),
            timeout=LLM_CLASSIFICATION_TIMEOUT,
        )
        logger.debug("LLM classification completed")
        return parse_llm_response(response, user_input, classifier, detect_jump_host_func)

    except TimeoutError:
        logger.warning(f"LLM classification timed out after {LLM_CLASSIFICATION_TIMEOUT}s")
        return None
    except Exception as e:
        logger.warning(f"LLM classification failed: {e}")
        return None


def parse_llm_response(
    response: object,
    user_input: str,
    classifier: IntentClassifier,
    detect_jump_host_func: Any,
) -> RouterResult | None:
    """Parse LLM classification response."""
    try:
        raw_output = getattr(response, "output", None)
        raw_data = getattr(response, "data", None)
        raw: object | None

        # Prefer explicit payloads (tests/mocks often have .data set while .output is a MagicMock).
        if isinstance(raw_data, (BaseModel, dict, str)):
            raw = raw_data
        elif isinstance(raw_output, (BaseModel, dict, str)):
            raw = raw_output
        else:
            raw = raw_output if raw_output is not None else raw_data
        data: dict[str, Any] | None = None

        if isinstance(raw, BaseModel):
            data = raw.model_dump()
        elif isinstance(raw, dict):
            data = raw
        elif raw is not None:
            raw_str = str(raw)
            # P0 Security: Validate size before parsing
            if len(raw_str) > MAX_LLM_RESPONSE_SIZE:
                logger.warning(f"LLM response too large: {len(raw_str)} bytes")
                return None
            data = extract_json_dict(raw_str) or json.loads(raw_str)
        else:
            raw_str = str(response)
            if len(raw_str) > MAX_LLM_RESPONSE_SIZE:
                logger.warning(f"LLM response too large: {len(raw_str)} bytes")
                return None
            data = extract_json_dict(raw_str) or json.loads(raw_str)

        if data is None:
            return None

        # Validate mode before creating enum
        mode_str = data.get("mode", "chat")
        try:
            mode = AgentMode(mode_str)
        except ValueError:
            logger.warning(f"Invalid mode from LLM: {mode_str}, defaulting to CHAT")
            mode = AgentMode.CHAT

        tools = data.get("tools", ["core"])
        reasoning = data.get("reasoning")
        credentials_required = bool(data.get("credentials_required", False))
        elevation_required = bool(data.get("elevation_required", False))

        # Re-extract entities and jump host
        entities = classifier.extract_entities(user_input)
        delegate_to = classifier.check_delegation(user_input.lower())
        jump_host = detect_jump_host_func(user_input)

        return RouterResult(
            mode=mode,
            tools=tools,
            entities=entities,
            confidence=0.9,  # LLM classifications are generally reliable
            delegate_to=delegate_to,
            reasoning=reasoning,
            credentials_required=credentials_required,
            elevation_required=elevation_required,
            jump_host=jump_host,
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to parse LLM response: {e}")
        return None


__all__ = [
    "LLM_CLASSIFICATION_TIMEOUT",
    "MAX_LLM_RESPONSE_SIZE",
    "classify_with_llm",
    "match_skill_embeddings",
    "match_skill_with_llm",
    "parse_llm_response",
]
