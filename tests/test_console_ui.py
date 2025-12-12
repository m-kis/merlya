"""Tests for merlya.ui.console module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.core.types import CheckStatus
from merlya.ui.console import ACCENT_COLOR, MERLYA_THEME, ConsoleUI

# ==============================================================================
# TestConsoleUIInit
# ==============================================================================


class TestConsoleUIInit:
    """Tests for ConsoleUI initialization."""

    def test_init_defaults(self) -> None:
        """Test initialization with default values."""
        ui = ConsoleUI()
        assert ui.auto_confirm is False
        assert ui.quiet is False
        assert ui.console is not None
        assert ui._active_status is None

    def test_init_with_auto_confirm(self) -> None:
        """Test initialization with auto_confirm enabled."""
        ui = ConsoleUI(auto_confirm=True)
        assert ui.auto_confirm is True

    def test_init_with_quiet_mode(self) -> None:
        """Test initialization with quiet mode enabled."""
        ui = ConsoleUI(quiet=True)
        assert ui.quiet is True

    def test_init_with_custom_theme(self) -> None:
        """Test initialization with custom theme."""
        from rich.theme import Theme

        custom_theme = Theme({"custom": "bold blue"})
        ui = ConsoleUI(theme=custom_theme)
        # Console was initialized (theme is applied internally)
        assert ui.console is not None

    def test_default_theme_has_expected_styles(self) -> None:
        """Test that default theme has all expected styles."""
        expected_styles = ["info", "warning", "error", "success", "muted", "highlight", "accent"]
        for style in expected_styles:
            assert style in MERLYA_THEME.styles

    def test_accent_color_constant(self) -> None:
        """Test accent color constant value."""
        assert ACCENT_COLOR == "sky_blue2"


# ==============================================================================
# TestConsoleUIOutput
# ==============================================================================


class TestConsoleUIOutput:
    """Tests for ConsoleUI output methods."""

    def test_print_delegates_to_console(self) -> None:
        """Test that print delegates to Rich console."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.print("test message")
            mock_print.assert_called_once_with("test message")

    def test_print_with_kwargs(self) -> None:
        """Test print with keyword arguments."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.print("test", style="bold", end="\n\n")
            mock_print.assert_called_once_with("test", style="bold", end="\n\n")

    def test_markdown_renders_markdown(self) -> None:
        """Test markdown rendering."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.markdown("# Title\n\n**bold**")
            mock_print.assert_called_once()
            # Verify Markdown object was passed
            args, _ = mock_print.call_args
            from rich.markdown import Markdown

            assert isinstance(args[0], Markdown)

    def test_panel_with_title(self) -> None:
        """Test panel display with title."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.panel("content", title="Test Panel")
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            from rich.panel import Panel

            assert isinstance(args[0], Panel)

    def test_panel_with_custom_style(self) -> None:
        """Test panel with custom style."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.panel("content", style="error")
            mock_print.assert_called_once()

    def test_panel_with_unknown_style_uses_accent(self) -> None:
        """Test panel falls back to accent for unknown styles."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.panel("content", style="nonexistent_style")
            mock_print.assert_called_once()

    def test_newline(self) -> None:
        """Test newline output."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.newline()
            mock_print.assert_called_once_with()


# ==============================================================================
# TestConsoleUIStyles
# ==============================================================================


class TestConsoleUIStyles:
    """Tests for styled message methods."""

    def test_success_message(self) -> None:
        """Test success message styling."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.success("Operation complete")
            mock_print.assert_called_once_with("[success]Operation complete[/success]")

    def test_error_message(self) -> None:
        """Test error message styling."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.error("Something went wrong")
            mock_print.assert_called_once_with("[error]Something went wrong[/error]")

    def test_warning_message(self) -> None:
        """Test warning message styling."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.warning("Be careful")
            mock_print.assert_called_once_with("[warning]Be careful[/warning]")

    def test_info_message(self) -> None:
        """Test info message styling."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.info("For your information")
            mock_print.assert_called_once_with("[info]For your information[/info]")

    def test_muted_message(self) -> None:
        """Test muted message styling."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.muted("Quiet message")
            mock_print.assert_called_once_with("[muted]Quiet message[/muted]")


# ==============================================================================
# TestConsoleUITable
# ==============================================================================


class TestConsoleUITable:
    """Tests for table output."""

    def test_table_basic(self) -> None:
        """Test basic table output."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.table(
                headers=["Name", "Status"],
                rows=[["web-01", "healthy"], ["web-02", "unhealthy"]],
            )
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            from rich.table import Table

            assert isinstance(args[0], Table)

    def test_table_with_title(self) -> None:
        """Test table with title."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.table(
                headers=["Col1"],
                rows=[["val1"]],
                title="My Table",
            )
            mock_print.assert_called_once()

    def test_table_empty_rows(self) -> None:
        """Test table with no rows."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.table(headers=["Header"], rows=[])
            mock_print.assert_called_once()

    def test_table_multiple_columns(self) -> None:
        """Test table with multiple columns."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.table(
                headers=["A", "B", "C", "D"],
                rows=[
                    ["1", "2", "3", "4"],
                    ["5", "6", "7", "8"],
                ],
            )
            mock_print.assert_called_once()


# ==============================================================================
# TestConsoleUIHealthStatus
# ==============================================================================


class TestConsoleUIHealthStatus:
    """Tests for health status display."""

    def test_health_status_ok(self) -> None:
        """Test OK status display."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.health_status("test", CheckStatus.OK, "All good")
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            assert "✅" in args[0]
            assert "All good" in args[0]

    def test_health_status_warning(self) -> None:
        """Test WARNING status display."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.health_status("test", CheckStatus.WARNING, "Needs attention")
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            assert "⚠️" in args[0]
            assert "Needs attention" in args[0]

    def test_health_status_error(self) -> None:
        """Test ERROR status display."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.health_status("test", CheckStatus.ERROR, "Critical issue")
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            assert "❌" in args[0]
            assert "Critical issue" in args[0]

    def test_health_status_disabled(self) -> None:
        """Test DISABLED status display."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.health_status("test", CheckStatus.DISABLED, "Disabled check")
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            assert "⊘" in args[0]
            assert "Disabled check" in args[0]

    def test_health_status_unknown(self) -> None:
        """Test unknown status shows question mark."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            # Use a mock status to test fallback
            ui.health_status("test", MagicMock(), "Unknown status")
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            assert "❓" in args[0]


# ==============================================================================
# TestConsoleUISpinner
# ==============================================================================


class TestConsoleUISpinner:
    """Tests for spinner context manager."""

    def test_spinner_context_manager(self) -> None:
        """Test spinner as context manager."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        mock_status.__enter__ = MagicMock(return_value=mock_status)
        mock_status.__exit__ = MagicMock(return_value=False)

        with patch.object(ui.console, "status", return_value=mock_status):
            with ui.spinner("Loading..."):
                assert ui._active_status is mock_status

            # After context exit, status should be None
            assert ui._active_status is None
            mock_status.stop.assert_called_once()

    def test_spinner_with_custom_spinner_type(self) -> None:
        """Test spinner with custom spinner type."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        mock_status.__enter__ = MagicMock(return_value=mock_status)
        mock_status.__exit__ = MagicMock(return_value=False)

        with patch.object(ui.console, "status", return_value=mock_status) as mock_create:
            with ui.spinner("Loading...", spinner="line"):
                pass
            # Verify custom spinner was used
            mock_create.assert_called_once()
            _, kwargs = mock_create.call_args
            assert kwargs.get("spinner") == "line"

    def test_spinner_cleanup_on_exception(self) -> None:
        """Test spinner cleanup when exception occurs."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        mock_status.__enter__ = MagicMock(return_value=mock_status)
        mock_status.__exit__ = MagicMock(return_value=False)

        with patch.object(ui.console, "status", return_value=mock_status):
            with pytest.raises(ValueError, match="test error"):
                with ui.spinner("Loading..."):
                    raise ValueError("test error")

            # Cleanup should still happen
            assert ui._active_status is None
            mock_status.stop.assert_called_once()


# ==============================================================================
# TestConsoleUIProgress
# ==============================================================================


class TestConsoleUIProgress:
    """Tests for progress bar creation."""

    def test_progress_returns_progress_instance(self) -> None:
        """Test progress returns Progress instance."""
        ui = ConsoleUI()
        progress = ui.progress()
        from rich.progress import Progress

        assert isinstance(progress, Progress)

    def test_progress_transient_default(self) -> None:
        """Test progress is transient by default."""
        ui = ConsoleUI()
        progress = ui.progress()
        assert progress.live.transient is True

    def test_progress_non_transient(self) -> None:
        """Test progress with transient=False."""
        ui = ConsoleUI()
        progress = ui.progress(transient=False)
        assert progress.live.transient is False


# ==============================================================================
# TestConsoleUIPrompt
# ==============================================================================


class TestConsoleUIPrompt:
    """Tests for async prompt methods."""

    @pytest.mark.asyncio
    async def test_prompt_basic(self) -> None:
        """Test basic text prompt."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="user input")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt("Enter name")
            assert result == "user input"
            mock_session.prompt_async.assert_called_once_with("Enter name: ", default="")

    @pytest.mark.asyncio
    async def test_prompt_with_default(self) -> None:
        """Test prompt with default value."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="default_value")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt("Enter name", default="default_value")
            assert result == "default_value"
            mock_session.prompt_async.assert_called_once_with(
                "Enter name: ", default="default_value"
            )

    @pytest.mark.asyncio
    async def test_prompt_with_none_default(self) -> None:
        """Test prompt with None default becomes empty string."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt("Enter name", default=None)
            mock_session.prompt_async.assert_called_once_with("Enter name: ", default="")

    @pytest.mark.asyncio
    async def test_prompt_strips_whitespace(self) -> None:
        """Test prompt strips whitespace from result."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="  input with spaces  ")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt("Enter name")
            assert result == "input with spaces"

    @pytest.mark.asyncio
    async def test_prompt_stops_spinner(self) -> None:
        """Test prompt stops active spinner."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        ui._active_status = mock_status

        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="input")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt("Enter name")
            # Check the saved mock reference (status is cleared after stop)
            mock_status.stop.assert_called_once()


# ==============================================================================
# TestConsoleUIPromptSecret
# ==============================================================================


class TestConsoleUIPromptSecret:
    """Tests for secret prompt method."""

    @pytest.mark.asyncio
    async def test_prompt_secret_basic(self) -> None:
        """Test basic secret prompt."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="secret123")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_secret("Enter password")
            assert result == "secret123"
            mock_session.prompt_async.assert_called_once_with("Enter password: ", is_password=True)

    @pytest.mark.asyncio
    async def test_prompt_secret_strips_whitespace(self) -> None:
        """Test secret prompt strips whitespace."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="  secret  ")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_secret("Password")
            assert result == "secret"

    @pytest.mark.asyncio
    async def test_prompt_secret_stops_spinner(self) -> None:
        """Test secret prompt stops active spinner."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        ui._active_status = mock_status

        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="secret")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt_secret("Password")
            # Check the saved mock reference (status is cleared after stop)
            mock_status.stop.assert_called_once()


# ==============================================================================
# TestConsoleUIPromptConfirm
# ==============================================================================


class TestConsoleUIPromptConfirm:
    """Tests for confirmation prompt."""

    @pytest.mark.asyncio
    async def test_prompt_confirm_yes(self) -> None:
        """Test confirmation with yes response."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="y")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continue?")
            assert result is True

    @pytest.mark.asyncio
    async def test_prompt_confirm_yes_uppercase(self) -> None:
        """Test confirmation with uppercase YES."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="YES")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continue?")
            assert result is True

    @pytest.mark.asyncio
    async def test_prompt_confirm_oui_french(self) -> None:
        """Test confirmation with French oui."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="oui")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continuer?")
            assert result is True

    @pytest.mark.asyncio
    async def test_prompt_confirm_o_french(self) -> None:
        """Test confirmation with French o."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="o")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continuer?")
            assert result is True

    @pytest.mark.asyncio
    async def test_prompt_confirm_no(self) -> None:
        """Test confirmation with no response."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="n")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continue?")
            assert result is False

    @pytest.mark.asyncio
    async def test_prompt_confirm_empty_uses_default_false(self) -> None:
        """Test empty response uses default (False)."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continue?", default=False)
            assert result is False

    @pytest.mark.asyncio
    async def test_prompt_confirm_empty_uses_default_true(self) -> None:
        """Test empty response uses default (True)."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_confirm("Continue?", default=True)
            assert result is True

    @pytest.mark.asyncio
    async def test_prompt_confirm_auto_confirm(self) -> None:
        """Test auto_confirm mode returns True without prompting."""
        ui = ConsoleUI(auto_confirm=True)

        with patch.object(ui.console, "print"):
            result = await ui.prompt_confirm("Continue?")
            assert result is True

    @pytest.mark.asyncio
    async def test_prompt_confirm_auto_confirm_quiet(self) -> None:
        """Test auto_confirm in quiet mode doesn't print."""
        ui = ConsoleUI(auto_confirm=True, quiet=True)

        with patch.object(ui.console, "print") as mock_print:
            result = await ui.prompt_confirm("Continue?")
            assert result is True
            mock_print.assert_not_called()

    @pytest.mark.asyncio
    async def test_prompt_confirm_shows_suffix(self) -> None:
        """Test confirmation shows correct suffix."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="y")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt_confirm("Continue?", default=False)
            mock_session.prompt_async.assert_called_with("Continue? [y/N]: ")

    @pytest.mark.asyncio
    async def test_prompt_confirm_shows_suffix_default_true(self) -> None:
        """Test confirmation shows correct suffix when default is True."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt_confirm("Continue?", default=True)
            mock_session.prompt_async.assert_called_with("Continue? [Y/n]: ")


# ==============================================================================
# TestConsoleUIConfirmAlias
# ==============================================================================


class TestConsoleUIConfirmAlias:
    """Tests for confirm method (alias for prompt_confirm)."""

    @pytest.mark.asyncio
    async def test_confirm_delegates_to_prompt_confirm(self) -> None:
        """Test confirm is an alias for prompt_confirm."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="y")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.confirm("Are you sure?")
            assert result is True


# ==============================================================================
# TestConsoleUIPromptChoice
# ==============================================================================


class TestConsoleUIPromptChoice:
    """Tests for choice prompt method."""

    @pytest.mark.asyncio
    async def test_prompt_choice_valid_selection(self) -> None:
        """Test choice selection from list."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="option2")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_choice("Select", ["option1", "option2", "option3"])
            assert result == "option2"

    @pytest.mark.asyncio
    async def test_prompt_choice_numeric_selection(self) -> None:
        """Test numeric choice selection."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="2")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_choice("Select", ["a", "b", "c"])
            assert result == "b"

    @pytest.mark.asyncio
    async def test_prompt_choice_numeric_first(self) -> None:
        """Test numeric selection of first item."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="1")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_choice("Select", ["first", "second"])
            assert result == "first"

    @pytest.mark.asyncio
    async def test_prompt_choice_empty_uses_default(self) -> None:
        """Test empty response uses default."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_choice("Select", ["a", "b"], default="b")
            assert result == "b"

    @pytest.mark.asyncio
    async def test_prompt_choice_invalid_returns_raw(self) -> None:
        """Test invalid choice returns raw input."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="invalid_option")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_choice("Select", ["a", "b"])
            assert result == "invalid_option"

    @pytest.mark.asyncio
    async def test_prompt_choice_invalid_numeric_returns_raw(self) -> None:
        """Test invalid numeric choice returns raw input."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="99")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            result = await ui.prompt_choice("Select", ["a", "b"])
            assert result == "99"

    @pytest.mark.asyncio
    async def test_prompt_choice_shows_choices_in_prompt(self) -> None:
        """Test choices are shown in prompt."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="x")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt_choice("Pick one", ["x", "y", "z"])
            call_args = mock_session.prompt_async.call_args[0][0]
            assert "x/y/z" in call_args

    @pytest.mark.asyncio
    async def test_prompt_choice_shows_default_in_prompt(self) -> None:
        """Test default is shown in prompt."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(return_value="")

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            await ui.prompt_choice("Pick", ["a", "b"], default="b")
            call_args = mock_session.prompt_async.call_args[0][0]
            assert "[b]" in call_args


# ==============================================================================
# TestConsoleUIStopSpinner
# ==============================================================================


class TestConsoleUIStopSpinner:
    """Tests for _stop_spinner helper method."""

    def test_stop_spinner_when_active(self) -> None:
        """Test stopping active spinner."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        ui._active_status = mock_status

        ui._stop_spinner()

        mock_status.stop.assert_called_once()
        assert ui._active_status is None

    def test_stop_spinner_when_inactive(self) -> None:
        """Test stopping when no spinner active."""
        ui = ConsoleUI()
        ui._active_status = None

        # Should not raise
        ui._stop_spinner()
        assert ui._active_status is None

    def test_stop_spinner_handles_exception(self) -> None:
        """Test stop_spinner handles exceptions gracefully."""
        ui = ConsoleUI()
        mock_status = MagicMock()
        mock_status.stop.side_effect = Exception("Stop failed")
        ui._active_status = mock_status

        # Should not raise
        ui._stop_spinner()
        assert ui._active_status is None


# ==============================================================================
# TestConsoleUIWelcomeScreen
# ==============================================================================


class TestConsoleUIWelcomeScreen:
    """Tests for welcome screen display."""

    def test_welcome_screen_renders_panels(self) -> None:
        """Test welcome screen renders hero and warning panels."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.welcome_screen(
                title="Welcome",
                warning_title="Warning",
                hero_lines=["Line 1", "Line 2"],
                warning_lines=["Warning 1"],
            )

            # Should print hero panel, newline, warning panel
            assert mock_print.call_count == 3

    def test_welcome_screen_with_empty_lines(self) -> None:
        """Test welcome screen with empty content."""
        ui = ConsoleUI()
        with patch.object(ui.console, "print") as mock_print:
            ui.welcome_screen(
                title="Test",
                warning_title="Warn",
                hero_lines=[],
                warning_lines=[],
            )

            assert mock_print.call_count == 3


# ==============================================================================
# TestConsoleUIIntegration
# ==============================================================================


class TestConsoleUIIntegration:
    """Integration tests for ConsoleUI."""

    def test_full_workflow(self) -> None:
        """Test typical UI workflow."""
        ui = ConsoleUI(quiet=True)

        # Display various messages
        with patch.object(ui.console, "print"):
            ui.success("Task completed")
            ui.warning("Check this")
            ui.error("Something failed")
            ui.info("FYI")
            ui.muted("Minor note")

    @pytest.mark.asyncio
    async def test_prompt_workflow(self) -> None:
        """Test typical prompt workflow."""
        ui = ConsoleUI()
        mock_session = MagicMock()
        mock_session.prompt_async = AsyncMock(side_effect=["John", "yes"])

        with patch("merlya.ui.console.PromptSession", return_value=mock_session):
            name = await ui.prompt("Name")
            confirm = await ui.prompt_confirm("Proceed?")

            assert name == "John"
            assert confirm is True
