"""Tests for capabilities models."""

from datetime import UTC, datetime, timedelta

from merlya.capabilities.models import (
    HostCapabilities,
    LocalCapabilities,
    SSHCapability,
    ToolCapability,
    ToolName,
)


class TestToolCapability:
    """Tests for ToolCapability model."""

    def test_create_installed_tool(self) -> None:
        """Test creating an installed tool capability."""
        cap = ToolCapability(
            name=ToolName.ANSIBLE,
            installed=True,
            version="2.14.0",
            config_valid=True,
        )
        assert cap.name == ToolName.ANSIBLE
        assert cap.installed is True
        assert cap.version == "2.14.0"
        assert cap.config_valid is True

    def test_create_not_installed_tool(self) -> None:
        """Test creating a not-installed tool capability."""
        cap = ToolCapability(name=ToolName.TERRAFORM, installed=False)
        assert cap.installed is False
        assert cap.version is None
        assert cap.config_valid is False

    def test_str_representation_installed(self) -> None:
        """Test string representation for installed tool."""
        cap = ToolCapability(
            name=ToolName.KUBECTL,
            installed=True,
            version="1.28.0",
            config_valid=True,
        )
        assert "kubectl" in str(cap)
        assert "1.28.0" in str(cap)
        assert "valid" in str(cap)

    def test_str_representation_not_installed(self) -> None:
        """Test string representation for not installed tool."""
        cap = ToolCapability(name=ToolName.HELM, installed=False)
        assert "helm" in str(cap)
        assert "not installed" in str(cap)


class TestSSHCapability:
    """Tests for SSHCapability model."""

    def test_create_available_ssh(self) -> None:
        """Test creating an available SSH capability."""
        cap = SSHCapability(
            available=True,
            read_only=False,
            auth_method="key",
        )
        assert cap.available is True
        assert cap.read_only is False
        assert cap.auth_method == "key"

    def test_create_unavailable_ssh(self) -> None:
        """Test creating an unavailable SSH capability."""
        cap = SSHCapability(
            available=False,
            connection_error="Connection refused",
        )
        assert cap.available is False
        assert cap.connection_error == "Connection refused"


class TestHostCapabilities:
    """Tests for HostCapabilities model."""

    def test_create_host_capabilities(self) -> None:
        """Test creating host capabilities."""
        caps = HostCapabilities(
            host_name="web-01",
            ssh=SSHCapability(available=True),
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
                ToolCapability(name=ToolName.GIT, installed=True, config_valid=True),
            ],
            web_access=True,
        )
        assert caps.host_name == "web-01"
        assert caps.ssh.available is True
        assert len(caps.tools) == 2

    def test_has_tool_returns_true_for_installed_valid_tool(self) -> None:
        """Test has_tool returns True for installed and valid tool."""
        caps = HostCapabilities(
            host_name="test-host",
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
            ],
        )
        assert caps.has_tool(ToolName.ANSIBLE) is True
        assert caps.has_tool("ansible") is True

    def test_has_tool_returns_false_for_not_installed(self) -> None:
        """Test has_tool returns False for not installed tool."""
        caps = HostCapabilities(
            host_name="test-host",
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=False),
            ],
        )
        assert caps.has_tool(ToolName.ANSIBLE) is False

    def test_has_tool_returns_false_for_invalid_config(self) -> None:
        """Test has_tool returns False for tool with invalid config."""
        caps = HostCapabilities(
            host_name="test-host",
            tools=[
                ToolCapability(name=ToolName.KUBECTL, installed=True, config_valid=False),
            ],
        )
        assert caps.has_tool(ToolName.KUBECTL) is False

    def test_has_tool_returns_false_for_unknown_tool(self) -> None:
        """Test has_tool returns False for unknown tool."""
        caps = HostCapabilities(host_name="test-host")
        assert caps.has_tool("unknown") is False

    def test_get_tool_returns_capability(self) -> None:
        """Test get_tool returns the capability."""
        ansible_cap = ToolCapability(name=ToolName.ANSIBLE, installed=True)
        caps = HostCapabilities(
            host_name="test-host",
            tools=[ansible_cap],
        )
        result = caps.get_tool(ToolName.ANSIBLE)
        assert result is ansible_cap

    def test_get_tool_returns_none_for_missing(self) -> None:
        """Test get_tool returns None for missing tool."""
        caps = HostCapabilities(host_name="test-host")
        assert caps.get_tool(ToolName.TERRAFORM) is None

    def test_is_expired_returns_false_when_fresh(self) -> None:
        """Test is_expired returns False when cache is fresh."""
        caps = HostCapabilities(
            host_name="test-host",
            cached_at=datetime.now(UTC),
            ttl_seconds=3600,
        )
        assert caps.is_expired() is False

    def test_is_expired_returns_true_when_old(self) -> None:
        """Test is_expired returns True when cache is old."""
        caps = HostCapabilities(
            host_name="test-host",
            cached_at=datetime.now(UTC) - timedelta(hours=25),
            ttl_seconds=86400,
        )
        assert caps.is_expired() is True

    def test_has_iac_repo_with_ansible(self) -> None:
        """Test has_iac_repo returns True when Ansible is configured."""
        caps = HostCapabilities(
            host_name="test-host",
            tools=[
                ToolCapability(name=ToolName.ANSIBLE, installed=True, config_valid=True),
            ],
        )
        assert caps.has_iac_repo is True

    def test_has_iac_repo_with_terraform(self) -> None:
        """Test has_iac_repo returns True when Terraform is configured."""
        caps = HostCapabilities(
            host_name="test-host",
            tools=[
                ToolCapability(name=ToolName.TERRAFORM, installed=True, config_valid=True),
            ],
        )
        assert caps.has_iac_repo is True

    def test_has_iac_repo_without_iac_tools(self) -> None:
        """Test has_iac_repo returns False when no IaC tools."""
        caps = HostCapabilities(
            host_name="test-host",
            tools=[
                ToolCapability(name=ToolName.GIT, installed=True, config_valid=True),
            ],
        )
        assert caps.has_iac_repo is False


class TestLocalCapabilities:
    """Tests for LocalCapabilities model."""

    def test_create_local_capabilities(self) -> None:
        """Test creating local capabilities."""
        caps = LocalCapabilities(
            tools=[
                ToolCapability(name=ToolName.GIT, installed=True),
            ],
            web_access=True,
        )
        assert len(caps.tools) == 1
        assert caps.web_access is True

    def test_has_tool_local(self) -> None:
        """Test has_tool for local capabilities."""
        caps = LocalCapabilities(
            tools=[
                ToolCapability(name=ToolName.DOCKER, installed=True),
            ],
        )
        assert caps.has_tool(ToolName.DOCKER) is True
        assert caps.has_tool(ToolName.HELM) is False

    def test_is_expired_local(self) -> None:
        """Test is_expired for local capabilities."""
        fresh = LocalCapabilities(cached_at=datetime.now(UTC), ttl_seconds=3600)
        assert fresh.is_expired() is False

        old = LocalCapabilities(
            cached_at=datetime.now(UTC) - timedelta(hours=2),
            ttl_seconds=3600,
        )
        assert old.is_expired() is True
