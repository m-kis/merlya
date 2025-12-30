"""
Tests for provisioners base module.

v0.9.0: Initial tests for provisioner abstractions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.provisioners.base import (
    AbstractProvisioner,
    ApplyOutput,
    DiffOutput,
    PlanOutput,
    ProvisionerAction,
    ProvisionerDeps,
    ProvisionerResult,
    ProvisionerStage,
    ResourceChange,
    ResourceSpec,
    RollbackOutput,
)


class TestProvisionerAction:
    """Test ProvisionerAction enum."""

    def test_action_values(self) -> None:
        """Test action enum values."""
        assert ProvisionerAction.CREATE.value == "create"
        assert ProvisionerAction.UPDATE.value == "update"
        assert ProvisionerAction.DELETE.value == "delete"


class TestProvisionerStage:
    """Test ProvisionerStage enum."""

    def test_stage_values(self) -> None:
        """Test stage enum values."""
        assert ProvisionerStage.VALIDATE.value == "validate"
        assert ProvisionerStage.PLAN.value == "plan"
        assert ProvisionerStage.APPLY.value == "apply"
        assert ProvisionerStage.HITL.value == "hitl"
        assert ProvisionerStage.ROLLBACK.value == "rollback"


class TestResourceSpec:
    """Test ResourceSpec model."""

    def test_minimal_spec(self) -> None:
        """Test minimal resource spec."""
        spec = ResourceSpec(
            resource_type="vm",
            name="test-vm",
            provider="aws",
        )
        assert spec.resource_type == "vm"
        assert spec.name == "test-vm"
        assert spec.provider == "aws"
        assert spec.config == {}
        assert spec.tags == {}

    def test_full_spec(self) -> None:
        """Test full resource spec."""
        spec = ResourceSpec(
            resource_type="vm",
            name="web-server-01",
            provider="aws",
            config={"instance_type": "t3.medium", "ami": "ami-12345"},
            tags={"env": "prod", "team": "infra"},
        )
        assert spec.config["instance_type"] == "t3.medium"
        assert spec.tags["env"] == "prod"


class TestResourceChange:
    """Test ResourceChange model."""

    def test_create_change(self) -> None:
        """Test create change."""
        change = ResourceChange(
            action=ProvisionerAction.CREATE,
            resource_type="vm",
            resource_name="new-vm",
            after={"cpu": 4, "memory": 8},
        )
        assert change.action == ProvisionerAction.CREATE
        assert change.before is None
        assert change.after["cpu"] == 4

    def test_update_change(self) -> None:
        """Test update change."""
        change = ResourceChange(
            action=ProvisionerAction.UPDATE,
            resource_type="vm",
            resource_name="existing-vm",
            before={"cpu": 2, "memory": 4},
            after={"cpu": 4, "memory": 8},
            attributes_changed=["cpu", "memory"],
        )
        assert change.action == ProvisionerAction.UPDATE
        assert change.attributes_changed == ["cpu", "memory"]


class TestPlanOutput:
    """Test PlanOutput model."""

    def test_empty_plan(self) -> None:
        """Test empty plan output."""
        plan = PlanOutput(success=True)
        assert plan.success is True
        assert plan.resources_to_create == 0
        assert plan.changes == []

    def test_plan_with_changes(self) -> None:
        """Test plan with changes."""
        plan = PlanOutput(
            success=True,
            resources_to_create=2,
            resources_to_update=1,
            resources_to_delete=0,
            estimated_cost="~$50/month",
            warnings=["Consider adding backup"],
        )
        assert plan.resources_to_create == 2
        assert plan.estimated_cost == "~$50/month"


class TestProvisionerDeps:
    """Test ProvisionerDeps model."""

    def test_minimal_deps(self) -> None:
        """Test minimal dependencies."""
        deps = ProvisionerDeps(
            action=ProvisionerAction.CREATE,
            provider="aws",
        )
        assert deps.action == ProvisionerAction.CREATE
        assert deps.provider == "aws"
        assert deps.backend == "auto"
        assert deps.dry_run is False
        assert deps.auto_rollback is True

    def test_full_deps(self) -> None:
        """Test full dependencies."""
        deps = ProvisionerDeps(
            action=ProvisionerAction.UPDATE,
            provider="gcp",
            backend="terraform",
            resources=[ResourceSpec(resource_type="vm", name="test", provider="gcp")],
            working_dir="/tmp/tf",
            dry_run=True,
            auto_rollback=False,
            environment="production",
            extra={"timeout": 300},
        )
        assert deps.backend == "terraform"
        assert deps.dry_run is True
        assert len(deps.resources) == 1


class TestProvisionerResult:
    """Test ProvisionerResult model."""

    def test_default_result(self) -> None:
        """Test default result values."""
        result = ProvisionerResult()
        assert result.success is False
        assert result.hitl_approved is False
        assert result.aborted is False

    def test_successful_result(self) -> None:
        """Test successful result."""
        result = ProvisionerResult(
            success=True,
            action=ProvisionerAction.CREATE,
            hitl_approved=True,
            hitl_approved_at=datetime.now(UTC),
            plan=PlanOutput(success=True, resources_to_create=1),
            apply=ApplyOutput(success=True, resources_created=["vm-1"]),
        )
        assert result.success is True
        assert result.hitl_approved is True
        assert result.plan is not None

    def test_aborted_result(self) -> None:
        """Test aborted result."""
        result = ProvisionerResult(
            success=False,
            aborted=True,
            aborted_at=ProvisionerStage.HITL,
            aborted_reason="User declined changes",
        )
        assert result.aborted is True
        assert result.aborted_at == ProvisionerStage.HITL


class ConcreteProvisioner(AbstractProvisioner):
    """Concrete provisioner for testing."""

    @property
    def name(self) -> str:
        return "test-provisioner"

    async def validate(self) -> tuple[bool, list[str]]:
        return True, []

    async def plan(self) -> PlanOutput:
        return PlanOutput(
            success=True,
            resources_to_create=1,
            changes=[
                ResourceChange(
                    action=ProvisionerAction.CREATE,
                    resource_type="vm",
                    resource_name="test-vm",
                )
            ],
        )

    async def diff(self) -> DiffOutput:
        return DiffOutput(
            success=True,
            has_changes=True,
            diff_text="+ vm.test-vm",
            changes_summary="Create 1 VM",
        )

    async def apply(self) -> ApplyOutput:
        return ApplyOutput(
            success=True,
            resources_created=["vm.test-vm"],
            outputs={"public_ip": "10.0.0.1"},
        )

    async def rollback(self) -> RollbackOutput:
        return RollbackOutput(success=True, resources_rolled_back=["vm.test-vm"])


class TestAbstractProvisioner:
    """Test AbstractProvisioner execution flow."""

    @pytest.fixture
    def mock_ctx(self) -> MagicMock:
        """Create mock context."""
        ctx = MagicMock()
        ctx.hitl = AsyncMock()
        ctx.hitl.request_approval = AsyncMock(return_value=True)
        return ctx

    @pytest.fixture
    def deps(self) -> ProvisionerDeps:
        """Create test dependencies."""
        return ProvisionerDeps(
            action=ProvisionerAction.CREATE,
            provider="test",
        )

    @pytest.mark.asyncio
    async def test_successful_execution(self, mock_ctx: MagicMock, deps: ProvisionerDeps) -> None:
        """Test successful execution flow."""
        provisioner = ConcreteProvisioner(mock_ctx, deps)
        result = await provisioner.execute()

        assert result.success is True
        assert result.hitl_approved is True
        assert result.plan is not None
        assert result.apply is not None
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_dry_run_skips_apply(self, mock_ctx: MagicMock) -> None:
        """Test dry run skips apply stage."""
        deps = ProvisionerDeps(
            action=ProvisionerAction.CREATE,
            provider="test",
            dry_run=True,
        )
        provisioner = ConcreteProvisioner(mock_ctx, deps)
        result = await provisioner.execute()

        assert result.success is True
        assert result.aborted is True
        assert result.aborted_reason == "Dry-run mode: apply skipped"
        assert result.apply is None

    @pytest.mark.asyncio
    async def test_hitl_rejection(self, mock_ctx: MagicMock, deps: ProvisionerDeps) -> None:
        """Test HITL rejection aborts execution."""
        mock_ctx.hitl.request_approval = AsyncMock(return_value=False)
        provisioner = ConcreteProvisioner(mock_ctx, deps)
        result = await provisioner.execute()

        assert result.success is False
        assert result.aborted is True
        assert result.aborted_at == ProvisionerStage.HITL

    @pytest.mark.asyncio
    async def test_generate_summary(self, mock_ctx: MagicMock, deps: ProvisionerDeps) -> None:
        """Test summary generation."""
        provisioner = ConcreteProvisioner(mock_ctx, deps)
        plan = PlanOutput(
            success=True,
            resources_to_create=2,
            resources_to_update=1,
            estimated_cost="~$100/month",
        )
        diff = DiffOutput(success=True, has_changes=True, changes_summary="Test changes")
        summary = provisioner._generate_summary(plan, diff)

        assert "test-provisioner" in summary
        assert "Create: 2" in summary
        assert "Update: 1" in summary
        assert "~$100/month" in summary
