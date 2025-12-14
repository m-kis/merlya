from __future__ import annotations

from merlya.ssh.types import is_transient_error


def test_is_transient_error_includes_open_failed() -> None:
    assert is_transient_error(RuntimeError("open failed"))
    assert is_transient_error(RuntimeError("channel open failed"))
