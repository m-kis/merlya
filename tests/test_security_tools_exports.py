"""Tests for the security tools re-export module."""

from __future__ import annotations


def test_security_tools_module_exports_public_api() -> None:
    from merlya.tools.security import tools as security_tools

    assert "check_failed_logins" in security_tools.__all__
    assert callable(security_tools.check_failed_logins)
    assert security_tools._execute_command is security_tools.execute_security_command
