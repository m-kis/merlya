"""Tests for bootstrap module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from merlya.core.bootstrap import _configure_logging_from_config


class TestConfigureLogging:
    """Tests for _configure_logging_from_config function."""

    @pytest.fixture
    def mock_ctx(self):
        """Create mock context with config."""
        ctx = MagicMock()
        ctx.config.logging.console_level = "info"
        ctx.config.logging.file_level = "debug"
        ctx.config.general.log_level = "warning"
        return ctx

    def test_verbose_overrides_config(self, mock_ctx):
        """Test that verbose flag sets DEBUG level."""
        with patch("merlya.core.logging.configure_logging") as mock_configure:
            _configure_logging_from_config(mock_ctx, verbose=True)

            mock_configure.assert_called_once()
            call_args = mock_configure.call_args
            assert call_args.kwargs["console_level"] == "DEBUG"

    def test_quiet_disables_logging(self, mock_ctx):
        """Test that quiet flag disables merlya logger."""
        with patch("merlya.core.bootstrap.logger") as mock_logger:
            _configure_logging_from_config(mock_ctx, quiet=True)

            mock_logger.disable.assert_called_once_with("merlya")

    def test_uses_config_console_level(self, mock_ctx):
        """Test that config console_level is used when no flags."""
        with patch("merlya.core.logging.configure_logging") as mock_configure:
            _configure_logging_from_config(mock_ctx, verbose=False, quiet=False)

            mock_configure.assert_called_once()
            call_args = mock_configure.call_args
            assert call_args.kwargs["console_level"] == "INFO"
            assert call_args.kwargs["file_level"] == "DEBUG"

    def test_fallback_to_general_log_level(self):
        """Test fallback to general.log_level when console_level is None."""
        ctx = MagicMock()
        ctx.config.logging.console_level = None
        ctx.config.logging.file_level = "debug"
        ctx.config.general.log_level = "warning"

        with patch("merlya.core.logging.configure_logging") as mock_configure:
            _configure_logging_from_config(ctx, verbose=False, quiet=False)

            call_args = mock_configure.call_args
            assert call_args.kwargs["console_level"] == "WARNING"
