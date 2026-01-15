"""
Utility tools for the orchestrator.

Contains @agent.tool decorated functions for user interaction and intent classification.
"""

from __future__ import annotations

from pydantic_ai import Agent, RunContext  # noqa: TC002 - required at runtime

from .models import OrchestratorDeps, OrchestratorResponse  # noqa: TC001


def register_utility_tools(
    agent: Agent[OrchestratorDeps, OrchestratorResponse],
) -> None:
    """Register utility tools (ask_user, classify_intent)."""

    @agent.tool
    async def ask_user(
        ctx: RunContext[OrchestratorDeps],
        question: str,
        choices: list[str] | None = None,
    ) -> str:
        """
        Ask the user a question directly.

        Use when you need clarification before delegating.

        Args:
            question: Question to ask.
            choices: Optional list of choices.

        Returns:
            User's response.
        """
        from merlya.tools.core import ask_user as _ask_user

        result = await _ask_user(ctx.deps.context, question, choices=choices)
        if result.success:
            return str(result.data) or ""
        return ""

    @agent.tool
    async def classify_intent(
        ctx: RunContext[OrchestratorDeps],
        user_request: str,
    ) -> dict[str, object]:
        """
        Classify user intent to determine the best center to use.

        Use this when unsure whether a request is read-only (DIAGNOSTIC)
        or requires changes (CHANGE).

        Args:
            user_request: The user's request text to classify.

        Returns:
            Classification with recommended center and confidence.
        """
        from merlya.router.center_classifier import CenterClassifier

        classifier = CenterClassifier(ctx.deps.context)
        result = await classifier.classify(user_request)

        return {
            "recommended_center": result.center.value,
            "confidence": result.confidence,
            "clarification_needed": result.clarification_needed,
            "suggested_prompt": result.suggested_prompt,
            "reasoning": result.reasoning,
        }
