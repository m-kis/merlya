"""Tests for hosts command security validations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from merlya.commands.handlers.hosts_io import (
    MAX_FILE_SIZE_BYTES,
    MAX_PORT,
    MIN_PORT,
    check_file_size,
    validate_file_path,
    validate_port,
    validate_tag,
)


class TestValidatePort:
    """Tests for port validation."""

    def test_valid_port(self) -> None:
        """Test valid ports are accepted."""
        assert validate_port("22") == 22
        assert validate_port("80") == 80
        assert validate_port("443") == 443
        assert validate_port("8080") == 8080
        assert validate_port("65535") == 65535

    def test_min_max_boundaries(self) -> None:
        """Test port boundary values."""
        assert validate_port(str(MIN_PORT)) == MIN_PORT
        assert validate_port(str(MAX_PORT)) == MAX_PORT

    def test_port_below_min_returns_default(self) -> None:
        """Test port below minimum returns default."""
        assert validate_port("0") == 22
        assert validate_port("-1") == 22

    def test_port_above_max_returns_default(self) -> None:
        """Test port above maximum returns default."""
        assert validate_port("65536") == 22
        assert validate_port("100000") == 22

    def test_non_numeric_returns_default(self) -> None:
        """Test non-numeric input returns default."""
        assert validate_port("abc") == 22
        assert validate_port("") == 22
        assert validate_port("22.5") == 22

    def test_custom_default(self) -> None:
        """Test custom default value."""
        assert validate_port("invalid", default=2222) == 2222
        assert validate_port("0", default=8080) == 8080


class TestValidateTag:
    """Tests for tag validation."""

    def test_valid_tags(self) -> None:
        """Test valid tags are accepted."""
        assert validate_tag("webserver")[0] is True
        assert validate_tag("web-server")[0] is True
        assert validate_tag("web_server")[0] is True
        assert validate_tag("server01")[0] is True
        assert validate_tag("ansible:web")[0] is True

    def test_empty_tag_rejected(self) -> None:
        """Test empty tag is rejected."""
        is_valid, msg = validate_tag("")
        assert is_valid is False
        assert "empty" in msg.lower()

    def test_tag_with_special_chars_rejected(self) -> None:
        """Test tag with special characters is rejected."""
        is_valid, _ = validate_tag("web server")
        assert is_valid is False
        is_valid, _ = validate_tag("web@server")
        assert is_valid is False
        is_valid, _ = validate_tag("web/server")
        assert is_valid is False

    def test_tag_max_length(self) -> None:
        """Test tag length limit."""
        # 50 chars should be OK
        is_valid, _ = validate_tag("a" * 50)
        assert is_valid is True

        # 51 chars should fail
        is_valid, _ = validate_tag("a" * 51)
        assert is_valid is False


class TestValidateFilePath:
    """Tests for file path validation."""

    def test_home_directory_allowed(self, tmp_path: Path) -> None:
        """Test paths in home directory are allowed."""
        with patch("merlya.commands.handlers.hosts_io.ALLOWED_IMPORT_DIRS", [tmp_path]):
            test_file = tmp_path / "hosts.json"
            test_file.write_text("[]")
            is_valid, _ = validate_file_path(test_file)
            assert is_valid is True

    def test_path_traversal_blocked(self) -> None:
        """Test path traversal attempts are blocked."""
        _, msg = validate_file_path(Path("/../../etc/passwd"))
        # Should be blocked either by traversal pattern or not in allowed dirs
        # depending on resolution
        assert "denied" in msg.lower() or "invalid" in msg.lower()

    def test_proc_paths_blocked(self) -> None:
        """Test /proc paths are blocked."""
        is_valid, msg = validate_file_path(Path("/proc/1/cmdline"))
        assert is_valid is False
        assert "denied" in msg.lower() or "invalid" in msg.lower()

    def test_sys_paths_blocked(self) -> None:
        """Test /sys paths are blocked."""
        is_valid, _ = validate_file_path(Path("/sys/kernel/hostname"))
        assert is_valid is False


class TestEtcHostsValidation:
    """Tests for /etc/hosts path validation (handles macOS symlinks)."""

    def test_etc_hosts_allowed(self) -> None:
        """Test /etc/hosts is allowed (handles /etc -> /private/etc symlink on macOS)."""
        etc_hosts = Path("/etc/hosts")
        if etc_hosts.exists():
            is_valid, msg = validate_file_path(etc_hosts)
            assert is_valid is True, f"Expected /etc/hosts to be allowed, got: {msg}"


class TestCheckFileSize:
    """Tests for file size validation."""

    def test_small_file_allowed(self, tmp_path: Path) -> None:
        """Test small files are allowed."""
        test_file = tmp_path / "small.json"
        test_file.write_text('{"hosts": []}')
        is_valid, _ = check_file_size(test_file)
        assert is_valid is True

    def test_large_file_rejected(self, tmp_path: Path) -> None:
        """Test large files are rejected."""
        test_file = tmp_path / "large.json"
        # Write more than MAX_FILE_SIZE_BYTES
        test_file.write_bytes(b"x" * (MAX_FILE_SIZE_BYTES + 1))
        is_valid, msg = check_file_size(test_file)
        assert is_valid is False
        assert "too large" in msg.lower()

    def test_nonexistent_file_error(self, tmp_path: Path) -> None:
        """Test nonexistent file returns error."""
        test_file = tmp_path / "nonexistent.json"
        is_valid, msg = check_file_size(test_file)
        assert is_valid is False
        assert "cannot read" in msg.lower()

    def test_file_at_exact_limit(self, tmp_path: Path) -> None:
        """Test file at exact limit is allowed."""
        test_file = tmp_path / "exact.json"
        test_file.write_bytes(b"x" * MAX_FILE_SIZE_BYTES)
        is_valid, _ = check_file_size(test_file)
        assert is_valid is True
