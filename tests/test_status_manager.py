"""
Tests for StatusManager - spinner pause/resume functionality.
"""
from unittest.mock import MagicMock, patch


class TestStatusManager:
    """Test StatusManager class."""

    def test_create_status_manager(self):
        """Should create StatusManager instance."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        assert manager._console is None
        assert manager._status is None
        assert manager._is_active is False

    def test_set_console(self):
        """Should set console."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        mock_console = MagicMock()
        manager.set_console(mock_console)
        assert manager._console is mock_console

    def test_start_without_console(self):
        """Should not start without console."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        manager.start()
        assert manager._is_active is False

    def test_start_with_console(self):
        """Should start spinner with console."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        manager.set_console(mock_console)
        manager.start("[cyan]Processing...[/cyan]")

        assert manager._is_active is True
        mock_console.status.assert_called_once()
        mock_status.start.assert_called_once()

    def test_stop_spinner(self):
        """Should stop spinner and cleanup."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        manager.set_console(mock_console)
        manager.start()
        manager.stop()

        assert manager._is_active is False
        assert manager._status is None
        mock_status.stop.assert_called_once()

    def test_pause_for_input_context_manager(self):
        """Should pause and resume spinner during input."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        manager.set_console(mock_console)
        manager.start()

        with manager.pause_for_input():
            # Spinner should be paused
            assert manager._is_active is False

        # Spinner should be resumed
        assert manager._is_active is True

    def test_pause_for_input_when_not_active(self):
        """Should handle pause when spinner not active."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()

        with manager.pause_for_input():
            # Should not raise
            pass

        assert manager._is_active is False

    def test_start_handles_exception(self):
        """Should handle exception during start."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        mock_console = MagicMock()
        mock_console.status.side_effect = Exception("Console error")

        manager.set_console(mock_console)
        manager.start()

        # Should handle gracefully
        assert manager._is_active is False
        assert manager._status is None

    def test_is_active_property(self):
        """Should expose is_active property."""
        from athena_ai.tools.base import StatusManager

        manager = StatusManager()
        assert manager.is_active is False


class TestGetStatusManager:
    """Test get_status_manager singleton."""

    def test_get_status_manager_singleton(self):
        """Should return same instance."""
        from athena_ai.tools.base import get_status_manager

        manager1 = get_status_manager()
        manager2 = get_status_manager()
        assert manager1 is manager2

    def test_get_status_manager_type(self):
        """Should return StatusManager instance."""
        from athena_ai.tools.base import StatusManager, get_status_manager

        manager = get_status_manager()
        assert isinstance(manager, StatusManager)


class TestToolContext:
    """Test ToolContext dependency injection."""

    def test_get_user_input_pauses_spinner(self):
        """Should pause spinner during user input."""
        from athena_ai.tools.base import ToolContext, get_status_manager

        mock_console = MagicMock()
        mock_status = MagicMock()
        mock_console.status.return_value = mock_status

        ctx = ToolContext(console=mock_console)

        # Start the status manager
        status_manager = get_status_manager()
        status_manager.set_console(mock_console)
        status_manager.start()

        # Mock input
        with patch("builtins.input", return_value="test response"):
            result = ctx.get_user_input("Enter: ")

        assert result == "test response"

    def test_get_user_input_with_callback(self):
        """Should use callback if provided."""
        from athena_ai.tools.base import ToolContext

        mock_callback = MagicMock(return_value="callback response")
        ctx = ToolContext(input_callback=mock_callback)

        result = ctx.get_user_input("Enter: ")

        assert result == "callback response"
        mock_callback.assert_called_once_with("Enter: ")
