"""Tests for SSH key validation module."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from merlya.ssh.validation import (
    _get_ppk_conversion_message,
    _is_ppk_format,
    validate_private_key,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestPPKDetection:
    """Tests for PuTTY PPK format detection."""

    def test_detects_ppk_v2_format(self, tmp_path: Path) -> None:
        """Test detection of PPK version 2 format."""
        ppk_file = tmp_path / "key.ppk"
        ppk_file.write_bytes(
            b"PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\nComment: test@example.com\n"
        )

        assert _is_ppk_format(ppk_file) is True

    def test_detects_ppk_v3_format(self, tmp_path: Path) -> None:
        """Test detection of PPK version 3 format."""
        ppk_file = tmp_path / "key.ppk"
        ppk_file.write_bytes(
            b"PuTTY-User-Key-File-3: ssh-ed25519\n"
            b"Encryption: aes256-cbc\n"
            b"Comment: test@example.com\n"
        )

        assert _is_ppk_format(ppk_file) is True

    def test_rejects_openssh_format(self, tmp_path: Path) -> None:
        """Test that OpenSSH format is not detected as PPK."""
        openssh_file = tmp_path / "id_ed25519"
        openssh_file.write_bytes(
            b"-----BEGIN OPENSSH PRIVATE KEY-----\n"
            b"b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB...\n"
            b"-----END OPENSSH PRIVATE KEY-----\n"
        )

        assert _is_ppk_format(openssh_file) is False

    def test_rejects_pem_format(self, tmp_path: Path) -> None:
        """Test that PEM format is not detected as PPK."""
        pem_file = tmp_path / "key.pem"
        pem_file.write_bytes(
            b"-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n"
        )

        assert _is_ppk_format(pem_file) is False

    def test_handles_nonexistent_file(self, tmp_path: Path) -> None:
        """Test handling of nonexistent file."""
        nonexistent = tmp_path / "nonexistent.ppk"

        assert _is_ppk_format(nonexistent) is False

    def test_handles_unreadable_file(self, tmp_path: Path) -> None:
        """Test handling of unreadable file."""
        # Create a file then remove read permissions
        unreadable = tmp_path / "unreadable.ppk"
        unreadable.write_bytes(b"PuTTY-User-Key-File-2: ssh-rsa\n")
        unreadable.chmod(0o000)

        try:
            # Should return False on permission error
            assert _is_ppk_format(unreadable) is False
        finally:
            # Restore permissions for cleanup
            unreadable.chmod(0o644)

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Test handling of empty file."""
        empty_file = tmp_path / "empty.ppk"
        empty_file.write_bytes(b"")

        assert _is_ppk_format(empty_file) is False


class TestPPKConversionMessage:
    """Tests for PPK conversion message generation."""

    def test_message_includes_file_path(self, tmp_path: Path) -> None:
        """Test that message includes the file path."""
        key_path = tmp_path / "mykey.ppk"
        message = _get_ppk_conversion_message(key_path)

        assert str(key_path) in message
        assert "mykey.ppk" in message

    def test_message_includes_puttygen_option(self, tmp_path: Path) -> None:
        """Test that message includes puttygen conversion option."""
        key_path = tmp_path / "key.ppk"
        message = _get_ppk_conversion_message(key_path)

        assert "puttygen" in message.lower()
        assert "-O private-openssh" in message

    def test_message_includes_puttygen_windows_option(self, tmp_path: Path) -> None:
        """Test that message includes PuTTYgen Windows instructions."""
        key_path = tmp_path / "key.ppk"
        message = _get_ppk_conversion_message(key_path)

        assert "PuTTYgen" in message
        assert "Export OpenSSH key" in message

    def test_message_includes_ssh_keygen_option(self, tmp_path: Path) -> None:
        """Test that message includes ssh-keygen conversion option."""
        key_path = tmp_path / "key.ppk"
        message = _get_ppk_conversion_message(key_path)

        assert "ssh-keygen" in message

    def test_message_suggests_output_filename(self, tmp_path: Path) -> None:
        """Test that message suggests output filename based on input."""
        key_path = tmp_path / "mykey.ppk"
        message = _get_ppk_conversion_message(key_path)

        # Should suggest mykey_openssh as output
        assert "mykey_openssh" in message


class TestValidatePrivateKey:
    """Tests for private key validation."""

    @pytest.mark.asyncio
    async def test_rejects_ppk_format(self, tmp_path: Path) -> None:
        """Test that PPK format keys are rejected with helpful message."""
        ppk_file = tmp_path / "key.ppk"
        ppk_file.write_bytes(b"PuTTY-User-Key-File-2: ssh-rsa\nEncryption: none\n")

        success, message = await validate_private_key(ppk_file)

        assert success is False
        assert "PPK format is not supported" in message
        assert "puttygen" in message.lower()

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that nonexistent files are rejected."""
        nonexistent = tmp_path / "nonexistent_key"

        success, message = await validate_private_key(nonexistent)

        assert success is False
        assert "not found" in message.lower()

    @pytest.mark.asyncio
    async def test_validates_valid_openssh_key(self, tmp_path: Path) -> None:
        """Test validation of a valid OpenSSH key."""
        # Generate a real ed25519 key for testing
        import asyncssh

        key = asyncssh.generate_private_key("ssh-ed25519")
        key_file = tmp_path / "id_ed25519"
        key_file.write_bytes(key.export_private_key())
        key_file.chmod(0o600)

        success, message = await validate_private_key(key_file)

        assert success is True
        assert "ed25519" in message.lower()

    @pytest.mark.asyncio
    async def test_rejects_bad_permissions_on_unix(self, tmp_path: Path) -> None:
        """Test that keys with bad permissions are rejected on Unix."""
        import sys

        if sys.platform == "win32":
            pytest.skip("Permission check only on Unix")

        import asyncssh

        key = asyncssh.generate_private_key("ssh-ed25519")
        key_file = tmp_path / "id_ed25519"
        key_file.write_bytes(key.export_private_key())
        key_file.chmod(0o644)  # Too open

        success, message = await validate_private_key(key_file)

        assert success is False
        assert "permissions" in message.lower()

    @pytest.mark.asyncio
    async def test_accepts_600_permissions(self, tmp_path: Path) -> None:
        """Test that keys with 600 permissions are accepted."""
        import sys

        if sys.platform == "win32":
            pytest.skip("Permission check only on Unix")

        import asyncssh

        key = asyncssh.generate_private_key("ssh-ed25519")
        key_file = tmp_path / "id_ed25519"
        key_file.write_bytes(key.export_private_key())
        key_file.chmod(0o600)

        success, _message = await validate_private_key(key_file)

        assert success is True

    @pytest.mark.asyncio
    async def test_accepts_400_permissions(self, tmp_path: Path) -> None:
        """Test that keys with 400 permissions are accepted."""
        import sys

        if sys.platform == "win32":
            pytest.skip("Permission check only on Unix")

        import asyncssh

        key = asyncssh.generate_private_key("ssh-ed25519")
        key_file = tmp_path / "id_ed25519"
        key_file.write_bytes(key.export_private_key())
        key_file.chmod(0o400)

        success, _message = await validate_private_key(key_file)

        assert success is True

    @pytest.mark.asyncio
    async def test_detects_encrypted_key(self, tmp_path: Path) -> None:
        """Test that encrypted keys are detected."""
        import asyncssh

        key = asyncssh.generate_private_key("ssh-ed25519")
        key_file = tmp_path / "id_ed25519_enc"
        # Export with passphrase (requires bcrypt)
        try:
            key_file.write_bytes(key.export_private_key(passphrase="testpass"))
        except asyncssh.KeyExportError:
            pytest.skip("bcrypt not available for encrypted key export")
        key_file.chmod(0o600)

        success, message = await validate_private_key(key_file)

        assert success is False
        assert "encrypted" in message.lower() or "passphrase" in message.lower()

    @pytest.mark.asyncio
    async def test_validates_encrypted_key_with_passphrase(self, tmp_path: Path) -> None:
        """Test that encrypted keys can be validated with passphrase."""
        import asyncssh

        key = asyncssh.generate_private_key("ssh-ed25519")
        key_file = tmp_path / "id_ed25519_enc"
        try:
            key_file.write_bytes(key.export_private_key(passphrase="testpass"))
        except asyncssh.KeyExportError:
            pytest.skip("bcrypt not available for encrypted key export")
        key_file.chmod(0o600)

        success, _message = await validate_private_key(key_file, passphrase="testpass")

        assert success is True
