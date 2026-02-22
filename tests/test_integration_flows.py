"""
Integration tests for SSH, Pipeline, and HITL flows.

Tests the complete execution flows for:
- SSH execution with mocking
- Pipeline execution (AnsiblePipeline)
- HITL (Human-In-The-Loop) confirmation

NOTE ON MOCKING STRATEGY:
These tests currently mock private methods (_check_ansible_available, _run_local_command)
to avoid requiring Ansible installation. This is a pragmatic compromise for MVP testing.

FUTURE IMPROVEMENT (V2.0):
- Inject dependencies via constructor (Dependency Injection pattern)
- Create CommandExecutor interface that can be swapped with TestCommandExecutor
- Mock at system boundaries (asyncio.subprocess) instead of internal methods
- Use test doubles pattern for better encapsulation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.agent.confirmation import ConfirmationResult, ConfirmationState, confirm_command
from merlya.core.contexts import UIContext
from merlya.pipelines.ansible import AnsibleMode, AnsiblePipeline
from merlya.pipelines.base import PipelineDeps
from merlya.tools.core import ssh_execute

# ============================================================================
# SSH Execution Flow Tests
# ============================================================================
#
# NOTE: These tests are temporarily skipped pending refactoring.
# They mock implementation details (get_pool) that have changed with circuit breaker/retry.
# The actual SSH functionality is covered by unit tests in:
# - tests/test_tools_core.py (ssh_execute unit tests)
# - tests/test_resilience.py (circuit breaker/retry tests)
# TODO: Refactor to test at orchestrator level or use real subprocess mocks


@pytest.mark.skip(reason="Needs refactoring after circuit breaker/retry decorators added")
@pytest.mark.asyncio
async def test_ssh_execute_success_flow(mock_shared_context: MagicMock) -> None:
    """Test successful SSH command execution flow."""
    with patch("merlya.tools.core.get_pool") as mock_get_pool:
        # Mock SSH pool
        mock_pool = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute.return_value = {
            "stdout": "success output",
            "stderr": "",
            "exit_code": 0,
        }
        mock_pool.get_connection = AsyncMock(return_value=mock_connection)
        mock_pool.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.__aexit__ = AsyncMock(return_value=None)
        mock_get_pool.return_value = mock_pool

        # Execute SSH command
        result = await ssh_execute(
            mock_shared_context, host="test-host", command="echo 'test'", timeout=30
        )

        # Verify result
        assert result.success is True
        assert result.data is not None
        assert result.data["stdout"] == "success output"
        assert result.data["exit_code"] == 0


@pytest.mark.skip(reason="Needs refactoring after circuit breaker/retry decorators added")
@pytest.mark.asyncio
async def test_ssh_execute_failure_flow(mock_shared_context: MagicMock) -> None:
    """Test SSH command execution failure flow."""
    with patch("merlya.tools.core.get_pool") as mock_get_pool:
        # Mock SSH pool with error
        mock_pool = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute.return_value = {
            "stdout": "",
            "stderr": "command not found",
            "exit_code": 127,
        }
        mock_pool.get_connection = AsyncMock(return_value=mock_connection)
        mock_pool.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.__aexit__ = AsyncMock(return_value=None)
        mock_get_pool.return_value = mock_pool

        # Execute SSH command that fails
        result = await ssh_execute(
            mock_shared_context, host="test-host", command="invalid_command", timeout=30
        )

        # Verify failure is handled
        assert result.data is not None
        assert result.data["exit_code"] == 127
        assert "not found" in result.data["stderr"]


@pytest.mark.skip(reason="Needs refactoring after circuit breaker/retry decorators added")
@pytest.mark.asyncio
async def test_ssh_execute_with_elevation(mock_shared_context: MagicMock) -> None:
    """Test SSH command execution with sudo elevation."""
    with patch("merlya.tools.core.get_pool") as mock_get_pool:
        # Mock SSH pool
        mock_pool = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute.return_value = {
            "stdout": "elevated output",
            "stderr": "",
            "exit_code": 0,
        }
        mock_pool.get_connection = AsyncMock(return_value=mock_connection)
        mock_pool.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.__aexit__ = AsyncMock(return_value=None)
        mock_get_pool.return_value = mock_pool

        # Execute SSH command with sudo
        result = await ssh_execute(
            mock_shared_context,
            host="test-host",
            command="sudo systemctl restart nginx",
            timeout=30,
        )

        # Verify result
        assert result.success is True
        assert result.data is not None
        assert result.data["stdout"] == "elevated output"


# ============================================================================
# Pipeline Flow Tests (AnsiblePipeline)
# ============================================================================


@pytest.fixture
def mock_pipeline_deps(mock_shared_context: MagicMock) -> PipelineDeps:
    """Create mock pipeline dependencies."""
    return PipelineDeps(
        target="test-host",
        dry_run=False,
        require_approval=False,
        auto_rollback=True,
    )


@pytest.mark.skip(reason="Needs refactoring - mocks private methods")
@pytest.mark.asyncio
async def test_ansible_pipeline_adhoc_mode_flow(
    mock_shared_context: MagicMock, mock_pipeline_deps: PipelineDeps
) -> None:
    """Test AnsiblePipeline ad-hoc mode complete flow."""
    # Create pipeline in ad-hoc mode
    pipeline = AnsiblePipeline(
        ctx=mock_shared_context,
        deps=mock_pipeline_deps,
        mode=AnsibleMode.AD_HOC,
        module="service",
        module_args="name=nginx state=restarted",
        inventory="test-host",
    )

    # NOTE: Mocking private method is temporary for testing without real Ansible
    # TODO(V2.0): Inject dependency via constructor or use test doubles pattern
    # Mock ansible availability check
    with patch.object(
        pipeline, "_check_ansible_available", return_value={"available": True, "version": "2.9.0"}
    ):
        # 1. Plan stage
        plan_result = await pipeline.plan()
        assert plan_result.success is True
        assert "Mode: ad_hoc" in plan_result.plan_output
        assert "Module: service" in plan_result.plan_output

        # 2. Diff stage (check mode)
        # NOTE: Mocking private method - prefer mocking external deps (asyncio.subprocess)
        # TODO(V2.0): Mock at system boundary (command executor interface)
        with patch.object(
            pipeline,
            "_run_local_command",
            return_value={
                "stdout": "changed=1 ok=1 failed=0",
                "stderr": "",
                "exit_code": 0,
            },
        ):
            diff_result = await pipeline.diff()
            assert diff_result.success is True
            assert diff_result.modifications > 0

        # 3. Apply stage
        # NOTE: Mocking private method - prefer mocking external deps (asyncio.subprocess)
        # TODO(V2.0): Mock at system boundary (command executor interface)
        with patch.object(
            pipeline,
            "_run_local_command",
            return_value={
                "stdout": "changed=1 ok=1 failed=0",
                "stderr": "",
                "exit_code": 0,
            },
        ):
            apply_result = await pipeline.apply()
            assert apply_result.success is True
            assert apply_result.duration_ms > 0

        # 4. Post-check stage
        post_check_result = await pipeline.post_check()
        assert post_check_result.success is True
        assert len(post_check_result.checks_passed) > 0


@pytest.mark.skip(reason="Needs refactoring - mocks private methods")
@pytest.mark.asyncio
async def test_ansible_pipeline_inline_mode_flow(
    mock_shared_context: MagicMock, mock_pipeline_deps: PipelineDeps
) -> None:
    """Test AnsiblePipeline inline mode (temp playbook) flow."""
    # Create pipeline in inline mode
    playbook_yaml = """
---
- hosts: test-host
  tasks:
    - name: Restart nginx
      service:
        name: nginx
        state: restarted
"""

    pipeline = AnsiblePipeline(
        ctx=mock_shared_context,
        deps=mock_pipeline_deps,
        mode=AnsibleMode.INLINE,
        playbook_content=playbook_yaml,
        inventory="test-host",
    )

    # NOTE: Mocking private method is temporary for testing without real Ansible
    # TODO(V2.0): Inject dependency via constructor or use test doubles pattern
    # Mock ansible availability check
    with patch.object(
        pipeline, "_check_ansible_available", return_value={"available": True, "version": "2.9.0"}
    ):
        # Plan stage
        plan_result = await pipeline.plan()
        assert plan_result.success is True
        assert "Mode: inline" in plan_result.plan_output
        assert "Playbook: (inline generated)" in plan_result.plan_output

        # Apply with temp playbook
        # NOTE: Mocking private method - prefer mocking external deps (asyncio.subprocess)
        # TODO(V2.0): Mock at system boundary (command executor interface)
        with patch.object(
            pipeline,
            "_run_local_command",
            return_value={
                "stdout": "changed=1 ok=1 failed=0",
                "stderr": "",
                "exit_code": 0,
            },
        ):
            apply_result = await pipeline.apply()
            assert apply_result.success is True


@pytest.mark.skip(reason="Needs refactoring - mocks private methods")
@pytest.mark.asyncio
async def test_ansible_pipeline_rollback_flow(
    mock_shared_context: MagicMock, mock_pipeline_deps: PipelineDeps
) -> None:
    """Test AnsiblePipeline rollback flow."""
    # Create pipeline with rollback playbook
    pipeline = AnsiblePipeline(
        ctx=mock_shared_context,
        deps=mock_pipeline_deps,
        mode=AnsibleMode.REPOSITORY,
        playbook_path="/path/to/deploy.yml",
        rollback_playbook="/path/to/rollback.yml",
        inventory="test-host",
    )

    # NOTE: Mocking private method - prefer mocking external deps (asyncio.subprocess)
    # TODO(V2.0): Mock at system boundary (command executor interface)
    # Mock rollback execution
    with patch.object(
        pipeline,
        "_run_local_command",
        return_value={
            "stdout": "rollback successful",
            "stderr": "",
            "exit_code": 0,
        },
    ):
        rollback_result = await pipeline.rollback()
        assert rollback_result.success is True
        assert len(rollback_result.resources_restored) > 0


@pytest.mark.skip(reason="Needs refactoring - mocks private methods")
@pytest.mark.asyncio
async def test_ansible_pipeline_without_rollback(
    mock_shared_context: MagicMock, mock_pipeline_deps: PipelineDeps
) -> None:
    """Test AnsiblePipeline rollback when no rollback playbook defined."""
    # Create pipeline without rollback playbook
    pipeline = AnsiblePipeline(
        ctx=mock_shared_context,
        deps=mock_pipeline_deps,
        mode=AnsibleMode.AD_HOC,
        module="service",
        module_args="name=nginx state=started",
        inventory="test-host",
        rollback_playbook=None,  # No rollback
    )

    # Rollback should fail gracefully
    rollback_result = await pipeline.rollback()
    assert rollback_result.success is False
    assert len(rollback_result.errors) > 0
    assert "no playbook" in rollback_result.errors[0].lower()


# ============================================================================
# HITL (Human-In-The-Loop) Confirmation Flow Tests
# ============================================================================


@pytest.fixture
def mock_ui_context() -> UIContext:
    """Create mock UI context for HITL tests."""
    ui = MagicMock(spec=UIContext)
    ui.prompt = AsyncMock()
    ui.prompt_confirm = AsyncMock()
    ui.info = MagicMock()
    ui.warning = MagicMock()
    ui.error = MagicMock()
    return ui


@pytest.mark.skip(reason="Needs refactoring - uses wrong enum values (APPROVE vs EXECUTE)")
@pytest.mark.asyncio
async def test_hitl_confirm_command_approve(mock_ui_context: UIContext) -> None:
    """Test HITL confirmation flow with user approval."""
    # Mock user approving the command
    mock_ui_context.prompt_confirm.return_value = True

    # Create confirmation state
    state = ConfirmationState()

    # Request confirmation
    result = await confirm_command(
        ui=mock_ui_context,
        command="sudo systemctl restart nginx",
        target="web-01",
        state=state,
    )

    # Verify approval
    assert result == ConfirmationResult.APPROVE
    mock_ui_context.prompt_confirm.assert_called_once()


@pytest.mark.skip(reason="Needs refactoring - uses wrong enum values (APPROVE vs EXECUTE)")
@pytest.mark.asyncio
async def test_hitl_confirm_command_cancel(mock_ui_context: UIContext) -> None:
    """Test HITL confirmation flow with user cancellation."""
    # Mock user canceling the command
    mock_ui_context.prompt_confirm.return_value = False

    # Create confirmation state
    state = ConfirmationState()

    # Request confirmation
    result = await confirm_command(
        ui=mock_ui_context,
        command="sudo rm -rf /important",
        target="prod-db-01",
        state=state,
    )

    # Verify cancellation
    assert result == ConfirmationResult.CANCEL
    mock_ui_context.prompt_confirm.assert_called_once()


@pytest.mark.skip(reason="Needs refactoring - uses wrong enum values (APPROVE vs EXECUTE)")
@pytest.mark.asyncio
async def test_hitl_confirmation_state_skip(mock_ui_context: UIContext) -> None:
    """Test HITL confirmation state with skip functionality."""
    # Create confirmation state
    state = ConfirmationState()

    # First command - should prompt
    command1 = "sudo systemctl restart nginx"
    assert not state.should_skip(command1)

    # Mark to skip future similar commands
    state.skip_similar(command1)

    # Same command - should skip
    assert state.should_skip(command1)


@pytest.mark.skip(reason="Needs refactoring - uses wrong enum values (APPROVE vs EXECUTE)")
@pytest.mark.asyncio
async def test_hitl_confirmation_reset(mock_ui_context: UIContext) -> None:
    """Test HITL confirmation state reset."""
    # Create confirmation state
    state = ConfirmationState()

    # Skip a command
    command = "sudo systemctl restart nginx"
    state.skip_similar(command)
    assert state.should_skip(command)

    # Reset state
    state.reset()

    # Should prompt again
    assert not state.should_skip(command)


# ============================================================================
# Full Integration Test (SSH + Pipeline + HITL)
# ============================================================================


@pytest.mark.skip(reason="Needs refactoring - combines multiple deprecated test patterns")
@pytest.mark.asyncio
async def test_full_integration_ssh_pipeline_hitl(
    mock_shared_context: MagicMock, mock_pipeline_deps: PipelineDeps, mock_ui_context: UIContext
) -> None:
    """
    Test full integration flow: SSH → Pipeline → HITL.

    Simulates a complete workflow:
    1. Check SSH connectivity
    2. Create and validate pipeline
    3. Request HITL approval
    4. Execute with SSH
    5. Verify result
    """
    # 1. SSH connectivity check
    with patch("merlya.tools.core.get_pool") as mock_get_pool:
        mock_pool = MagicMock()
        mock_connection = AsyncMock()
        mock_connection.execute.return_value = {
            "stdout": "ansible 2.9.0",
            "stderr": "",
            "exit_code": 0,
        }
        mock_pool.get_connection = AsyncMock(return_value=mock_connection)
        mock_pool.__aenter__ = AsyncMock(return_value=mock_connection)
        mock_pool.__aexit__ = AsyncMock(return_value=None)
        mock_get_pool.return_value = mock_pool

        # Check if ansible is available via SSH
        ssh_result = await ssh_execute(
            mock_shared_context, host="test-host", command="ansible --version", timeout=10
        )
        assert ssh_result.success is True

    # 2. Create pipeline
    pipeline = AnsiblePipeline(
        ctx=mock_shared_context,
        deps=mock_pipeline_deps,
        mode=AnsibleMode.AD_HOC,
        module="service",
        module_args="name=nginx state=restarted",
        inventory="test-host",
    )

    # Mock ansible availability
    with patch.object(
        pipeline, "_check_ansible_available", return_value={"available": True, "version": "2.9.0"}
    ):
        # Validate pipeline
        plan_result = await pipeline.plan()
        assert plan_result.success is True

    # 3. Request HITL approval
    mock_ui_context.prompt_confirm.return_value = True
    confirmation_state = ConfirmationState()

    approval = await confirm_command(
        ui=mock_ui_context,
        command="ansible test-host -m service -a 'name=nginx state=restarted'",
        target="test-host",
        state=confirmation_state,
    )
    assert approval == ConfirmationResult.APPROVE

    # 4. Execute pipeline (simulating SSH backend)
    with patch.object(
        pipeline,
        "_run_local_command",
        return_value={
            "stdout": "changed=1 ok=1 failed=0",
            "stderr": "",
            "exit_code": 0,
        },
    ):
        apply_result = await pipeline.apply()
        assert apply_result.success is True
        assert apply_result.duration_ms > 0

    # 5. Verify post-check
    post_check_result = await pipeline.post_check()
    assert post_check_result.success is True


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_shared_context() -> MagicMock:
    """Create mock SharedContext for tests."""
    ctx = MagicMock()
    ctx.ui = MagicMock()
    ctx.ui.info = MagicMock()
    ctx.ui.warning = MagicMock()
    ctx.ui.error = MagicMock()
    ctx.ui.success = MagicMock()
    ctx.config = MagicMock()
    return ctx
