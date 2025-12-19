"""
Merlya Tools - System legacy compatibility module.

This module exists for backward compatibility with older imports:
`from merlya.tools.system.tools import ...`

The refactor split the original monolithic module into specialized modules.
Tests and external callers may still patch `merlya.tools.system.tools.ssh_execute`,
so we proxy `ssh_execute` through this module and wire submodules to use it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.tools.core import ToolResult
from merlya.tools.core import ssh_execute as _core_ssh_execute

from . import (
    basic_info as _basic_info,
)
from . import (
    cpu_tools as _cpu_tools,
)
from . import (
    disk_tools as _disk_tools,
)
from . import (
    docker_tools as _docker_tools,
)
from . import (
    log_tools as _log_tools,
)
from . import (
    memory_tools as _memory_tools,
)
from . import (
    process_tools as _process_tools,
)
from . import (
    service_tools as _service_tools,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Patch target for tests and backward compatibility
ssh_execute = _core_ssh_execute
_SSH_EXECUTE_ATTR = "ssh_execute"


async def _proxy_ssh_execute(
    ctx: SharedContext,
    host: str,
    command: str,
    timeout: int = 60,
    connect_timeout: int | None = None,
    via: str | None = None,
) -> ToolResult:
    """Proxy to the module-level `ssh_execute` (supports monkeypatching in tests)."""
    return await ssh_execute(
        ctx,
        host,
        command,
        timeout=timeout,
        connect_timeout=connect_timeout,
        via=via,
    )


# Wire refactored submodules to use the proxy so patching this module works.
setattr(_basic_info, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_disk_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_memory_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_cpu_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_process_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_service_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_log_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)
setattr(_docker_tools, _SSH_EXECUTE_ATTR, _proxy_ssh_execute)


# Public re-exports (legacy API surface)
from .basic_info import get_system_info  # noqa: E402
from .cpu_tools import check_cpu  # noqa: E402
from .disk_tools import check_all_disks, check_disk_usage  # noqa: E402
from .docker_tools import check_docker  # noqa: E402
from .log_tools import analyze_logs  # noqa: E402
from .memory_tools import check_memory  # noqa: E402
from .process_tools import list_processes  # noqa: E402
from .service_tools import check_service_status  # noqa: E402
from .validation import _validate_path, _validate_service_name, _validate_username  # noqa: E402

__all__ = [
    "_validate_path",
    "_validate_service_name",
    "_validate_username",
    "analyze_logs",
    "check_all_disks",
    "check_cpu",
    "check_disk_usage",
    "check_docker",
    "check_memory",
    "check_service_status",
    "get_system_info",
    "list_processes",
    "ssh_execute",
]
