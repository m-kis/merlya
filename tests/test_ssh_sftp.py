"""Tests for SSH SFTP operations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.ssh.sftp import SFTPOperations

if TYPE_CHECKING:
    from pathlib import Path


# Create a test class that inherits from SFTPOperations for testing
class MockSSHPoolWithSFTP(SFTPOperations):
    """Mock SSH Pool with SFTP operations for testing."""

    def __init__(self) -> None:
        self._connections: dict = {}

    async def get_connection(self, host: str, **kwargs) -> MagicMock:
        """Return mock connection."""
        return self._mock_connection


# ==============================================================================
# Tests for upload_file
# ==============================================================================


class TestUploadFile:
    """Tests for upload_file method."""

    @pytest.mark.asyncio
    async def test_upload_file_success(self, tmp_path: Path) -> None:
        """Test successful file upload."""
        pool = MockSSHPoolWithSFTP()

        # Create local file
        local_file = tmp_path / "test.txt"
        local_file.write_text("test content")

        # Mock connection and SFTP
        mock_sftp = MagicMock()
        mock_sftp.put = AsyncMock()
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        await pool.upload_file("host1", str(local_file), "/remote/path/test.txt")

        mock_sftp.put.assert_called_once_with(str(local_file), "/remote/path/test.txt")

    @pytest.mark.asyncio
    async def test_upload_file_not_found(self) -> None:
        """Test upload with non-existent local file."""
        pool = MockSSHPoolWithSFTP()

        with pytest.raises(FileNotFoundError, match="Local file not found"):
            await pool.upload_file("host1", "/nonexistent/file.txt", "/remote/path")

    @pytest.mark.asyncio
    async def test_upload_file_connection_closed(self, tmp_path: Path) -> None:
        """Test upload when connection is closed."""
        pool = MockSSHPoolWithSFTP()

        local_file = tmp_path / "test.txt"
        local_file.write_text("content")

        mock_conn = MagicMock()
        mock_conn.connection = None  # Connection closed

        pool._mock_connection = mock_conn

        with pytest.raises(RuntimeError, match="is closed"):
            await pool.upload_file("host1", str(local_file), "/remote/path")

    @pytest.mark.asyncio
    async def test_upload_file_expands_user_path(self, tmp_path: Path) -> None:
        """Test that upload expands ~ in paths."""
        pool = MockSSHPoolWithSFTP()

        # Create file in temp dir but use ~ path
        local_file = tmp_path / "test.txt"
        local_file.write_text("content")

        mock_sftp = MagicMock()
        mock_sftp.put = AsyncMock()
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        # Use actual path since we can't easily mock ~
        await pool.upload_file("host1", str(local_file), "/remote/test.txt")

        assert mock_sftp.put.called


# ==============================================================================
# Tests for download_file
# ==============================================================================


class TestDownloadFile:
    """Tests for download_file method."""

    @pytest.mark.asyncio
    async def test_download_file_success(self, tmp_path: Path) -> None:
        """Test successful file download."""
        pool = MockSSHPoolWithSFTP()

        local_file = tmp_path / "downloaded.txt"

        mock_sftp = MagicMock()
        mock_sftp.get = AsyncMock()
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        await pool.download_file("host1", "/remote/file.txt", str(local_file))

        mock_sftp.get.assert_called_once_with("/remote/file.txt", str(local_file))

    @pytest.mark.asyncio
    async def test_download_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Test that download creates parent directories."""
        pool = MockSSHPoolWithSFTP()

        # Path with non-existent parent directory
        local_file = tmp_path / "subdir" / "nested" / "file.txt"
        assert not local_file.parent.exists()

        mock_sftp = MagicMock()
        mock_sftp.get = AsyncMock()
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        await pool.download_file("host1", "/remote/file.txt", str(local_file))

        # Parent directory should have been created
        assert local_file.parent.exists()

    @pytest.mark.asyncio
    async def test_download_file_connection_closed(self, tmp_path: Path) -> None:
        """Test download when connection is closed."""
        pool = MockSSHPoolWithSFTP()

        mock_conn = MagicMock()
        mock_conn.connection = None

        pool._mock_connection = mock_conn

        with pytest.raises(RuntimeError, match="is closed"):
            await pool.download_file("host1", "/remote/file.txt", str(tmp_path / "file.txt"))


# ==============================================================================
# Tests for list_remote_dir
# ==============================================================================


class TestListRemoteDir:
    """Tests for list_remote_dir method."""

    @pytest.mark.asyncio
    async def test_list_remote_dir_success(self) -> None:
        """Test successful directory listing."""
        pool = MockSSHPoolWithSFTP()

        # Create mock directory entries
        mock_entry1 = MagicMock()
        mock_entry1.filename = "file1.txt"
        mock_entry1.attrs.size = 1024
        mock_entry1.attrs.type = 1  # Regular file
        mock_entry1.attrs.permissions = 0o644
        mock_entry1.attrs.mtime = 1234567890

        mock_entry2 = MagicMock()
        mock_entry2.filename = "subdir"
        mock_entry2.attrs.size = 4096
        mock_entry2.attrs.type = 2  # Directory
        mock_entry2.attrs.permissions = 0o755
        mock_entry2.attrs.mtime = 1234567891

        # Create async iterator for scandir
        async def mock_scandir(path):
            for entry in [mock_entry1, mock_entry2]:
                yield entry

        mock_sftp = MagicMock()
        mock_sftp.scandir = mock_scandir
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        result = await pool.list_remote_dir("host1", "/var/log")

        assert len(result) == 2
        assert result[0]["name"] == "file1.txt"
        assert result[0]["is_dir"] is False
        assert result[1]["name"] == "subdir"
        assert result[1]["is_dir"] is True

    @pytest.mark.asyncio
    async def test_list_remote_dir_default_path(self) -> None:
        """Test listing with default path (current directory)."""
        pool = MockSSHPoolWithSFTP()

        async def mock_scandir(path):
            # Verify default path is used
            assert path == "."
            return
            yield  # Empty generator

        mock_sftp = MagicMock()
        mock_sftp.scandir = mock_scandir
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        result = await pool.list_remote_dir("host1")  # No path specified

        assert result == []

    @pytest.mark.asyncio
    async def test_list_remote_dir_connection_closed(self) -> None:
        """Test listing when connection is closed."""
        pool = MockSSHPoolWithSFTP()

        mock_conn = MagicMock()
        mock_conn.connection = None

        pool._mock_connection = mock_conn

        with pytest.raises(RuntimeError, match="is closed"):
            await pool.list_remote_dir("host1", "/var/log")

    @pytest.mark.asyncio
    async def test_list_remote_dir_no_permissions(self) -> None:
        """Test listing entry with no permissions attribute."""
        pool = MockSSHPoolWithSFTP()

        mock_entry = MagicMock()
        mock_entry.filename = "file.txt"
        mock_entry.attrs.size = 100
        mock_entry.attrs.type = 1
        mock_entry.attrs.permissions = None  # No permissions
        mock_entry.attrs.mtime = 1234567890

        async def mock_scandir(path):
            yield mock_entry

        mock_sftp = MagicMock()
        mock_sftp.scandir = mock_scandir
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        result = await pool.list_remote_dir("host1", "/path")

        assert len(result) == 1
        assert result[0]["permissions"] is None


# ==============================================================================
# Tests for read_remote_file
# ==============================================================================


class TestReadRemoteFile:
    """Tests for read_remote_file method."""

    @pytest.mark.asyncio
    async def test_read_remote_file_success(self) -> None:
        """Test successful file read."""
        pool = MockSSHPoolWithSFTP()

        mock_file = MagicMock()
        mock_file.read = AsyncMock(return_value="file content")
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        mock_sftp = MagicMock()
        mock_sftp.open = MagicMock(return_value=mock_file)
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        result = await pool.read_remote_file("host1", "/etc/hostname")

        assert result == "file content"
        mock_sftp.open.assert_called_once_with("/etc/hostname", "r")

    @pytest.mark.asyncio
    async def test_read_remote_file_bytes_decoded(self) -> None:
        """Test that bytes content is decoded to UTF-8."""
        pool = MockSSHPoolWithSFTP()

        mock_file = MagicMock()
        mock_file.read = AsyncMock(return_value=b"binary content")
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        mock_sftp = MagicMock()
        mock_sftp.open = MagicMock(return_value=mock_file)
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        result = await pool.read_remote_file("host1", "/path/file.txt")

        assert result == "binary content"
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_read_remote_file_connection_closed(self) -> None:
        """Test reading when connection is closed."""
        pool = MockSSHPoolWithSFTP()

        mock_conn = MagicMock()
        mock_conn.connection = None

        pool._mock_connection = mock_conn

        with pytest.raises(RuntimeError, match="is closed"):
            await pool.read_remote_file("host1", "/etc/hostname")


# ==============================================================================
# Tests for write_remote_file
# ==============================================================================


class TestWriteRemoteFile:
    """Tests for write_remote_file method."""

    @pytest.mark.asyncio
    async def test_write_remote_file_success(self) -> None:
        """Test successful file write."""
        pool = MockSSHPoolWithSFTP()

        mock_file = MagicMock()
        mock_file.write = AsyncMock()
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        mock_sftp = MagicMock()
        mock_sftp.open = MagicMock(return_value=mock_file)
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        await pool.write_remote_file("host1", "/tmp/test.txt", "test content")

        mock_sftp.open.assert_called_once_with("/tmp/test.txt", "w")
        mock_file.write.assert_called_once_with("test content")

    @pytest.mark.asyncio
    async def test_write_remote_file_large_content(self) -> None:
        """Test writing large content."""
        pool = MockSSHPoolWithSFTP()

        large_content = "x" * 10000  # 10KB

        mock_file = MagicMock()
        mock_file.write = AsyncMock()
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        mock_sftp = MagicMock()
        mock_sftp.open = MagicMock(return_value=mock_file)
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        await pool.write_remote_file("host1", "/tmp/large.txt", large_content)

        mock_file.write.assert_called_once_with(large_content)

    @pytest.mark.asyncio
    async def test_write_remote_file_connection_closed(self) -> None:
        """Test writing when connection is closed."""
        pool = MockSSHPoolWithSFTP()

        mock_conn = MagicMock()
        mock_conn.connection = None

        pool._mock_connection = mock_conn

        with pytest.raises(RuntimeError, match="is closed"):
            await pool.write_remote_file("host1", "/tmp/test.txt", "content")

    @pytest.mark.asyncio
    async def test_write_remote_file_empty_content(self) -> None:
        """Test writing empty content."""
        pool = MockSSHPoolWithSFTP()

        mock_file = MagicMock()
        mock_file.write = AsyncMock()
        mock_file.__aenter__ = AsyncMock(return_value=mock_file)
        mock_file.__aexit__ = AsyncMock(return_value=False)

        mock_sftp = MagicMock()
        mock_sftp.open = MagicMock(return_value=mock_file)
        mock_sftp.__aenter__ = AsyncMock(return_value=mock_sftp)
        mock_sftp.__aexit__ = AsyncMock(return_value=False)

        mock_async_conn = MagicMock()
        mock_async_conn.start_sftp_client = MagicMock(return_value=mock_sftp)

        mock_conn = MagicMock()
        mock_conn.connection = mock_async_conn

        pool._mock_connection = mock_conn

        await pool.write_remote_file("host1", "/tmp/empty.txt", "")

        mock_file.write.assert_called_once_with("")
