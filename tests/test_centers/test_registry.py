"""Tests for centers registry."""

from unittest.mock import MagicMock

import pytest

from merlya.centers.base import AbstractCenter, CenterDeps, CenterMode, CenterResult
from merlya.centers.registry import CenterRegistry


class MockCenter(AbstractCenter):
    """Mock center for testing."""

    @property
    def mode(self) -> CenterMode:
        return CenterMode.DIAGNOSTIC

    @property
    def allowed_tools(self) -> list[str]:
        return ["ssh_execute", "list_hosts"]

    async def execute(self, deps: CenterDeps) -> CenterResult:
        return CenterResult(
            success=True,
            message="Mock execution",
            mode=self.mode,
        )


class MockChangeCenter(AbstractCenter):
    """Mock change center for testing."""

    @property
    def mode(self) -> CenterMode:
        return CenterMode.CHANGE

    @property
    def allowed_tools(self) -> list[str]:
        return ["ssh_execute", "ansible_run"]

    async def execute(self, deps: CenterDeps) -> CenterResult:
        return CenterResult(
            success=True,
            message="Mock change",
            mode=self.mode,
            applied=True,
        )


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Reset registry between tests."""
    yield
    CenterRegistry.reset_instance()


@pytest.fixture
def mock_ctx() -> MagicMock:
    """Create mock shared context."""
    return MagicMock()


class TestCenterRegistry:
    """Tests for CenterRegistry."""

    def test_singleton_pattern(self) -> None:
        """Test registry uses singleton pattern."""
        reg1 = CenterRegistry.get_instance()
        reg2 = CenterRegistry.get_instance()
        assert reg1 is reg2

    def test_reset_instance(self) -> None:
        """Test reset creates new instance."""
        reg1 = CenterRegistry.get_instance()
        CenterRegistry.reset_instance()
        reg2 = CenterRegistry.get_instance()
        assert reg1 is not reg2

    def test_register_center(self, mock_ctx: MagicMock) -> None:
        """Test registering a center."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)

        assert reg.is_registered(CenterMode.DIAGNOSTIC)
        assert not reg.is_registered(CenterMode.CHANGE)

    def test_get_center(self, mock_ctx: MagicMock) -> None:
        """Test getting a registered center."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)

        center = reg.get(CenterMode.DIAGNOSTIC)
        assert isinstance(center, MockCenter)
        assert center.mode == CenterMode.DIAGNOSTIC

    def test_get_returns_same_instance(self, mock_ctx: MagicMock) -> None:
        """Test get returns the same instance (lazy singleton)."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)

        center1 = reg.get(CenterMode.DIAGNOSTIC)
        center2 = reg.get(CenterMode.DIAGNOSTIC)
        assert center1 is center2

    def test_get_unregistered_raises(self, mock_ctx: MagicMock) -> None:
        """Test getting unregistered center raises ValueError."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)

        with pytest.raises(ValueError, match="No center registered"):
            reg.get(CenterMode.DIAGNOSTIC)

    def test_get_without_context_raises(self) -> None:
        """Test getting center without context raises RuntimeError."""
        reg = CenterRegistry.get_instance()
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)

        with pytest.raises(RuntimeError, match="Context not set"):
            reg.get(CenterMode.DIAGNOSTIC)

    def test_get_by_name(self, mock_ctx: MagicMock) -> None:
        """Test getting center by string name."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.CHANGE, MockChangeCenter)

        center = reg.get_by_name("change")
        assert isinstance(center, MockChangeCenter)

    def test_get_by_name_case_insensitive(self, mock_ctx: MagicMock) -> None:
        """Test get_by_name is case insensitive."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)

        center = reg.get_by_name("DIAGNOSTIC")
        assert center.mode == CenterMode.DIAGNOSTIC

    def test_get_by_name_unknown_raises(self, mock_ctx: MagicMock) -> None:
        """Test get_by_name with unknown name raises."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)

        with pytest.raises(ValueError, match="Unknown center mode"):
            reg.get_by_name("unknown")

    def test_registered_modes(self, mock_ctx: MagicMock) -> None:
        """Test getting list of registered modes."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)
        reg.register(CenterMode.CHANGE, MockChangeCenter)

        modes = reg.registered_modes
        assert CenterMode.DIAGNOSTIC in modes
        assert CenterMode.CHANGE in modes

    def test_set_context_clears_instances(self, mock_ctx: MagicMock) -> None:
        """Test setting new context clears cached instances."""
        reg = CenterRegistry.get_instance()
        reg.set_context(mock_ctx)
        reg.register(CenterMode.DIAGNOSTIC, MockCenter)

        # Get instance
        center1 = reg.get(CenterMode.DIAGNOSTIC)

        # Set new context
        new_ctx = MagicMock()
        reg.set_context(new_ctx)

        # Get instance again - should be new
        center2 = reg.get(CenterMode.DIAGNOSTIC)
        assert center1 is not center2
