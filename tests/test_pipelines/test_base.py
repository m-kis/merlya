"""Tests for pipeline base classes."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.pipelines.base import (
    AbstractPipeline,
    ApplyResult,
    DiffResult,
    PipelineDeps,
    PipelineResult,
    PipelineStage,
    PlanResult,
    PostCheckResult,
    RollbackResult,
)


class TestPipelineStage:
    """Tests for PipelineStage enum."""

    def test_all_stages_defined(self) -> None:
        """Test all pipeline stages are defined."""
        assert PipelineStage.PLAN.value == "plan"
        assert PipelineStage.DIFF.value == "diff"
        assert PipelineStage.SUMMARY.value == "summary"
        assert PipelineStage.HITL.value == "hitl"
        assert PipelineStage.APPLY.value == "apply"
        assert PipelineStage.POST_CHECK.value == "post_check"
        assert PipelineStage.ROLLBACK.value == "rollback"

    def test_stage_count(self) -> None:
        """Test there are exactly 7 stages."""
        assert len(PipelineStage) == 7


class TestPlanResult:
    """Tests for PlanResult model."""

    def test_create_success_plan(self) -> None:
        """Test creating a successful plan result."""
        result = PlanResult(
            success=True,
            plan_output="All resources validated",
            resources_affected=["aws_instance.web", "aws_security_group.allow_http"],
        )
        assert result.success is True
        assert len(result.resources_affected) == 2
        assert result.warnings == []
        assert result.errors == []

    def test_create_failed_plan(self) -> None:
        """Test creating a failed plan result."""
        result = PlanResult(
            success=False,
            plan_output="",
            errors=["Invalid configuration", "Missing required field"],
        )
        assert result.success is False
        assert len(result.errors) == 2


class TestDiffResult:
    """Tests for DiffResult model."""

    def test_create_diff_with_changes(self) -> None:
        """Test creating a diff result with changes."""
        result = DiffResult(
            success=True,
            diff_output="+ resource created\n~ resource modified",
            additions=5,
            modifications=3,
            deletions=1,
            risk_assessment="medium",
        )
        assert result.success is True
        assert result.additions == 5
        assert result.modifications == 3
        assert result.deletions == 1
        assert result.risk_assessment == "medium"

    def test_create_no_changes_diff(self) -> None:
        """Test creating a diff with no changes."""
        result = DiffResult(
            success=True,
            diff_output="No changes",
            unchanged=10,
        )
        assert result.additions == 0
        assert result.deletions == 0
        assert result.unchanged == 10


class TestApplyResult:
    """Tests for ApplyResult model."""

    def test_create_successful_apply(self) -> None:
        """Test creating a successful apply result."""
        result = ApplyResult(
            success=True,
            output="Apply complete! Resources: 3 added, 1 changed, 0 destroyed.",
            resources_created=["web-01", "web-02", "lb-01"],
            resources_modified=["sg-main"],
            duration_ms=15000,
            rollback_data={"previous_state": "state.backup"},
        )
        assert result.success is True
        assert len(result.resources_created) == 3
        assert result.duration_ms == 15000
        assert "previous_state" in result.rollback_data

    def test_apply_defaults(self) -> None:
        """Test apply result defaults."""
        result = ApplyResult(success=True, output="OK")
        assert result.resources_created == []
        assert result.resources_modified == []
        assert result.resources_deleted == []
        assert result.duration_ms == 0
        assert result.rollback_data == {}


class TestRollbackResult:
    """Tests for RollbackResult model."""

    def test_successful_rollback(self) -> None:
        """Test successful rollback result."""
        result = RollbackResult(
            success=True,
            output="Rollback complete",
            resources_restored=["web-01", "web-02"],
        )
        assert result.success is True
        assert result.partial is False
        assert len(result.resources_restored) == 2

    def test_partial_rollback(self) -> None:
        """Test partial rollback result."""
        result = RollbackResult(
            success=False,
            output="Partial rollback",
            resources_restored=["web-01"],
            partial=True,
            errors=["Failed to restore web-02"],
        )
        assert result.success is False
        assert result.partial is True
        assert len(result.errors) == 1


class TestPostCheckResult:
    """Tests for PostCheckResult model."""

    def test_all_checks_passed(self) -> None:
        """Test post-check with all checks passed."""
        result = PostCheckResult(
            success=True,
            checks_passed=["connectivity", "service_health", "metrics"],
        )
        assert result.success is True
        assert len(result.checks_passed) == 3
        assert result.checks_failed == []

    def test_some_checks_failed(self) -> None:
        """Test post-check with some failures."""
        result = PostCheckResult(
            success=False,
            checks_passed=["connectivity"],
            checks_failed=["service_health"],
            warnings=["High latency detected"],
        )
        assert result.success is False
        assert len(result.checks_failed) == 1
        assert len(result.warnings) == 1


class TestPipelineResult:
    """Tests for PipelineResult model."""

    def test_successful_pipeline(self) -> None:
        """Test a fully successful pipeline result."""
        result = PipelineResult(
            success=True,
            plan=PlanResult(success=True, plan_output="OK"),
            diff=DiffResult(success=True, diff_output="OK"),
            apply=ApplyResult(success=True, output="OK"),
            post_check=PostCheckResult(success=True),
            hitl_approved=True,
        )
        assert result.success is True
        assert result.aborted is False
        assert result.rollback_triggered is False

    def test_aborted_pipeline(self) -> None:
        """Test an aborted pipeline result."""
        result = PipelineResult(
            success=False,
            aborted=True,
            aborted_at=PipelineStage.HITL,
            aborted_reason="User declined",
        )
        assert result.success is False
        assert result.aborted is True
        assert result.aborted_at == PipelineStage.HITL

    def test_pipeline_with_rollback(self) -> None:
        """Test pipeline that triggered rollback."""
        result = PipelineResult(
            success=False,
            apply=ApplyResult(success=True, output="OK"),
            post_check=PostCheckResult(success=False, checks_failed=["health"]),
            rollback_triggered=True,
            rollback_reason="Post-check failed",
            rollback=RollbackResult(success=True, output="Rolled back"),
        )
        assert result.rollback_triggered is True
        assert result.rollback is not None
        assert result.rollback.success is True


class TestPipelineDeps:
    """Tests for PipelineDeps model."""

    def test_create_minimal_deps(self) -> None:
        """Test creating deps with minimal info."""
        deps = PipelineDeps(target="web-01", task="deploy nginx")
        assert deps.target == "web-01"
        assert deps.task == "deploy nginx"
        assert deps.working_dir is None
        assert deps.dry_run is False
        assert deps.auto_rollback is True

    def test_create_full_deps(self) -> None:
        """Test creating deps with all options."""
        deps = PipelineDeps(
            target="db-cluster",
            task="upgrade postgresql",
            working_dir="/opt/terraform/db",
            dry_run=True,
            auto_rollback=False,
            extra={"version": "15.4"},
        )
        assert deps.working_dir == "/opt/terraform/db"
        assert deps.dry_run is True
        assert deps.auto_rollback is False
        assert deps.extra["version"] == "15.4"


class MockPipeline(AbstractPipeline):
    """Mock pipeline for testing abstract class."""

    def __init__(self, ctx: MagicMock, deps: PipelineDeps):
        super().__init__(ctx, deps)
        self.plan_result = PlanResult(success=True, plan_output="OK")
        self.diff_result = DiffResult(success=True, diff_output="OK", additions=1, modifications=2)
        self.apply_result = ApplyResult(success=True, output="OK")
        self.rollback_result = RollbackResult(success=True, output="OK")
        self.post_check_result = PostCheckResult(success=True)

    @property
    def name(self) -> str:
        return "mock"

    async def plan(self) -> PlanResult:
        return self.plan_result

    async def diff(self) -> DiffResult:
        return self.diff_result

    async def apply(self) -> ApplyResult:
        return self.apply_result

    async def rollback(self) -> RollbackResult:
        return self.rollback_result

    async def post_check(self) -> PostCheckResult:
        return self.post_check_result


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create mock context."""
    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.prompt_confirm = AsyncMock(return_value=True)
    return ctx


@pytest.fixture
def mock_deps() -> PipelineDeps:
    """Create mock deps."""
    return PipelineDeps(target="test-host", task="test task")


class TestAbstractPipeline:
    """Tests for AbstractPipeline class."""

    def test_pipeline_name(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test pipeline has a name."""
        pipeline = MockPipeline(mock_ctx, mock_deps)
        assert pipeline.name == "mock"

    async def test_successful_execution(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test successful pipeline execution."""
        pipeline = MockPipeline(mock_ctx, mock_deps)

        result = await pipeline.execute()

        assert result.success is True
        assert result.aborted is False
        assert result.hitl_approved is True
        assert result.plan is not None
        assert result.diff is not None
        assert result.apply is not None
        assert result.post_check is not None
        assert result.rollback_triggered is False
        assert result.duration_ms >= 0

    async def test_plan_failure_aborts(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test pipeline aborts on plan failure."""
        pipeline = MockPipeline(mock_ctx, mock_deps)
        pipeline.plan_result = PlanResult(success=False, plan_output="", errors=["Invalid config"])

        result = await pipeline.execute()

        assert result.success is False
        assert result.aborted is True
        assert result.aborted_at == PipelineStage.PLAN
        assert result.apply is None

    async def test_hitl_decline_aborts(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test pipeline aborts when HITL declined."""
        mock_ctx.ui.prompt_confirm = AsyncMock(return_value=False)
        pipeline = MockPipeline(mock_ctx, mock_deps)

        result = await pipeline.execute()

        assert result.success is False
        assert result.aborted is True
        assert result.aborted_at == PipelineStage.HITL
        assert result.hitl_approved is False

    async def test_dry_run_skips_apply(self, mock_ctx: MagicMock) -> None:
        """Test dry-run mode skips apply."""
        deps = PipelineDeps(target="test", task="test", dry_run=True)
        pipeline = MockPipeline(mock_ctx, deps)

        result = await pipeline.execute()

        assert result.success is True
        assert result.aborted is True
        assert result.aborted_at == PipelineStage.APPLY
        assert "dry-run" in result.aborted_reason.lower()
        assert result.apply is None

    async def test_apply_failure_triggers_rollback(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test apply failure triggers auto-rollback."""
        pipeline = MockPipeline(mock_ctx, mock_deps)
        pipeline.apply_result = ApplyResult(
            success=False, output="Apply failed", rollback_data={"state": "backup"}
        )

        result = await pipeline.execute()

        assert result.success is False
        assert result.rollback_triggered is True
        assert result.rollback is not None
        assert result.rollback.success is True

    async def test_post_check_failure_triggers_rollback(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test post-check failure triggers rollback."""
        pipeline = MockPipeline(mock_ctx, mock_deps)
        pipeline.apply_result = ApplyResult(
            success=True, output="OK", rollback_data={"state": "backup"}
        )
        pipeline.post_check_result = PostCheckResult(success=False, checks_failed=["health"])

        result = await pipeline.execute()

        assert result.success is False
        assert result.rollback_triggered is True
        assert result.rollback_reason == "Post-check verification failed"

    async def test_no_rollback_when_disabled(self, mock_ctx: MagicMock) -> None:
        """Test no rollback when auto_rollback is disabled."""
        deps = PipelineDeps(target="test", task="test", auto_rollback=False)
        pipeline = MockPipeline(mock_ctx, deps)
        pipeline.apply_result = ApplyResult(success=False, output="Failed")

        result = await pipeline.execute()

        assert result.success is False
        assert result.rollback_triggered is False
        assert result.rollback is None

    def test_generate_summary(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test summary generation."""
        pipeline = MockPipeline(mock_ctx, mock_deps)
        plan = PlanResult(
            success=True,
            plan_output="OK",
            resources_affected=["resource1", "resource2"],
            warnings=["Deprecated feature used"],
        )
        diff = DiffResult(
            success=True,
            diff_output="OK",
            additions=3,
            modifications=2,
            deletions=1,
            risk_assessment="medium",
        )

        summary = pipeline._generate_summary(plan, diff)

        assert "mock" in summary
        assert "test-host" in summary
        assert "+ Additions: 3" in summary
        assert "~ Modifications: 2" in summary
        assert "- Deletions: 1" in summary
        assert "resource1" in summary
        assert "Deprecated feature used" in summary
        assert "medium" in summary

    def test_assess_risk_level(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test risk level assessment."""
        pipeline = MockPipeline(mock_ctx, mock_deps)

        # Critical: many deletions
        diff = DiffResult(success=True, diff_output="", deletions=10)
        assert pipeline._assess_risk_level(diff) == "critical"

        # High: some deletions
        diff = DiffResult(success=True, diff_output="", deletions=3)
        assert pipeline._assess_risk_level(diff) == "high"

        # High: many modifications
        diff = DiffResult(success=True, diff_output="", modifications=15)
        assert pipeline._assess_risk_level(diff) == "high"

        # Medium: some modifications
        diff = DiffResult(success=True, diff_output="", modifications=5)
        assert pipeline._assess_risk_level(diff) == "medium"

        # Low: only additions
        diff = DiffResult(success=True, diff_output="", additions=10)
        assert pipeline._assess_risk_level(diff) == "low"

    async def test_exception_during_apply_triggers_rollback(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test exception during apply triggers rollback."""
        pipeline = MockPipeline(mock_ctx, mock_deps)

        # Simulate exception during apply
        async def raise_exception() -> ApplyResult:
            raise RuntimeError("Connection lost")

        pipeline.apply = raise_exception  # type: ignore
        # Set rollback data to enable rollback
        pipeline._rollback_data = {"state": "backup"}

        result = await pipeline.execute()

        assert result.success is False
        assert result.aborted is True
        assert "Exception" in result.aborted_reason

    async def test_timing_recorded(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test timing is properly recorded."""
        pipeline = MockPipeline(mock_ctx, mock_deps)

        result = await pipeline.execute()

        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.completed_at >= result.started_at
        assert result.duration_ms >= 0

    async def test_hitl_approved_timestamp(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test HITL approval timestamp is set."""
        pipeline = MockPipeline(mock_ctx, mock_deps)

        result = await pipeline.execute()

        assert result.hitl_approved is True
        assert result.hitl_approved_at is not None
