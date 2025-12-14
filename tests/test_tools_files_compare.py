"""Tests for merlya.tools.files.compare module."""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.ssh.types import SSHResult
from merlya.tools.files import compare as compare_module


class TestGetFileInfo:
    """Tests for _get_file_info helper."""

    @pytest.mark.asyncio
    async def test_remote_non_utf8_content_does_not_error(self) -> None:
        """Remote comparisons should not fail on non-UTF8 file bytes."""
        raw_bytes = b"\xff\xfehello\n"
        base64_content = base64.b64encode(raw_bytes).decode("ascii") + "\n"
        stdout = f"{base64_content}\0abcdabcdabcdabcd\0{len(raw_bytes)}"

        with patch(
            "merlya.tools.files.compare.execute_security_command",
            new=AsyncMock(return_value=SSHResult(stdout=stdout, stderr="", exit_code=0)),
        ):
            content, file_hash, size = await compare_module._get_file_info(
                MagicMock(),
                "web-01",
                "/tmp/non-utf8.bin",
            )

        assert "hello" in content
        assert "\ufffd" in content
        assert file_hash == "abcdabcdabcdabcd"
        assert size == len(raw_bytes)
