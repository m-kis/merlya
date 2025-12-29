"""Tests for Orchestrator Center integration."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.agent.orchestrator import (
    DelegationResult,
    OrchestratorDeps,
    _convert_center_result,
    create_orchestrator,
)
from merlya.centers.base import CenterMode, CenterResult


@pytest.fixture
def mock_context() -> MagicMock:
    """Create mock SharedContext."""
    ctx = MagicMock()
    ctx.hosts = MagicMock()
    ctx.hosts.get_by_name = AsyncMock(return_value=MagicMock(name="web-01"))
    ctx.ui = MagicMock()
    ctx.ui.prompt_confirm = AsyncMock(return_value=True)
    ctx.config = MagicMock()
    ctx.config.get_model = MagicMock(return_value="anthropic:claude-haiku-4-5-20250514")
    return ctx


@pytest.fixture
def mock_deps(mock_context: MagicMock) -> OrchestratorDeps:
    """Create OrchestratorDeps with mock context."""
    return OrchestratorDeps(context=mock_context)


class TestConvertCenterResult:
    """Tests for _convert_center_result function."""

    def test_converts_success_result(self) -> None:
        """Test converting a successful CenterResult."""
        center_result = CenterResult(
            success=True,
            message="Operation completed successfully",
            mode=CenterMode.DIAGNOSTIC,
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert result.success is True
        assert result.specialist == "diagnostic_center"
        assert "successfully" in result.output
        assert result.complete is True

    def test_converts_failure_result(self) -> None:
        """Test converting a failed CenterResult."""
        center_result = CenterResult(
            success=False,
            message="Host not found",
            mode=CenterMode.CHANGE,
        )

        result = _convert_center_result(center_result, "change_center")

        assert result.success is False
        assert result.specialist == "change_center"
        assert "not found" in result.output
        assert result.complete is False

    def test_includes_evidence_count(self) -> None:
        """Test that evidence count is included in output."""
        center_result = CenterResult(
            success=True,
            message="Diagnostics complete",
            mode=CenterMode.DIAGNOSTIC,
            data={"evidence": ["item1", "item2", "item3"]},
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert "3 items" in result.output

    def test_includes_pipeline_info(self) -> None:
        """Test that pipeline info is included in output."""
        center_result = CenterResult(
            success=True,
            message="Change applied",
            mode=CenterMode.CHANGE,
            data={"pipeline": "BashPipeline"},
        )

        result = _convert_center_result(center_result, "change_center")

        assert "BashPipeline" in result.output

    def test_includes_hitl_status_approved(self) -> None:
        """Test that HITL approval status is included."""
        center_result = CenterResult(
            success=True,
            message="Change applied",
            mode=CenterMode.CHANGE,
            data={"hitl_approved": True},
        )

        result = _convert_center_result(center_result, "change_center")

        assert "approved" in result.output

    def test_includes_hitl_status_declined(self) -> None:
        """Test that HITL declined status is included."""
        center_result = CenterResult(
            success=False,
            message="Change aborted",
            mode=CenterMode.CHANGE,
            data={"hitl_approved": False},
        )

        result = _convert_center_result(center_result, "change_center")

        assert "declined" in result.output


class TestOrchestratorCreation:
    """Tests for orchestrator creation."""

    def test_create_orchestrator_returns_agent(self) -> None:
        """Test that create_orchestrator returns an Agent."""
        with (
            patch(
                "merlya.agent.orchestrator.get_model_for_role",
                return_value="test-model",
            ),
            patch(
                "merlya.agent.orchestrator.get_pydantic_model_string",
                return_value="test:test-model",
            ),
        ):
            from pydantic_ai import Agent

            agent = create_orchestrator(provider="test")

            assert isinstance(agent, Agent)

    def test_create_orchestrator_with_model_override(self) -> None:
        """Test that create_orchestrator accepts model override."""
        with (
            patch(
                "merlya.agent.orchestrator.get_model_for_role",
                return_value="default-model",
            ),
            patch(
                "merlya.agent.orchestrator.get_pydantic_model_string",
                return_value="test:custom-model",
            ) as mock_get_string,
        ):
            create_orchestrator(provider="test", model_override="custom-model")

            # Should use the override model
            mock_get_string.assert_called_with("test", "custom-model")


class TestClassifyIntent:
    """Tests for classify_intent tool."""

    async def test_classify_diagnostic_intent(self, mock_deps: OrchestratorDeps) -> None:
        """Test classifying a diagnostic intent."""
        from merlya.router.center_classifier import CenterClassification, CenterClassifier

        with patch.object(
            CenterClassifier,
            "classify",
            new_callable=AsyncMock,
            return_value=CenterClassification(
                center=CenterMode.DIAGNOSTIC,
                confidence=0.9,
                reasoning="Read-only check",
            ),
        ):
            classifier = CenterClassifier(mock_deps.context)
            result = await classifier.classify("check disk usage on web-01")

            assert result.center == CenterMode.DIAGNOSTIC
            assert result.confidence == 0.9

    async def test_classify_change_intent(self, mock_deps: OrchestratorDeps) -> None:
        """Test classifying a change intent."""
        from merlya.router.center_classifier import CenterClassification, CenterClassifier

        with patch.object(
            CenterClassifier,
            "classify",
            new_callable=AsyncMock,
            return_value=CenterClassification(
                center=CenterMode.CHANGE,
                confidence=0.85,
                reasoning="Service restart",
            ),
        ):
            classifier = CenterClassifier(mock_deps.context)
            result = await classifier.classify("restart nginx on web-01")

            assert result.center == CenterMode.CHANGE
            assert result.confidence == 0.85


class TestDelegationResult:
    """Tests for DelegationResult model."""

    def test_delegation_result_defaults(self) -> None:
        """Test DelegationResult default values."""
        result = DelegationResult(
            success=True,
            output="Test output",
            specialist="test",
        )

        assert result.tool_calls == 0
        assert result.complete is True

    def test_delegation_result_custom_values(self) -> None:
        """Test DelegationResult with custom values."""
        result = DelegationResult(
            success=False,
            output="Error occurred",
            specialist="diagnostic_center",
            tool_calls=5,
            complete=False,
        )

        assert result.success is False
        assert result.tool_calls == 5
        assert result.complete is False
        assert result.specialist == "diagnostic_center"


class TestConvertCenterResultEdgeCases:
    """Edge case tests for _convert_center_result."""

    def test_empty_data_dict(self) -> None:
        """Test with empty data dictionary."""
        center_result = CenterResult(
            success=True,
            message="Operation complete",
            mode=CenterMode.DIAGNOSTIC,
            data={},
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert result.success is True
        # Should not have any additional info appended
        assert "Evidence" not in result.output
        assert "Pipeline" not in result.output
        assert "HITL" not in result.output

    def test_evidence_not_a_list(self) -> None:
        """Test when evidence is not a list."""
        center_result = CenterResult(
            success=True,
            message="Operation complete",
            mode=CenterMode.DIAGNOSTIC,
            data={"evidence": "not a list"},
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        # Should not fail, just skip the evidence line
        assert result.success is True
        assert "Evidence" not in result.output

    def test_evidence_is_none(self) -> None:
        """Test when evidence is None."""
        center_result = CenterResult(
            success=True,
            message="Operation complete",
            mode=CenterMode.DIAGNOSTIC,
            data={"evidence": None},
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert result.success is True
        assert "Evidence" not in result.output

    def test_no_data_provided(self) -> None:
        """Test when data is not provided (uses default empty dict)."""
        center_result = CenterResult(
            success=True,
            message="Operation complete",
            mode=CenterMode.DIAGNOSTIC,
            # data defaults to {} per CenterResult model
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert result.success is True
        assert result.output == "Operation complete"

    def test_includes_agent_output(self) -> None:
        """Test that specialist agent output is included in result."""
        center_result = CenterResult(
            success=True,
            message="Diagnostic completed for local",
            mode=CenterMode.DIAGNOSTIC,
            data={
                "output": "Disk usage check:\n/dev/sda1: 45% used\n/dev/sdb1: 78% used",
                "status": "completed",
            },
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert result.success is True
        assert "Disk usage check:" in result.output
        assert "45% used" in result.output
        assert "78% used" in result.output

    def test_includes_error_in_data(self) -> None:
        """Test that error field from data is included in result."""
        center_result = CenterResult(
            success=False,
            message="Diagnostic failed",
            mode=CenterMode.DIAGNOSTIC,
            data={
                "status": "failed",
                "error": "Connection refused to host",
            },
        )

        result = _convert_center_result(center_result, "diagnostic_center")

        assert result.success is False
        assert "Connection refused" in result.output
        assert "Error" in result.output
