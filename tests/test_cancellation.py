from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_execute_with_elevation_propagates_cancelled_error() -> None:
    from merlya.tools.core.ssh_elevation import execute_with_elevation
    from merlya.tools.core.ssh_models import _DummyFailedResult

    class _Perms:
        async def prepare_command(self, _host: str, _command: str):  # type: ignore[no-untyped-def]
            raise asyncio.CancelledError()

    class _Ctx:
        async def get_permissions(self) -> _Perms:  # type: ignore[override]
            return _Perms()

    async def _execute_fn(  # type: ignore[no-untyped-def]
        _ssh_pool, _host, _host_entry, _cmd, _timeout, _input_data, _ssh_opts
    ):
        raise AssertionError("execute_fn should not be called")

    with pytest.raises(asyncio.CancelledError):
        await execute_with_elevation(
            _Ctx(),  # type: ignore[arg-type]
            ssh_pool=None,  # type: ignore[arg-type]
            host="example",
            host_entry=None,
            base_command="id",
            timeout=1,
            ssh_opts=None,  # type: ignore[arg-type]
            initial_result=_DummyFailedResult(),
            execute_fn=_execute_fn,
        )

