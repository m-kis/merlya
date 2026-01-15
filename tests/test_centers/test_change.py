"""Tests for ChangeCenter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.capabilities.models import (
    HostCapabilities,
    LocalCapabilities,
    SSHCapability,
    ToolCapability,
    ToolName,
)
from merlya.centers.base import CenterDeps, CenterMode, RiskLevel
from merlya.centers.change import ChangeCenter
from merlya.pipelines.base import (
    ApplyResult,
    PipelineResult,
    PostCheckResult,
)


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create mock shared context."""
    ctx = MagicMock()
    ctx.hosts = MagicMock()
    ctx.hosts.get_by_name = AsyncMock(return_value=MagicMock(name="web-01"))
    ctx.hosts.get_by_hostname = AsyncMock(return_value=None)
    ctx.hosts.get_all = AsyncMock(return_value=[])
    ctx.session = MagicMock()
    ctx.session.last_remote_target = None
    ctx.ui = MagicMock()
    ctx.ui.prompt_confirm = AsyncMock(return_value=True)
    ctx.auto_confirm = False
    return ctx


@pytest.fixture
def mock_capabilities() -> MagicMock:
    """Create mock capability detector."""
    detector = MagicMock()
    caps = LocalCapabilities(
        tools=[
            ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
        ],
        web_access=True,
    )
    detector.detect_local = AsyncMock(return_value=caps)
    detector.detect_host = AsyncMock(
        return_value=HostCapabilities(
            host_name="web-01",
            ssh=SSHCapability(available=True),
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
            ],
        )
    )
    return detector


@pytest.fixture
def center(mock_ctx: MagicMock, mock_capabilities: MagicMock) -> ChangeCenter:
    """Create ChangeCenter with mock context."""
    return ChangeCenter(mock_ctx, mock_capabilities)


class TestChangeCenterProperties:
    """Tests for ChangeCenter properties."""

    def test_mode_is_change(self, center: ChangeCenter) -> None:
        """Test center mode is CHANGE."""
        assert center.mode == CenterMode.CHANGE

    def test_risk_level_is_high(self, center: ChangeCenter) -> None:
        """Test risk level is HIGH."""
        assert center.risk_level == RiskLevel.HIGH

    def test_allowed_tools_contains_write_tools(self, center: ChangeCenter) -> None:
        """Test allowed tools list contains expected tools."""
        tools = center.allowed_tools
        assert "execute_pipeline" in tools
        assert "ssh_execute" in tools
        assert "write_file" in tools
        assert "request_credentials" in tools

    def test_allowed_tools_is_list(self, center: ChangeCenter) -> None:
        """Test allowed_tools returns a list."""
        assert isinstance(center.allowed_tools, list)


class TestChangeCenterExecute:
    """Tests for ChangeCenter.execute method."""

    async def test_execute_returns_result(
        self,
        center: ChangeCenter,
        mock_ctx: MagicMock,
    ) -> None:
        """Test execute returns a CenterResult."""
        deps = CenterDeps(target="local", task="restart nginx")

        result = await center.execute(deps)

        assert result.mode == CenterMode.CHANGE
        # Will fail because no commands extracted (expected behavior)
        assert result.success is False

    async def test_execute_fails_for_unknown_host(
        self,
        center: ChangeCenter,
        mock_ctx: MagicMock,
    ) -> None:
        """Test execute fails for unknown host."""
        mock_ctx.hosts.get_by_name = AsyncMock(return_value=None)

        deps = CenterDeps(target="unknown-host", task="deploy app")

        result = await center.execute(deps)

        assert result.success is False
        assert "not found" in result.message

    async def test_execute_detects_capabilities(
        self,
        center: ChangeCenter,
        mock_ctx: MagicMock,
        mock_capabilities: MagicMock,
    ) -> None:
        """Test execute calls capability detector."""
        deps = CenterDeps(target="local", task="install package")

        await center.execute(deps)

        mock_capabilities.detect_local.assert_called_once()


class TestPipelineSelection:
    """Tests for pipeline selection logic."""

    async def test_selects_no_pipeline_without_commands(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test returns None when no commands can be extracted."""

        caps = LocalCapabilities(tools=[], web_access=True)
        deps = CenterDeps(target="local", task="do something vague")

        pipeline = await center._select_pipeline(deps, caps)

        # No pipeline because no commands extracted
        assert pipeline is None

    async def test_ansible_keywords_detected(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test Ansible keywords are recognized."""

        caps = LocalCapabilities(
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
            ],
        )
        deps = CenterDeps(target="local", task="run ansible playbook to deploy")

        # Currently returns None because AnsiblePipeline not implemented
        # but the method should recognize the keywords
        with patch.object(center, "_try_ansible_pipeline", new_callable=AsyncMock) as mock:
            mock.return_value = None
            await center._select_pipeline(deps, caps)
            mock.assert_called_once()


class TestResultFormatting:
    """Tests for pipeline result formatting."""

    def test_format_aborted_result(self, center: ChangeCenter) -> None:
        """Test formatting aborted pipeline result."""
        result = PipelineResult(
            success=False,
            aborted=True,
            aborted_reason="User declined",
        )

        formatted = center._format_pipeline_result(result)

        assert "aborted" in formatted.lower()
        assert "User declined" in formatted

    def test_format_success_result(self, center: ChangeCenter) -> None:
        """Test formatting successful pipeline result."""
        result = PipelineResult(
            success=True,
            apply=ApplyResult(
                success=True,
                output="done",
                resources_created=["resource1"],
                resources_modified=["resource2"],
            ),
            post_check=PostCheckResult(success=True, checks_passed=["check1"]),
            duration_ms=1500,
        )

        formatted = center._format_pipeline_result(result)

        assert "successfully" in formatted.lower()
        assert "Created: 1" in formatted
        assert "Modified: 1" in formatted
        assert "1500ms" in formatted

    def test_format_failed_with_rollback(self, center: ChangeCenter) -> None:
        """Test formatting failed result with rollback."""
        from merlya.pipelines.base import RollbackResult

        result = PipelineResult(
            success=False,
            rollback_triggered=True,
            rollback_reason="Post-check failed",
            rollback=RollbackResult(
                success=True,
                output="Rolled back",
                resources_restored=["resource1"],
            ),
        )

        formatted = center._format_pipeline_result(result)

        assert "failed" in formatted.lower()
        assert "Rollback triggered" in formatted
        assert "successful" in formatted.lower()


class TestCapabilityDetection:
    """Tests for capability detection integration."""

    async def test_uses_provided_detector(
        self,
        center: ChangeCenter,
        mock_capabilities: MagicMock,
    ) -> None:
        """Test uses provided capability detector."""
        CenterDeps(target="local", task="test")

        await center._get_capabilities("local", None)

        mock_capabilities.detect_local.assert_called_once()

    async def test_creates_detector_if_none(
        self,
        mock_ctx: MagicMock,
    ) -> None:
        """Test creates detector if none provided."""
        center = ChangeCenter(mock_ctx, capabilities=None)

        with patch("merlya.capabilities.detector.CapabilityDetector") as mock_detector_class:
            mock_instance = MagicMock()
            mock_instance.detect_local = AsyncMock(return_value=LocalCapabilities(tools=[]))
            mock_detector_class.return_value = mock_instance

            await center._get_capabilities("local", None)

            mock_detector_class.assert_called_once_with(mock_ctx)

    async def test_detects_host_capabilities(
        self,
        center: ChangeCenter,
        mock_ctx: MagicMock,
        mock_capabilities: MagicMock,
    ) -> None:
        """Test detects host capabilities for remote target."""
        host = MagicMock()
        host.name = "web-01"

        await center._get_capabilities("web-01", host)

        mock_capabilities.detect_host.assert_called_once_with(host)


class TestAvailableTools:
    """Tests for listing available tools."""

    def test_list_available_tools(self, center: ChangeCenter) -> None:
        """Test listing available tools from capabilities."""
        caps = LocalCapabilities(
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
                ToolCapability(name=ToolName.TERRAFORM, installed=True, config_valid=False),
                ToolCapability(name=ToolName.GIT, installed=False, config_valid=False),
            ],
        )

        tools = center._list_available_tools(caps)

        assert "ansible" in tools
        assert "terraform" not in tools  # config_valid=False
        assert "git" not in tools  # installed=False


class TestLastResult:
    """Tests for last_result property."""

    def test_last_result_initially_none(self, center: ChangeCenter) -> None:
        """Test last_result is None initially."""
        assert center.last_result is None


class TestTryProvisioner:
    """Tests for _try_provisioner method."""

    async def test_returns_none_without_iac_operation(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test returns None when no iac_operation in extra."""
        deps = CenterDeps(target="local", task="restart nginx")

        result = await center._try_provisioner(deps)

        assert result is None

    async def test_returns_none_for_unknown_operation(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test returns None for unknown IaC operation."""
        deps = CenterDeps(
            target="local",
            task="do something",
            extra={"iac_operation": "unknown_op"},
        )

        result = await center._try_provisioner(deps)

        assert result is None

    async def test_maps_provision_to_create(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test provision operation maps to CREATE action."""
        from merlya.provisioners.base import ProvisionerAction

        deps = CenterDeps(
            target="local",
            task="create vm",
            extra={
                "iac_operation": "provision",
                "cloud_provider": "aws",
            },
        )

        with patch("merlya.provisioners.registry.ProvisionerRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry
            mock_provisioner = MagicMock()
            mock_registry.get.return_value = mock_provisioner
            mock_provisioner.execute = AsyncMock(return_value=MagicMock())

            await center._try_provisioner(deps)

            # Verify registry.get was called with ProvisionerDeps containing correct action
            mock_registry.get.assert_called_once()
            call_args = mock_registry.get.call_args[0][0]
            assert call_args.action == ProvisionerAction.CREATE
            # Verify provisioner.execute was called
            mock_provisioner.execute.assert_called_once()

    async def test_maps_destroy_to_delete(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test destroy operation maps to DELETE action."""
        from merlya.provisioners.base import ProvisionerAction

        deps = CenterDeps(
            target="local",
            task="destroy vm",
            extra={
                "iac_operation": "destroy",
                "cloud_provider": "aws",
            },
        )

        with patch("merlya.provisioners.registry.ProvisionerRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry
            mock_provisioner = MagicMock()
            mock_registry.get.return_value = mock_provisioner
            mock_provisioner.execute = AsyncMock(return_value=MagicMock())

            await center._try_provisioner(deps)

            call_args = mock_registry.get.call_args[0][0]
            assert call_args.action == ProvisionerAction.DELETE

    async def test_returns_none_when_no_provisioner(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test returns None when no provisioner available."""
        deps = CenterDeps(
            target="local",
            task="create vm",
            extra={
                "iac_operation": "provision",
                "cloud_provider": "unknown_provider",
            },
        )

        with patch("merlya.provisioners.registry.ProvisionerRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry
            mock_registry.get.side_effect = ValueError("No provisioner for unknown_provider")

            result = await center._try_provisioner(deps)

            assert result is None

    async def test_returns_failed_result_on_exception(
        self,
        center: ChangeCenter,
    ) -> None:
        """Test returns failed result on provisioner exception."""
        deps = CenterDeps(
            target="local",
            task="create vm",
            extra={
                "iac_operation": "provision",
                "cloud_provider": "aws",
            },
        )

        with patch("merlya.provisioners.registry.ProvisionerRegistry") as mock_registry_cls:
            mock_registry = MagicMock()
            mock_registry_cls.get_instance.return_value = mock_registry
            mock_provisioner = MagicMock()
            mock_registry.get.return_value = mock_provisioner
            mock_provisioner.execute = AsyncMock(side_effect=RuntimeError("Test error"))

            result = await center._try_provisioner(deps)

            assert result is not None
            assert result.success is False
            assert result.aborted is True
            assert "Test error" in result.aborted_reason


class TestFormatProvisionerResult:
    """Tests for _format_provisioner_result method."""

    def test_format_aborted_result(self, center: ChangeCenter) -> None:
        """Test formatting aborted provisioner result."""
        from merlya.provisioners.base import ProvisionerAction, ProvisionerResult

        result = ProvisionerResult(
            success=False,
            action=ProvisionerAction.CREATE,
            aborted=True,
            aborted_reason="User declined",
        )

        formatted = center._format_provisioner_result(result)

        assert "aborted" in formatted.lower()
        assert "User declined" in formatted

    def test_format_success_create_result(self, center: ChangeCenter) -> None:
        """Test formatting successful CREATE result."""
        from merlya.provisioners.base import ApplyOutput, ProvisionerAction, ProvisionerResult

        result = ProvisionerResult(
            success=True,
            action=ProvisionerAction.CREATE,
            apply=ApplyOutput(
                success=True,
                resources_created=["r1", "r2", "r3"],
                outputs={"instance_id": "i-12345", "public_ip": "1.2.3.4"},
            ),
            duration_seconds=2.5,
        )

        formatted = center._format_provisioner_result(result)

        assert "successfully" in formatted.lower()
        assert "Created: 3" in formatted
        assert "instance_id" in formatted
        assert "2500ms" in formatted

    def test_format_success_update_result(self, center: ChangeCenter) -> None:
        """Test formatting successful UPDATE result."""
        from merlya.provisioners.base import ApplyOutput, ProvisionerAction, ProvisionerResult

        result = ProvisionerResult(
            success=True,
            action=ProvisionerAction.UPDATE,
            apply=ApplyOutput(
                success=True,
                resources_updated=["r1", "r2"],
            ),
        )

        formatted = center._format_provisioner_result(result)

        assert "Updated: 2" in formatted

    def test_format_success_delete_result(self, center: ChangeCenter) -> None:
        """Test formatting successful DELETE result."""
        from merlya.provisioners.base import ApplyOutput, ProvisionerAction, ProvisionerResult

        result = ProvisionerResult(
            success=True,
            action=ProvisionerAction.DELETE,
            apply=ApplyOutput(
                success=True,
                resources_deleted=["r1"],
            ),
        )

        formatted = center._format_provisioner_result(result)

        assert "Deleted: 1" in formatted

    def test_format_failed_result(self, center: ChangeCenter) -> None:
        """Test formatting failed provisioner result."""
        from merlya.provisioners.base import ApplyOutput, ProvisionerAction, ProvisionerResult

        result = ProvisionerResult(
            success=False,
            action=ProvisionerAction.CREATE,
            apply=ApplyOutput(
                success=False,
                rollback_data={"state": "previous"},
            ),
        )

        formatted = center._format_provisioner_result(result)

        assert "failed" in formatted.lower()
        assert "Rollback data available" in formatted

    def test_format_truncates_long_outputs(self, center: ChangeCenter) -> None:
        """Test output values are truncated if too long."""
        from merlya.provisioners.base import ApplyOutput, ProvisionerAction, ProvisionerResult

        result = ProvisionerResult(
            success=True,
            action=ProvisionerAction.CREATE,
            apply=ApplyOutput(
                success=True,
                outputs={"long_value": "x" * 100},
            ),
        )

        formatted = center._format_provisioner_result(result)

        assert "..." in formatted
        assert "x" * 100 not in formatted
