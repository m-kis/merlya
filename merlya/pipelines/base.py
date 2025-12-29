"""
Merlya Pipelines - Base Classes.

Defines the core abstractions for controlled change pipelines.
Each pipeline follows: Plan -> Diff -> Summary -> HITL -> Apply -> Post-check -> Rollback
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


class PipelineStage(str, Enum):
    """Stages in a change pipeline."""

    PLAN = "plan"
    DIFF = "diff"
    SUMMARY = "summary"
    HITL = "hitl"
    APPLY = "apply"
    POST_CHECK = "post_check"
    ROLLBACK = "rollback"


class PlanResult(BaseModel):
    """Result from the plan stage."""

    success: bool
    plan_output: str
    resources_affected: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiffResult(BaseModel):
    """Result from the diff/dry-run stage."""

    success: bool
    diff_output: str
    additions: int = 0
    modifications: int = 0
    deletions: int = 0
    unchanged: int = 0
    risk_assessment: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApplyResult(BaseModel):
    """Result from the apply stage."""

    success: bool
    output: str
    resources_created: list[str] = Field(default_factory=list)
    resources_modified: list[str] = Field(default_factory=list)
    resources_deleted: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    rollback_data: dict[str, Any] = Field(default_factory=dict)


class RollbackResult(BaseModel):
    """Result from a rollback operation."""

    success: bool
    output: str
    resources_restored: list[str] = Field(default_factory=list)
    partial: bool = False
    errors: list[str] = Field(default_factory=list)


class PostCheckResult(BaseModel):
    """Result from post-apply verification."""

    success: bool
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PipelineResult(BaseModel):
    """Complete result from pipeline execution."""

    success: bool
    aborted: bool = False
    aborted_at: PipelineStage | None = None
    aborted_reason: str | None = None

    # Stage results
    plan: PlanResult | None = None
    diff: DiffResult | None = None
    apply: ApplyResult | None = None
    post_check: PostCheckResult | None = None
    rollback: RollbackResult | None = None

    # Was rollback triggered?
    rollback_triggered: bool = False
    rollback_reason: str | None = None

    # Timing
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int = 0

    # Audit
    hitl_approved: bool = False
    hitl_approved_at: datetime | None = None


class PipelineDeps(BaseModel):
    """Dependencies for pipeline execution."""

    model_config = {"arbitrary_types_allowed": True}

    target: str
    task: str
    working_dir: str | None = None
    dry_run: bool = False
    auto_rollback: bool = True
    extra: dict[str, Any] = Field(default_factory=dict)


class AbstractPipeline(ABC):
    """
    Abstract base class for change pipelines.

    All pipelines must implement:
    - plan(): Prepare and validate changes
    - diff(): Show what will change (dry-run)
    - apply(): Execute the changes
    - rollback(): Revert changes if needed
    - post_check(): Verify changes were successful
    """

    def __init__(self, ctx: SharedContext, deps: PipelineDeps):
        """
        Initialize pipeline with context and dependencies.

        Args:
            ctx: Shared context with infrastructure access.
            deps: Pipeline dependencies and configuration.
        """
        self._ctx = ctx
        self._deps = deps
        self._current_stage: PipelineStage | None = None
        self._rollback_data: dict[str, Any] = {}

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the pipeline name (e.g., 'terraform', 'ansible')."""
        ...

    @abstractmethod
    async def plan(self) -> PlanResult:
        """
        Plan stage: Prepare and validate changes.

        Returns:
            PlanResult with validation output and affected resources.
        """
        ...

    @abstractmethod
    async def diff(self) -> DiffResult:
        """
        Diff stage: Show what will change (dry-run).

        Returns:
            DiffResult with change preview.
        """
        ...

    @abstractmethod
    async def apply(self) -> ApplyResult:
        """
        Apply stage: Execute the changes.

        Returns:
            ApplyResult with execution details.
        """
        ...

    @abstractmethod
    async def rollback(self) -> RollbackResult:
        """
        Rollback stage: Revert changes.

        Returns:
            RollbackResult with restoration details.
        """
        ...

    @abstractmethod
    async def post_check(self) -> PostCheckResult:
        """
        Post-check stage: Verify changes were successful.

        Returns:
            PostCheckResult with verification details.
        """
        ...

    async def execute(self) -> PipelineResult:
        """
        Execute the full pipeline with HITL approval.

        Flow: Plan -> Diff -> Summary -> HITL -> Apply -> Post-check

        If post-check fails and auto_rollback is enabled, rollback is triggered.

        Returns:
            Complete PipelineResult with all stage results.
        """
        start_time = datetime.now(UTC)

        result = PipelineResult(
            success=False,
            started_at=start_time,
        )

        try:
            # Stage 1: Plan
            self._current_stage = PipelineStage.PLAN
            plan_result = await self.plan()
            result.plan = plan_result

            if not plan_result.success:
                result.aborted = True
                result.aborted_at = PipelineStage.PLAN
                result.aborted_reason = "Planning failed"
                return self._finalize_result(result)

            # Stage 2: Diff
            self._current_stage = PipelineStage.DIFF
            diff_result = await self.diff()
            result.diff = diff_result

            if not diff_result.success:
                result.aborted = True
                result.aborted_at = PipelineStage.DIFF
                result.aborted_reason = "Diff generation failed"
                return self._finalize_result(result)

            # Stage 3: Summary (generated for HITL)
            self._current_stage = PipelineStage.SUMMARY
            summary = self._generate_summary(plan_result, diff_result)

            # Stage 4: HITL Approval
            self._current_stage = PipelineStage.HITL
            approved = await self._request_hitl(summary, diff_result)

            if not approved:
                result.aborted = True
                result.aborted_at = PipelineStage.HITL
                result.aborted_reason = "HITL: User declined changes"
                return self._finalize_result(result)

            result.hitl_approved = True
            result.hitl_approved_at = datetime.now(UTC)

            # Stage 5: Apply (skip if dry_run)
            if self._deps.dry_run:
                result.success = True
                result.aborted = True
                result.aborted_at = PipelineStage.APPLY
                result.aborted_reason = "Dry-run mode: apply skipped"
                return self._finalize_result(result)

            self._current_stage = PipelineStage.APPLY
            apply_result = await self.apply()
            result.apply = apply_result
            self._rollback_data = apply_result.rollback_data

            if not apply_result.success:
                # Apply failed - attempt rollback if enabled
                if self._deps.auto_rollback:
                    result.rollback_triggered = True
                    result.rollback_reason = "Apply stage failed"
                    result.rollback = await self._safe_rollback()
                return self._finalize_result(result)

            # Stage 6: Post-check
            self._current_stage = PipelineStage.POST_CHECK
            post_check_result = await self.post_check()
            result.post_check = post_check_result

            if not post_check_result.success:
                # Post-check failed - attempt rollback if enabled
                if self._deps.auto_rollback:
                    result.rollback_triggered = True
                    result.rollback_reason = "Post-check verification failed"
                    result.rollback = await self._safe_rollback()
                return self._finalize_result(result)

            # All stages successful
            result.success = True
            return self._finalize_result(result)

        except Exception as e:
            result.aborted = True
            result.aborted_at = self._current_stage
            result.aborted_reason = f"Exception: {e}"

            # Attempt rollback on exception if we've applied changes
            should_rollback = (
                self._current_stage in (PipelineStage.APPLY, PipelineStage.POST_CHECK)
                and self._deps.auto_rollback
                and self._rollback_data
            )
            if should_rollback:
                result.rollback_triggered = True
                result.rollback_reason = f"Exception during {self._current_stage}"
                result.rollback = await self._safe_rollback()

            return self._finalize_result(result)

    def _generate_summary(
        self,
        plan: PlanResult,
        diff: DiffResult,
    ) -> str:
        """
        Generate human-readable summary for HITL approval.

        Args:
            plan: Plan stage result.
            diff: Diff stage result.

        Returns:
            Formatted summary string.
        """
        lines = [
            f"Pipeline: {self.name}",
            f"Target: {self._deps.target}",
            "",
            "Changes:",
            f"  + Additions: {diff.additions}",
            f"  ~ Modifications: {diff.modifications}",
            f"  - Deletions: {diff.deletions}",
            f"  = Unchanged: {diff.unchanged}",
            "",
        ]

        if plan.resources_affected:
            lines.append("Affected resources:")
            for resource in plan.resources_affected[:10]:
                lines.append(f"  - {resource}")
            if len(plan.resources_affected) > 10:
                lines.append(f"  ... and {len(plan.resources_affected) - 10} more")
            lines.append("")

        if plan.warnings:
            lines.append("Warnings:")
            for warning in plan.warnings:
                lines.append(f"  ⚠️ {warning}")
            lines.append("")

        if diff.risk_assessment:
            lines.append(f"Risk Assessment: {diff.risk_assessment}")

        return "\n".join(lines)

    async def _request_hitl(self, summary: str, diff: DiffResult) -> bool:
        """
        Request human-in-the-loop approval.

        Args:
            summary: Change summary.
            diff: Diff result for detailed view.

        Returns:
            True if approved, False otherwise.
        """
        # Determine risk level based on changes
        risk_level = self._assess_risk_level(diff)

        # Format confirmation message with risk level
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(
            risk_level, "⚪"
        )
        confirm_msg = f"{risk_emoji} [{risk_level.upper()}] Approve {self.name} changes?"
        logger.info(f"📋 Summary:\n{summary}")
        return await self._ctx.ui.prompt_confirm(confirm_msg, default=False)

    def _assess_risk_level(self, diff: DiffResult) -> str:
        """
        Assess risk level based on diff.

        Args:
            diff: Diff result.

        Returns:
            Risk level string: low, medium, high, critical.
        """
        if diff.deletions > 5:
            return "critical"
        if diff.deletions > 0 or diff.modifications > 10:
            return "high"
        if diff.modifications > 0:
            return "medium"
        return "low"

    async def _safe_rollback(self) -> RollbackResult:
        """
        Safely attempt rollback, catching any exceptions.

        Returns:
            RollbackResult, with errors captured if rollback failed.
        """
        try:
            self._current_stage = PipelineStage.ROLLBACK
            return await self.rollback()
        except Exception as e:
            return RollbackResult(
                success=False,
                output="",
                errors=[f"Rollback failed: {e}"],
            )

    def _finalize_result(self, result: PipelineResult) -> PipelineResult:
        """
        Finalize result with timing information.

        Args:
            result: Pipeline result to finalize.

        Returns:
            Finalized result with timing.
        """
        result.completed_at = datetime.now(UTC)
        result.duration_ms = int((result.completed_at - result.started_at).total_seconds() * 1000)
        return result
