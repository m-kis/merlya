"""Tests for save_report tool."""
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


class TestSaveReport:
    """Test cases for save_report function."""

    @pytest.fixture
    def mock_context(self):
        """Create a mock tool context."""
        ctx = MagicMock()
        ctx.console = MagicMock()
        return ctx

    @pytest.fixture
    def temp_reports_dir(self, tmp_path):
        """Create a temporary reports directory."""
        reports_dir = tmp_path / "merlya_reports"
        reports_dir.mkdir()
        return reports_dir

    def test_save_report_basic(self, mock_context, temp_reports_dir):
        """Test basic report saving."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                result = save_report(
                    title="Test Report",
                    content="This is test content."
                )

                assert "✅ Report saved to:" in result
                assert temp_reports_dir.name in result

                # Verify file was created
                reports = list(temp_reports_dir.glob("*.md"))
                assert len(reports) == 1

                # Verify content
                content = reports[0].read_text()
                assert "# Test Report" in content
                assert "This is test content." in content

    def test_save_report_with_filename(self, mock_context, temp_reports_dir):
        """Test report saving with custom filename."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                result = save_report(
                    title="Custom Report",
                    content="Content here.",
                    filename="my-custom-report"
                )

                assert "✅ Report saved to:" in result

                # Verify filename contains custom name
                reports = list(temp_reports_dir.glob("*.md"))
                assert len(reports) == 1
                assert "my-custom-report" in reports[0].name

    def test_save_report_empty_title(self, mock_context, temp_reports_dir):
        """Test that empty title is rejected."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                result = save_report(title="", content="Some content")
                assert "❌ Title cannot be empty" in result

                result = save_report(title="   ", content="Some content")
                assert "❌ Title cannot be empty" in result

    def test_save_report_empty_content(self, mock_context, temp_reports_dir):
        """Test that empty content is rejected."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                result = save_report(title="Title", content="")
                assert "❌ Content cannot be empty" in result

                result = save_report(title="Title", content="   ")
                assert "❌ Content cannot be empty" in result

    def test_save_report_title_too_long(self, mock_context, temp_reports_dir):
        """Test that long titles are rejected."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                long_title = "A" * 250
                result = save_report(title=long_title, content="Content")
                assert "❌ Title too long" in result

    def test_save_report_path_traversal_protection(self, mock_context, temp_reports_dir):
        """Test that path traversal attempts are blocked."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                # These should be sanitized, not cause errors
                result = save_report(
                    title="Test",
                    content="Content",
                    filename="../../../etc/passwd"
                )

                # Should succeed with sanitized filename
                assert "✅ Report saved to:" in result

                # Verify file is in correct directory
                reports = list(temp_reports_dir.glob("*.md"))
                assert len(reports) == 1
                assert str(reports[0].resolve()).startswith(str(temp_reports_dir.resolve()))

    def test_save_report_special_characters_in_filename(self, mock_context, temp_reports_dir):
        """Test that special characters in filename are sanitized."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                result = save_report(
                    title="Test",
                    content="Content",
                    filename="report<>:\"|?*name"
                )

                assert "✅ Report saved to:" in result

                # Verify file was created with sanitized name
                reports = list(temp_reports_dir.glob("*.md"))
                assert len(reports) == 1
                # Special chars should be replaced with underscores
                assert "<" not in reports[0].name
                assert ">" not in reports[0].name

    def test_save_report_size_limit(self, mock_context, temp_reports_dir):
        """Test that oversized reports are rejected."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                # Create content larger than 10MB
                huge_content = "X" * (11 * 1024 * 1024)
                result = save_report(title="Huge", content=huge_content)

                assert "❌ Report too large" in result

    def test_cleanup_old_reports(self, temp_reports_dir):
        """Test that old reports are cleaned up."""
        from merlya.tools.interaction import _cleanup_old_reports

        # Create an old file (mock old mtime)
        old_report = temp_reports_dir / "old_report.md"
        old_report.write_text("Old content")

        # Create a new file
        new_report = temp_reports_dir / "new_report.md"
        new_report.write_text("New content")

        # Set old file's mtime to 10 days ago
        old_time = (datetime.now() - timedelta(days=10)).timestamp()
        os.utime(old_report, (old_time, old_time))

        # Run cleanup
        deleted = _cleanup_old_reports(temp_reports_dir, max_age_days=7)

        # Old file should be deleted
        assert deleted == 1
        assert not old_report.exists()
        assert new_report.exists()

    def test_cleanup_old_reports_empty_dir(self, temp_reports_dir):
        """Test cleanup on empty directory."""
        from merlya.tools.interaction import _cleanup_old_reports

        deleted = _cleanup_old_reports(temp_reports_dir, max_age_days=7)
        assert deleted == 0

    def test_save_report_creates_directory(self, mock_context, tmp_path):
        """Test that reports directory is created if it doesn't exist."""
        reports_dir = tmp_path / "new_reports_dir"
        assert not reports_dir.exists()

        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(reports_dir)}):
                from merlya.tools.interaction import save_report

                result = save_report(title="Test", content="Content")

                assert "✅ Report saved to:" in result
                assert reports_dir.exists()

    def test_save_report_console_notification(self, mock_context, temp_reports_dir):
        """Test that user is notified via console."""
        with patch("merlya.tools.interaction.get_tool_context", return_value=mock_context):
            with patch.dict(os.environ, {"MERLYA_REPORTS_DIR": str(temp_reports_dir)}):
                from merlya.tools.interaction import save_report

                save_report(title="Test", content="Content")

                # Verify console.print was called
                mock_context.console.print.assert_called_once()
                call_args = str(mock_context.console.print.call_args)
                assert "Report saved" in call_args
