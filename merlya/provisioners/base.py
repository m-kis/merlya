"""
Merlya Provisioners - Base abstractions.

Provides the core abstractions for infrastructure provisioning:
- ProvisionerAction: CREATE, UPDATE, DELETE operations
- ProvisionerStage: Workflow stages (validate, plan, apply, etc.)
- AbstractProvisioner: Base class with HITL workflow

v0.9.0: Initial implementation following Pipeline patterns.
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


class ProvisionerAction(str, Enum):
    """Actions that can be performed on infrastructure."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class ProvisionerStage(str, Enum):
    """Stages in the provisioning workflow."""

    VALIDATE = "validate"
    PLAN = "plan"
    DIFF = "diff"
    SUMMARY = "summary"
    HITL = "hitl"
    APPLY = "apply"
    POST_CHECK = "post_check"
    ROLLBACK = "rollback"


class ResourceSpec(BaseModel):
    """Specification for a resource to provision."""

    resource_type: str = Field(description="Type of resource (vm, vpc, subnet, etc.)")
    name: str = Field(description="Name for the resource")
    provider: str = Field(description="Cloud provider (aws, gcp, azure, etc.)")
    config: dict[str, Any] = Field(
        default_factory=dict, description="Provider-specific configuration"
    )
    tags: dict[str, str] = Field(default_factory=dict, description="Resource tags")


class ResourceChange(BaseModel):
    """A single resource change in a plan."""

    action: ProvisionerAction
    resource_type: str
    resource_name: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    attributes_changed: list[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    """Result of the plan stage."""

    success: bool = False
    changes: list[ResourceChange] = Field(default_factory=list)
    resources_to_create: int = 0
    resources_to_update: int = 0
    resources_to_delete: int = 0
    estimated_cost: str | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    raw_plan: str | None = None


class DiffOutput(BaseModel):
    """Result of the diff stage."""

    success: bool = False
    diff_text: str = ""
    has_changes: bool = False
    changes_summary: str = ""


class ApplyOutput(BaseModel):
    """Result of the apply stage."""

    success: bool = False
    resources_created: list[str] = Field(default_factory=list)
    resources_updated: list[str] = Field(default_factory=list)
    resources_deleted: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    rollback_data: dict[str, Any] | None = None


class PostCheckOutput(BaseModel):
    """Result of post-apply verification."""

    success: bool = False
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)
    resource_states: dict[str, str] = Field(default_factory=dict)


class RollbackOutput(BaseModel):
    """Result of rollback operation."""

    success: bool = False
    resources_rolled_back: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ProvisionerDeps(BaseModel):
    """Dependencies for provisioner execution."""

    model_config = {"arbitrary_types_allowed": True}

    action: ProvisionerAction
    resources: list[ResourceSpec] = Field(default_factory=list)
    provider: str = Field(description="Target cloud provider")
    backend: str = Field(default="auto", description="Backend: mcp, terraform, pulumi, auto")
    working_dir: str | None = None
    dry_run: bool = False
    auto_rollback: bool = True
    environment: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ProvisionerResult(BaseModel):
    """Complete result of a provisioning operation."""

    success: bool = False
    action: ProvisionerAction | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    # Stage results
    plan: PlanOutput | None = None
    diff: DiffOutput | None = None
    apply: ApplyOutput | None = None
    post_check: PostCheckOutput | None = None
    rollback: RollbackOutput | None = None

    # HITL tracking
    hitl_approved: bool = False
    hitl_approved_at: datetime | None = None

    # Abort tracking
    aborted: bool = False
    aborted_at: ProvisionerStage | None = None
    aborted_reason: str | None = None

    # Rollback tracking
    rollback_triggered: bool = False
    rollback_reason: str | None = None


class AbstractProvisioner(ABC):
    """
    Abstract base class for infrastructure provisioners.

    Implements the standard workflow:
    Validate -> Plan -> Diff -> Summary -> HITL -> Apply -> Post-check

    Subclasses must implement the abstract methods for each stage.
    """

    def __init__(self, ctx: SharedContext, deps: ProvisionerDeps) -> None:
        """
        Initialize the provisioner.

        Args:
            ctx: Shared context with config, secrets, etc.
            deps: Provisioner dependencies.
        """
        self._ctx = ctx
        self._deps = deps
        self._current_stage: ProvisionerStage = ProvisionerStage.VALIDATE
        self._rollback_data: dict[str, Any] | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provisioner name."""
        ...

    @abstractmethod
    async def validate(self) -> tuple[bool, list[str]]:
        """
        Validate prerequisites (credentials, tools, etc.).

        Returns:
            Tuple of (success, list of error messages).
        """
        ...

    @abstractmethod
    async def plan(self) -> PlanOutput:
        """
        Generate an execution plan.

        Returns:
            PlanOutput with changes to be made.
        """
        ...

    @abstractmethod
    async def diff(self) -> DiffOutput:
        """
        Generate a human-readable diff.

        Returns:
            DiffOutput with diff text.
        """
        ...

    @abstractmethod
    async def apply(self) -> ApplyOutput:
        """
        Apply the changes.

        Returns:
            ApplyOutput with results.
        """
        ...

    @abstractmethod
    async def rollback(self) -> RollbackOutput:
        """
        Rollback applied changes.

        Returns:
            RollbackOutput with results.
        """
        ...

    async def post_check(self) -> PostCheckOutput:
        """
        Verify the applied changes.

        Default implementation marks as successful.
        Override for custom verification.

        Returns:
            PostCheckOutput with verification results.
        """
        return PostCheckOutput(success=True)

    async def execute(self) -> ProvisionerResult:
        """
        Execute the full provisioning workflow with HITL approval.

        Flow: Validate -> Plan -> Diff -> Summary -> HITL -> Apply -> Post-check

        Returns:
            Complete ProvisionerResult.
        """
        start_time = datetime.now(UTC)
        result = ProvisionerResult(
            success=False,
            action=self._deps.action,
            started_at=start_time,
        )

        try:
            # Stage 1: Validate
            self._current_stage = ProvisionerStage.VALIDATE
            valid, errors = await self.validate()
            if not valid:
                result.aborted = True
                result.aborted_at = ProvisionerStage.VALIDATE
                result.aborted_reason = f"Validation failed: {'; '.join(errors)}"
                return self._finalize_result(result)

            # Stage 2: Plan
            self._current_stage = ProvisionerStage.PLAN
            plan_result = await self.plan()
            result.plan = plan_result

            if not plan_result.success:
                result.aborted = True
                result.aborted_at = ProvisionerStage.PLAN
                result.aborted_reason = "Planning failed"
                return self._finalize_result(result)

            # No changes to apply
            if (
                plan_result.resources_to_create == 0
                and plan_result.resources_to_update == 0
                and plan_result.resources_to_delete == 0
            ):
                result.success = True
                result.aborted = True
                result.aborted_at = ProvisionerStage.PLAN
                result.aborted_reason = "No changes to apply"
                return self._finalize_result(result)

            # Stage 3: Diff
            self._current_stage = ProvisionerStage.DIFF
            diff_result = await self.diff()
            result.diff = diff_result

            if not diff_result.success:
                result.aborted = True
                result.aborted_at = ProvisionerStage.DIFF
                result.aborted_reason = "Diff generation failed"
                return self._finalize_result(result)

            # Stage 4: Summary + HITL
            self._current_stage = ProvisionerStage.HITL
            summary = self._generate_summary(plan_result, diff_result)
            approved = await self._request_hitl(summary, diff_result)

            if not approved:
                result.aborted = True
                result.aborted_at = ProvisionerStage.HITL
                result.aborted_reason = "User declined changes"
                return self._finalize_result(result)

            result.hitl_approved = True
            result.hitl_approved_at = datetime.now(UTC)

            # Stage 5: Apply (skip if dry_run)
            if self._deps.dry_run:
                result.success = True
                result.aborted = True
                result.aborted_at = ProvisionerStage.APPLY
                result.aborted_reason = "Dry-run mode: apply skipped"
                return self._finalize_result(result)

            self._current_stage = ProvisionerStage.APPLY
            apply_result = await self.apply()
            result.apply = apply_result
            self._rollback_data = apply_result.rollback_data

            if not apply_result.success:
                if self._deps.auto_rollback and self._rollback_data:
                    result.rollback_triggered = True
                    result.rollback_reason = "Apply stage failed"
                    result.rollback = await self._safe_rollback()
                return self._finalize_result(result)

            # Stage 6: Post-check
            self._current_stage = ProvisionerStage.POST_CHECK
            post_check_result = await self.post_check()
            result.post_check = post_check_result

            if not post_check_result.success:
                if self._deps.auto_rollback and self._rollback_data:
                    result.rollback_triggered = True
                    result.rollback_reason = "Post-check verification failed"
                    result.rollback = await self._safe_rollback()
                return self._finalize_result(result)

            # All stages successful
            result.success = True
            return self._finalize_result(result)

        except Exception as e:
            logger.exception(f"Provisioner error: {e}")
            result.aborted = True
            result.aborted_at = self._current_stage
            result.aborted_reason = f"Exception: {e}"

            # Attempt rollback on exception
            should_rollback = (
                self._current_stage in (ProvisionerStage.APPLY, ProvisionerStage.POST_CHECK)
                and self._deps.auto_rollback
                and self._rollback_data
            )
            if should_rollback:
                result.rollback_triggered = True
                result.rollback_reason = f"Exception during {self._current_stage.value}"
                result.rollback = await self._safe_rollback()

            return self._finalize_result(result)

    def _generate_summary(self, plan: PlanOutput, diff: DiffOutput) -> str:
        """Generate a human-readable summary for HITL approval."""
        action_verb = {
            ProvisionerAction.CREATE: "create",
            ProvisionerAction.UPDATE: "update",
            ProvisionerAction.DELETE: "delete",
        }
        verb = action_verb.get(self._deps.action, "modify")

        summary_parts = [
            f"## Provisioner: {self.name}",
            f"Action: {verb.upper()}",
            f"Provider: {self._deps.provider}",
            "",
            "### Changes:",
            f"  - Create: {plan.resources_to_create}",
            f"  - Update: {plan.resources_to_update}",
            f"  - Delete: {plan.resources_to_delete}",
        ]

        if plan.estimated_cost:
            summary_parts.append(f"\nEstimated cost: {plan.estimated_cost}")

        if plan.warnings:
            summary_parts.append("\n### Warnings:")
            for w in plan.warnings:
                summary_parts.append(f"  - {w}")

        if diff.has_changes:
            summary_parts.append("\n### Diff Preview:")
            summary_parts.append(diff.changes_summary or diff.diff_text[:500])

        return "\n".join(summary_parts)

    async def _request_hitl(self, summary: str, diff: DiffOutput) -> bool:
        """Request HITL approval."""
        # Use the context's HITL mechanism
        if hasattr(self._ctx, "hitl") and self._ctx.hitl:
            result = await self._ctx.hitl.request_approval(
                action=f"Provisioner: {self.name}",
                summary=summary,
                diff=diff.diff_text if diff.has_changes else None,
                is_destructive=self._deps.action == ProvisionerAction.DELETE,
            )
            return bool(result)
        # Fallback: log and return True for non-interactive contexts
        logger.warning("HITL not available, auto-approving (non-production use only)")
        return True

    async def _safe_rollback(self) -> RollbackOutput:
        """Execute rollback with error handling."""
        try:
            self._current_stage = ProvisionerStage.ROLLBACK
            return await self.rollback()
        except Exception as e:
            logger.exception(f"Rollback failed: {e}")
            return RollbackOutput(success=False, errors=[str(e)])

    def _finalize_result(self, result: ProvisionerResult) -> ProvisionerResult:
        """Finalize the result with timing information."""
        result.completed_at = datetime.now(UTC)
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
        return result
