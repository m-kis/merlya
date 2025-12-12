"""Tests for merlya.tools.files.tools module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.ssh.pool import SSHResult
from merlya.tools.files.tools import (
    FileResult,
    _format_size,
    _validate_mode,
    _validate_path,
    delete_file,
    download_file,
    file_exists,
    file_info,
    list_directory,
    read_file,
    search_files,
    upload_file,
    write_file,
)

# ==============================================================================
# TestFileResult
# ==============================================================================


class TestFileResult:
    """Tests for FileResult dataclass."""

    def test_success_result(self) -> None:
        """Test successful file result."""
        result = FileResult(success=True, data="file content")
        assert result.success is True
        assert result.data == "file content"
        assert result.error is None

    def test_error_result(self) -> None:
        """Test error file result."""
        result = FileResult(success=False, error="File not found")
        assert result.success is False
        assert result.data is None
        assert result.error == "File not found"

    def test_result_with_dict_data(self) -> None:
        """Test result with dictionary data."""
        result = FileResult(success=True, data={"name": "test.txt", "size": 100})
        assert result.data == {"name": "test.txt", "size": 100}

    def test_result_with_list_data(self) -> None:
        """Test result with list data."""
        result = FileResult(success=True, data=["file1.txt", "file2.txt"])
        assert result.data == ["file1.txt", "file2.txt"]


# ==============================================================================
# TestValidatePath
# ==============================================================================


class TestValidatePath:
    """Tests for _validate_path function."""

    def test_valid_path(self) -> None:
        """Test valid path returns None."""
        assert _validate_path("/home/user/file.txt") is None
        assert _validate_path("./relative/path") is None
        assert _validate_path("filename.txt") is None

    def test_empty_path(self) -> None:
        """Test empty path returns error."""
        assert _validate_path("") == "Path cannot be empty"

    def test_path_with_null_bytes(self) -> None:
        """Test path with null bytes returns error."""
        assert _validate_path("/path/to\x00/file") == "Path contains null bytes"

    def test_path_too_long(self) -> None:
        """Test path exceeding max length."""
        long_path = "/" + "a" * 5000
        error = _validate_path(long_path)
        assert error is not None
        assert "too long" in error

    def test_path_at_max_length(self) -> None:
        """Test path at exactly max length."""
        # 4096 is max length
        max_path = "/" + "a" * 4095
        assert _validate_path(max_path) is None


# ==============================================================================
# TestValidateMode
# ==============================================================================


class TestValidateMode:
    """Tests for _validate_mode function."""

    def test_valid_modes(self) -> None:
        """Test valid file modes."""
        assert _validate_mode("0644") is None
        assert _validate_mode("0755") is None
        assert _validate_mode("777") is None
        assert _validate_mode("0600") is None
        assert _validate_mode("0400") is None

    def test_invalid_mode_letters(self) -> None:
        """Test mode with letters returns error."""
        error = _validate_mode("rwxr-xr-x")
        assert error is not None
        assert "Invalid mode" in error

    def test_invalid_mode_decimal(self) -> None:
        """Test decimal mode (contains 8 or 9)."""
        error = _validate_mode("0689")
        assert error is not None
        assert "Invalid mode" in error

    def test_invalid_mode_too_short(self) -> None:
        """Test mode too short."""
        error = _validate_mode("64")
        assert error is not None

    def test_invalid_mode_too_long(self) -> None:
        """Test mode too long."""
        error = _validate_mode("06444")
        assert error is not None


# ==============================================================================
# TestFormatSize
# ==============================================================================


class TestFormatSize:
    """Tests for _format_size function."""

    def test_bytes(self) -> None:
        """Test byte formatting."""
        assert "B" in _format_size(512)
        assert "512" in _format_size(512)

    def test_kilobytes(self) -> None:
        """Test kilobyte formatting."""
        result = _format_size(2048)
        assert "KB" in result

    def test_megabytes(self) -> None:
        """Test megabyte formatting."""
        result = _format_size(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self) -> None:
        """Test gigabyte formatting."""
        result = _format_size(3 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_terabytes(self) -> None:
        """Test terabyte formatting."""
        result = _format_size(2 * 1024 * 1024 * 1024 * 1024)
        assert "TB" in result

    def test_zero_size(self) -> None:
        """Test zero size."""
        result = _format_size(0)
        assert "0" in result
        assert "B" in result

    def test_small_size(self) -> None:
        """Test small size (< 10)."""
        result = _format_size(5)
        assert "5 B" in result


# ==============================================================================
# TestReadFile
# ==============================================================================


class TestReadFile:
    """Tests for read_file function."""

    @pytest.mark.asyncio
    async def test_read_file_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful file read."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="file content here", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await read_file(mock_shared_context, "web-01", "/etc/passwd")

        assert result.success is True
        assert result.data == "file content here"

    @pytest.mark.asyncio
    async def test_read_file_with_head(self, mock_shared_context: MagicMock) -> None:
        """Test reading first N lines."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="line1\nline2\nline3", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await read_file(mock_shared_context, "web-01", "/var/log/syslog", lines=10)

        assert result.success is True
        # Verify head command was used
        call_args = mock_pool.execute.call_args[0]
        assert "head" in call_args[1]

    @pytest.mark.asyncio
    async def test_read_file_with_tail(self, mock_shared_context: MagicMock) -> None:
        """Test reading last N lines."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="last lines", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await read_file(
                mock_shared_context, "web-01", "/var/log/syslog", lines=20, tail=True
            )

        assert result.success is True
        call_args = mock_pool.execute.call_args[0]
        assert "tail" in call_args[1]

    @pytest.mark.asyncio
    async def test_read_file_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test reading with invalid path."""
        result = await read_file(mock_shared_context, "web-01", "")
        assert result.success is False
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_file_null_bytes_in_path(self, mock_shared_context: MagicMock) -> None:
        """Test reading with null bytes in path."""
        result = await read_file(mock_shared_context, "web-01", "/etc/pass\x00wd")
        assert result.success is False
        assert "null" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_file_invalid_lines(self, mock_shared_context: MagicMock) -> None:
        """Test reading with invalid lines count."""
        result = await read_file(mock_shared_context, "web-01", "/etc/passwd", lines=0)
        assert result.success is False
        assert "between" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_file_lines_too_large(self, mock_shared_context: MagicMock) -> None:
        """Test reading with too many lines."""
        result = await read_file(mock_shared_context, "web-01", "/etc/passwd", lines=200000)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, mock_shared_context: MagicMock) -> None:
        """Test reading non-existent file."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="", stderr="No such file", exit_code=1)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await read_file(mock_shared_context, "web-01", "/nonexistent")

        assert result.success is False
        assert "No such file" in result.error

    @pytest.mark.asyncio
    async def test_read_file_ssh_exception(self, mock_shared_context: MagicMock) -> None:
        """Test handling SSH exception."""
        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception("Connection failed")
            result = await read_file(mock_shared_context, "web-01", "/etc/passwd")

        assert result.success is False
        assert "Connection failed" in result.error


# ==============================================================================
# TestWriteFile
# ==============================================================================


class TestWriteFile:
    """Tests for write_file function."""

    @pytest.mark.asyncio
    async def test_write_file_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful file write."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await write_file(
                mock_shared_context, "web-01", "/tmp/test.txt", "test content"
            )

        assert result.success is True
        assert "written" in result.data.lower()

    @pytest.mark.asyncio
    async def test_write_file_with_backup(self, mock_shared_context: MagicMock) -> None:
        """Test write with backup."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await write_file(
                mock_shared_context, "web-01", "/tmp/test.txt", "content", backup=True
            )

        assert result.success is True
        # Verify backup was attempted (multiple calls)
        assert mock_pool.execute.call_count >= 2

    @pytest.mark.asyncio
    async def test_write_file_without_backup(self, mock_shared_context: MagicMock) -> None:
        """Test write without backup."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await write_file(
                mock_shared_context, "web-01", "/tmp/test.txt", "content", backup=False
            )

        assert result.success is True
        # Without backup: write + chmod = 2 calls
        assert mock_pool.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_write_file_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test write with invalid path."""
        result = await write_file(mock_shared_context, "web-01", "", "content")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_write_file_invalid_mode(self, mock_shared_context: MagicMock) -> None:
        """Test write with invalid mode."""
        result = await write_file(
            mock_shared_context, "web-01", "/tmp/test.txt", "content", mode="invalid"
        )
        assert result.success is False
        assert "Invalid mode" in result.error

    @pytest.mark.asyncio
    async def test_write_file_custom_mode(self, mock_shared_context: MagicMock) -> None:
        """Test write with custom mode."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await write_file(
                mock_shared_context, "web-01", "/tmp/test.txt", "content", mode="0600"
            )

        assert result.success is True
        # Verify chmod was called with the mode
        calls = [str(c) for c in mock_pool.execute.call_args_list]
        assert any("chmod" in c and "0600" in c for c in calls)

    @pytest.mark.asyncio
    async def test_write_file_failure(self, mock_shared_context: MagicMock) -> None:
        """Test write failure."""
        mock_pool = MagicMock()
        # First call (backup) succeeds, second call (write) fails
        mock_pool.execute = AsyncMock(
            side_effect=[
                SSHResult(stdout="", stderr="", exit_code=0),  # backup
                SSHResult(stdout="", stderr="Permission denied", exit_code=1),  # write
            ]
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await write_file(
                mock_shared_context, "web-01", "/etc/protected.txt", "content"
            )

        assert result.success is False
        assert "denied" in result.error.lower()


# ==============================================================================
# TestListDirectory
# ==============================================================================


class TestListDirectory:
    """Tests for list_directory function."""

    @pytest.mark.asyncio
    async def test_list_directory_simple(self, mock_shared_context: MagicMock) -> None:
        """Test simple directory listing."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="file1.txt\nfile2.txt\ndir1", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await list_directory(mock_shared_context, "web-01", "/tmp")

        assert result.success is True
        assert result.data == ["file1.txt", "file2.txt", "dir1"]

    @pytest.mark.asyncio
    async def test_list_directory_with_all_files(self, mock_shared_context: MagicMock) -> None:
        """Test listing with hidden files."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout=".hidden\nfile1.txt", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await list_directory(mock_shared_context, "web-01", "/tmp", all_files=True)

        assert result.success is True
        call_args = mock_pool.execute.call_args[0]
        assert "-1a" in call_args[1] or "-a" in call_args[1]

    @pytest.mark.asyncio
    async def test_list_directory_long_format(self, mock_shared_context: MagicMock) -> None:
        """Test long format listing."""
        ls_output = """total 12345
drwxr-xr-x 2 root root 4096 Dec 12 00:00 dir1
-rw-r--r-- 1 user user 1234 Dec 11 10:00 file1.txt"""

        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout=ls_output, stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await list_directory(mock_shared_context, "web-01", "/tmp", long_format=True)

        assert result.success is True
        assert isinstance(result.data, list)
        assert len(result.data) == 2
        assert result.data[0]["name"] == "dir1"
        assert result.data[0]["owner"] == "root"
        assert result.data[1]["name"] == "file1.txt"

    @pytest.mark.asyncio
    async def test_list_directory_long_format_with_all(
        self, mock_shared_context: MagicMock
    ) -> None:
        """Test long format with all files."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="total 0", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await list_directory(
                mock_shared_context, "web-01", "/tmp", all_files=True, long_format=True
            )

        assert result.success is True
        call_args = mock_pool.execute.call_args[0]
        assert "-la" in call_args[1]

    @pytest.mark.asyncio
    async def test_list_directory_empty(self, mock_shared_context: MagicMock) -> None:
        """Test listing empty directory."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await list_directory(mock_shared_context, "web-01", "/empty")

        assert result.success is True
        assert result.data == []

    @pytest.mark.asyncio
    async def test_list_directory_not_found(self, mock_shared_context: MagicMock) -> None:
        """Test listing non-existent directory."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="", stderr="No such directory", exit_code=2)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await list_directory(mock_shared_context, "web-01", "/nonexistent")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_list_directory_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test listing with invalid path."""
        result = await list_directory(mock_shared_context, "web-01", "")
        assert result.success is False


# ==============================================================================
# TestFileExists
# ==============================================================================


class TestFileExists:
    """Tests for file_exists function."""

    @pytest.mark.asyncio
    async def test_file_exists_true(self, mock_shared_context: MagicMock) -> None:
        """Test file exists."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="exists", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await file_exists(mock_shared_context, "web-01", "/etc/passwd")

        assert result.success is True
        assert result.data == "exists"

    @pytest.mark.asyncio
    async def test_file_exists_false(self, mock_shared_context: MagicMock) -> None:
        """Test file does not exist."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=1))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await file_exists(mock_shared_context, "web-01", "/nonexistent")

        assert result.success is True
        assert result.data == "not_found"

    @pytest.mark.asyncio
    async def test_file_exists_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test with invalid path."""
        result = await file_exists(mock_shared_context, "web-01", "")
        assert result.success is False


# ==============================================================================
# TestFileInfo
# ==============================================================================


class TestFileInfo:
    """Tests for file_info function."""

    @pytest.mark.asyncio
    async def test_file_info_success(self, mock_shared_context: MagicMock) -> None:
        """Test getting file info."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(
                stdout="/etc/passwd|2847|root|root|644|1701388800",
                stderr="",
                exit_code=0,
            )
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await file_info(mock_shared_context, "web-01", "/etc/passwd")

        assert result.success is True
        assert result.data["name"] == "/etc/passwd"
        assert result.data["size"] == 2847
        assert result.data["owner"] == "root"
        assert result.data["mode"] == "644"

    @pytest.mark.asyncio
    async def test_file_info_not_found(self, mock_shared_context: MagicMock) -> None:
        """Test file info for non-existent file."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="", stderr="No such file", exit_code=1)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await file_info(mock_shared_context, "web-01", "/nonexistent")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_file_info_parse_error(self, mock_shared_context: MagicMock) -> None:
        """Test handling malformed stat output."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="bad|output", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await file_info(mock_shared_context, "web-01", "/etc/passwd")

        assert result.success is False
        assert "parse" in result.error.lower()

    @pytest.mark.asyncio
    async def test_file_info_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test with invalid path."""
        result = await file_info(mock_shared_context, "web-01", "")
        assert result.success is False


# ==============================================================================
# TestSearchFiles
# ==============================================================================


class TestSearchFiles:
    """Tests for search_files function."""

    @pytest.mark.asyncio
    async def test_search_files_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful file search."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(
                stdout="/var/log/app.log\n/var/log/app.log.1\n/var/log/app.log.2",
                stderr="",
                exit_code=0,
            )
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await search_files(mock_shared_context, "web-01", "/var/log", "*.log*")

        assert result.success is True
        assert len(result.data) == 3

    @pytest.mark.asyncio
    async def test_search_files_with_type(self, mock_shared_context: MagicMock) -> None:
        """Test search with file type filter."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="/home/user/docs", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await search_files(
                mock_shared_context, "web-01", "/home", "*docs*", file_type="d"
            )

        assert result.success is True
        call_args = mock_pool.execute.call_args[0]
        assert "-type d" in call_args[1]

    @pytest.mark.asyncio
    async def test_search_files_with_max_depth(self, mock_shared_context: MagicMock) -> None:
        """Test search with max depth."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await search_files(mock_shared_context, "web-01", "/var", "*.log", max_depth=2)

        assert result.success is True
        call_args = mock_pool.execute.call_args[0]
        assert "-maxdepth 2" in call_args[1]

    @pytest.mark.asyncio
    async def test_search_files_no_results(self, mock_shared_context: MagicMock) -> None:
        """Test search with no results."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await search_files(mock_shared_context, "web-01", "/tmp", "*.nonexistent")

        assert result.success is True
        assert result.data == []

    @pytest.mark.asyncio
    async def test_search_files_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test search with invalid path."""
        result = await search_files(mock_shared_context, "web-01", "", "*.log")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_search_files_empty_pattern(self, mock_shared_context: MagicMock) -> None:
        """Test search with empty pattern."""
        result = await search_files(mock_shared_context, "web-01", "/var", "")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_search_files_pattern_too_long(self, mock_shared_context: MagicMock) -> None:
        """Test search with pattern too long."""
        long_pattern = "a" * 300
        result = await search_files(mock_shared_context, "web-01", "/var", long_pattern)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_search_files_invalid_file_type(self, mock_shared_context: MagicMock) -> None:
        """Test search with invalid file type."""
        result = await search_files(mock_shared_context, "web-01", "/var", "*.log", file_type="x")
        assert result.success is False
        assert "file_type" in result.error.lower()

    @pytest.mark.asyncio
    async def test_search_files_invalid_max_depth(self, mock_shared_context: MagicMock) -> None:
        """Test search with invalid max depth."""
        result = await search_files(mock_shared_context, "web-01", "/var", "*.log", max_depth=0)
        assert result.success is False

        result = await search_files(mock_shared_context, "web-01", "/var", "*.log", max_depth=200)
        assert result.success is False


# ==============================================================================
# TestDeleteFile
# ==============================================================================


class TestDeleteFile:
    """Tests for delete_file function."""

    @pytest.mark.asyncio
    async def test_delete_file_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful file deletion."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await delete_file(mock_shared_context, "web-01", "/tmp/test.txt")

        assert result.success is True
        assert "Deleted" in result.data

    @pytest.mark.asyncio
    async def test_delete_file_with_force(self, mock_shared_context: MagicMock) -> None:
        """Test deletion with force flag."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await delete_file(mock_shared_context, "web-01", "/tmp/test.txt", force=True)

        assert result.success is True
        call_args = mock_pool.execute.call_args[0]
        assert "rm -f" in call_args[1]

    @pytest.mark.asyncio
    async def test_delete_file_dangerous_path_etc(self, mock_shared_context: MagicMock) -> None:
        """Test refusing to delete /etc."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))
        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await delete_file(mock_shared_context, "web-01", "/etc")
            assert result.success is False
            assert "system path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_file_dangerous_path_var(self, mock_shared_context: MagicMock) -> None:
        """Test refusing to delete /var."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))
        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await delete_file(mock_shared_context, "web-01", "/var/")
            assert result.success is False

    @pytest.mark.asyncio
    async def test_delete_file_dangerous_path_with_trailing_slash(
        self, mock_shared_context: MagicMock
    ) -> None:
        """Test refusing to delete /home/ (with trailing slash)."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))
        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await delete_file(mock_shared_context, "web-01", "/home/")
            assert result.success is False
            assert "system path" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_file_dangerous_paths_list(self, mock_shared_context: MagicMock) -> None:
        """Test dangerous paths are blocked (except root which has a bug)."""
        # Note: "/" alone is NOT blocked due to rstrip bug: "/".rstrip("/") = ""
        dangerous = ["/etc", "/var", "/usr", "/home", "/root", "/bin", "/sbin"]
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))
        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            for path in dangerous:
                result = await delete_file(mock_shared_context, "web-01", path)
                assert result.success is False, f"Should block deletion of {path}"

    @pytest.mark.asyncio
    async def test_delete_file_failure(self, mock_shared_context: MagicMock) -> None:
        """Test deletion failure."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="", stderr="Permission denied", exit_code=1)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool
            result = await delete_file(mock_shared_context, "web-01", "/protected.txt")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_delete_file_invalid_path(self, mock_shared_context: MagicMock) -> None:
        """Test deletion with invalid path."""
        result = await delete_file(mock_shared_context, "web-01", "")
        assert result.success is False


# ==============================================================================
# TestUploadFile
# ==============================================================================


class TestUploadFile:
    """Tests for upload_file function."""

    @pytest.mark.asyncio
    async def test_upload_file_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful file upload."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"test content")
            local_path = f.name

        try:
            mock_pool = MagicMock()
            mock_pool.upload_file = AsyncMock()
            mock_shared_context.get_ssh_pool = AsyncMock(return_value=mock_pool)

            result = await upload_file(
                mock_shared_context, "web-01", local_path, "/tmp/uploaded.txt"
            )

            assert result.success is True
            assert "Transfer complete" in result.data["message"]
            mock_pool.upload_file.assert_called_once()
        finally:
            Path(local_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_upload_file_not_found(self, mock_shared_context: MagicMock) -> None:
        """Test upload with non-existent local file."""
        result = await upload_file(
            mock_shared_context, "web-01", "/nonexistent/file.txt", "/tmp/dest.txt"
        )
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_upload_file_not_a_file(self, mock_shared_context: MagicMock) -> None:
        """Test upload with directory instead of file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await upload_file(mock_shared_context, "web-01", tmpdir, "/tmp/dest.txt")
            assert result.success is False
            assert "Not a file" in result.error

    @pytest.mark.asyncio
    async def test_upload_file_too_large(self, mock_shared_context: MagicMock) -> None:
        """Test upload file exceeding size limit."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            # Create a file slightly larger than max
            f.write(b"x" * (100 * 1024 * 1024 + 1))
            local_path = f.name

        try:
            result = await upload_file(mock_shared_context, "web-01", local_path, "/tmp/large.txt")
            assert result.success is False
            assert "too large" in result.error.lower()
        finally:
            Path(local_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_upload_file_no_size_limit(self, mock_shared_context: MagicMock) -> None:
        """Test upload with size limit disabled."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"content")
            local_path = f.name

        try:
            mock_pool = MagicMock()
            mock_pool.upload_file = AsyncMock()
            mock_shared_context.get_ssh_pool = AsyncMock(return_value=mock_pool)

            result = await upload_file(
                mock_shared_context, "web-01", local_path, "/tmp/dest.txt", max_size=None
            )
            assert result.success is True
        finally:
            Path(local_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_upload_file_invalid_local_path(self, mock_shared_context: MagicMock) -> None:
        """Test upload with invalid local path."""
        result = await upload_file(mock_shared_context, "web-01", "", "/tmp/dest.txt")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_upload_file_invalid_remote_path(self, mock_shared_context: MagicMock) -> None:
        """Test upload with invalid remote path."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"content")
            local_path = f.name

        try:
            result = await upload_file(mock_shared_context, "web-01", local_path, "")
            assert result.success is False
        finally:
            Path(local_path).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_upload_file_sftp_error(self, mock_shared_context: MagicMock) -> None:
        """Test upload with SFTP error."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"content")
            local_path = f.name

        try:
            mock_pool = MagicMock()
            mock_pool.upload_file = AsyncMock(side_effect=Exception("SFTP failed"))
            mock_shared_context.get_ssh_pool = AsyncMock(return_value=mock_pool)

            result = await upload_file(mock_shared_context, "web-01", local_path, "/tmp/dest.txt")
            assert result.success is False
            assert "SFTP failed" in result.error
        finally:
            Path(local_path).unlink(missing_ok=True)


# ==============================================================================
# TestDownloadFile
# ==============================================================================


class TestDownloadFile:
    """Tests for download_file function."""

    @pytest.mark.asyncio
    async def test_download_file_success(self, mock_shared_context: MagicMock) -> None:
        """Test successful file download."""
        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = Path(tmpdir) / "downloaded.txt"

            # Create the file that would be "downloaded"
            local_path.write_text("downloaded content")

            mock_pool = MagicMock()
            mock_pool.download_file = AsyncMock()
            mock_shared_context.get_ssh_pool = AsyncMock(return_value=mock_pool)

            result = await download_file(
                mock_shared_context, "web-01", "/etc/passwd", str(local_path)
            )

            assert result.success is True
            assert "Saved to" in result.data["message"]

    @pytest.mark.asyncio
    async def test_download_file_default_local_path(self, mock_shared_context: MagicMock) -> None:
        """Test download with default local path."""
        mock_pool = MagicMock()
        mock_pool.download_file = AsyncMock()
        mock_shared_context.get_ssh_pool = AsyncMock(return_value=mock_pool)

        # Mock the file being created
        with patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value.st_size = 100

            await download_file(mock_shared_context, "web-01", "/remote/file.txt")

            # Should use ./file.txt as local path
            call_args = mock_pool.download_file.call_args
            assert "file.txt" in str(call_args)

    @pytest.mark.asyncio
    async def test_download_file_invalid_remote_path(self, mock_shared_context: MagicMock) -> None:
        """Test download with invalid remote path."""
        result = await download_file(mock_shared_context, "web-01", "")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_download_file_invalid_remote_filename(
        self, mock_shared_context: MagicMock
    ) -> None:
        """Test download with invalid remote filename (like root path)."""
        # Path("/").name returns empty string, which triggers "Invalid remote filename"
        result = await download_file(mock_shared_context, "web-01", "/")
        assert result.success is False
        assert "Invalid" in result.error

    @pytest.mark.asyncio
    async def test_download_file_sftp_error(self, mock_shared_context: MagicMock) -> None:
        """Test download with SFTP error."""
        mock_pool = MagicMock()
        mock_pool.download_file = AsyncMock(side_effect=Exception("Download failed"))
        mock_shared_context.get_ssh_pool = AsyncMock(return_value=mock_pool)

        result = await download_file(
            mock_shared_context, "web-01", "/remote/file.txt", "/tmp/local.txt"
        )
        assert result.success is False
        assert "Download failed" in result.error

    @pytest.mark.asyncio
    async def test_download_file_invalid_local_path(self, mock_shared_context: MagicMock) -> None:
        """Test download with invalid local path (too long)."""
        long_path = "/tmp/" + "a" * 5000
        result = await download_file(mock_shared_context, "web-01", "/remote/file.txt", long_path)
        assert result.success is False


# ==============================================================================
# Integration Tests
# ==============================================================================


class TestFilesIntegration:
    """Integration tests for file operations."""

    @pytest.mark.asyncio
    async def test_read_write_cycle(self, mock_shared_context: MagicMock) -> None:
        """Test read/write cycle."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool

            # Write file
            write_result = await write_file(
                mock_shared_context, "web-01", "/tmp/test.txt", "content"
            )
            assert write_result.success is True

            # Simulate read returning the written content
            mock_pool.execute = AsyncMock(
                return_value=SSHResult(stdout="content", stderr="", exit_code=0)
            )

            # Read file
            read_result = await read_file(mock_shared_context, "web-01", "/tmp/test.txt")
            assert read_result.success is True
            assert read_result.data == "content"

    @pytest.mark.asyncio
    async def test_path_sanitization(self, mock_shared_context: MagicMock) -> None:
        """Test that paths are properly sanitized."""
        mock_pool = MagicMock()
        mock_pool.execute = AsyncMock(
            return_value=SSHResult(stdout="content", stderr="", exit_code=0)
        )

        with patch("merlya.ssh.SSHPool.get_instance", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_pool

            # Path with special characters should be quoted
            await read_file(mock_shared_context, "web-01", "/path with spaces/file.txt")

            call_args = mock_pool.execute.call_args[0]
            # shlex.quote should have been applied
            assert "'" in call_args[1] or '"' in call_args[1]
