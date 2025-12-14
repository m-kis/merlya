from __future__ import annotations


def test_system_tools_package_exports_list_cron() -> None:
    from merlya.tools import system

    assert hasattr(system, "list_cron")
    assert callable(system.list_cron)
