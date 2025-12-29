"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from merlya.persistence.database import Database
from merlya.persistence.models import Host
from merlya.ssh.pool import SSHResult

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# Use pytest-asyncio's built-in event loop management
# See: https://pytest-asyncio.readthedocs.io/en/latest/concepts.html
pytest_plugins = ("pytest_asyncio",)


# ==============================================================================
# Pytest Hooks for E2E Tests
# ==============================================================================


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests (requires working Merlya installation)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip e2e tests unless --e2e flag is passed."""
    if config.getoption("--e2e"):
        # --e2e passed: run all tests including e2e
        return

    skip_e2e = pytest.mark.skip(reason="E2E tests skipped (use --e2e to run)")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Return the event loop policy to use for tests."""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
async def temp_db_path() -> AsyncGenerator[Path, None]:
    """Create a temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "test.db"


@pytest.fixture
async def database(temp_db_path: Path) -> AsyncGenerator[Database, None]:
    """Create a test database."""
    db = Database(temp_db_path)
    await db.connect()
    yield db
    await db.close()
    Database.reset_instance()


# ==============================================================================
# Common Mock Fixtures for High-Coverage Testing
# ==============================================================================


@pytest.fixture
def mock_ssh_result_success() -> SSHResult:
    """Create a successful SSH result."""
    return SSHResult(stdout="success output", stderr="", exit_code=0)


@pytest.fixture
def mock_ssh_result_failure() -> SSHResult:
    """Create a failed SSH result."""
    return SSHResult(stdout="", stderr="command not found", exit_code=127)


@pytest.fixture
def mock_ssh_pool() -> MagicMock:
    """Create mock SSH pool with execute method."""
    pool = MagicMock()
    pool.execute = AsyncMock(return_value=SSHResult(stdout="", stderr="", exit_code=0))
    pool.has_passphrase_callback = MagicMock(return_value=False)
    pool.set_passphrase_callback = MagicMock()
    pool.disconnect = AsyncMock()
    pool.disconnect_all = AsyncMock()
    return pool


@pytest.fixture
def mock_console_ui() -> MagicMock:
    """Create mock ConsoleUI with all methods."""
    ui = MagicMock()
    ui.print = MagicMock()
    ui.markdown = MagicMock()
    ui.panel = MagicMock()
    ui.success = MagicMock()
    ui.error = MagicMock()
    ui.warning = MagicMock()
    ui.info = MagicMock()
    ui.muted = MagicMock()
    ui.newline = MagicMock()
    ui.table = MagicMock()
    ui.health_status = MagicMock()
    ui.progress = MagicMock()
    ui.prompt = AsyncMock(return_value="test_input")
    ui.prompt_secret = AsyncMock(return_value="secret_value")
    ui.prompt_confirm = AsyncMock(return_value=True)
    ui.confirm = AsyncMock(return_value=True)
    ui.prompt_choice = AsyncMock(return_value="choice1")
    ui.spinner = MagicMock(
        return_value=MagicMock(
            __enter__=MagicMock(),
            __exit__=MagicMock(return_value=False),
        )
    )
    ui.auto_confirm = False
    ui.quiet = False
    return ui


@pytest.fixture
def mock_host() -> Host:
    """Create a mock Host object."""
    return Host(
        id="test-host-id",
        name="test-host",
        hostname="192.168.1.100",
        port=22,
        username="testuser",
        tags=["web", "prod"],
        health_status="healthy",
    )


@pytest.fixture
def mock_hosts_list() -> list[Host]:
    """Create a list of mock hosts."""
    return [
        Host(
            id="host-1",
            name="web-01",
            hostname="10.0.0.1",
            port=22,
            username="admin",
            tags=["web", "prod"],
            health_status="healthy",
        ),
        Host(
            id="host-2",
            name="web-02",
            hostname="10.0.0.2",
            port=22,
            username="admin",
            tags=["web", "prod"],
            health_status="healthy",
        ),
        Host(
            id="host-3",
            name="db-01",
            hostname="10.0.0.10",
            port=22,
            username="dbadmin",
            tags=["db", "prod"],
            health_status="healthy",
        ),
        Host(
            id="host-4",
            name="backup",
            hostname="10.0.0.100",
            port=22,
            username="backup",
            tags=["backup"],
            health_status="unreachable",
        ),
    ]


@pytest.fixture
def mock_shared_context(
    mock_ssh_pool: MagicMock,
    mock_console_ui: MagicMock,
    mock_hosts_list: list[Host],
) -> MagicMock:
    """Create a comprehensive SharedContext mock."""
    ctx = MagicMock()

    # UI
    ctx.ui = mock_console_ui

    # SSH Pool
    ctx.get_ssh_pool = AsyncMock(return_value=mock_ssh_pool)

    # Hosts repository
    ctx.hosts = AsyncMock()
    ctx.hosts.get_all = AsyncMock(return_value=mock_hosts_list)
    ctx.hosts.get_by_name = AsyncMock(
        side_effect=lambda name: next((h for h in mock_hosts_list if h.name == name), None)
    )
    ctx.hosts.create = AsyncMock()
    ctx.hosts.update = AsyncMock()
    ctx.hosts.delete = AsyncMock(return_value=True)

    # Variables repository
    ctx.variables = AsyncMock()
    ctx.variables.get = AsyncMock(return_value=None)
    ctx.variables.get_all = AsyncMock(return_value=[])
    ctx.variables.set = AsyncMock()
    ctx.variables.delete = AsyncMock(return_value=True)

    # Secrets
    ctx.secrets = MagicMock()
    ctx.secrets.get = MagicMock(return_value=None)
    ctx.secrets.has = MagicMock(return_value=False)
    ctx.secrets.set = MagicMock()
    ctx.secrets.list_keys = MagicMock(return_value=[])

    # Config
    ctx.config = MagicMock()
    ctx.config.general = MagicMock()
    ctx.config.general.data_dir = Path(tempfile.mkdtemp())
    ctx.config.ssh = MagicMock()
    ctx.config.ssh.default_timeout = 30
    ctx.config.save = MagicMock()

    # Permissions
    ctx.get_permissions = AsyncMock(return_value=MagicMock())

    # Auth manager
    ctx.get_auth_manager = AsyncMock(return_value=MagicMock())

    return ctx


@pytest.fixture
def realistic_command_outputs() -> dict[str, SSHResult]:
    """Provide realistic command outputs for system tools testing."""
    return {
        # System info
        "uname -a": SSHResult(
            stdout="Linux web-01 5.15.0-91-generic #101-Ubuntu SMP x86_64 GNU/Linux",
            stderr="",
            exit_code=0,
        ),
        # Disk usage
        "df -h": SSHResult(
            stdout="""Filesystem      Size  Used Avail Use% Mounted on
/dev/sda1        50G   25G   23G  53% /
/dev/sdb1       100G   80G   15G  85% /data
tmpfs           3.9G     0  3.9G   0% /dev/shm""",
            stderr="",
            exit_code=0,
        ),
        # Memory
        "free -m": SSHResult(
            stdout="""              total        used        free      shared  buff/cache   available
Mem:           7982        2156        3421         256        2404        5289
Swap:          2047           0        2047""",
            stderr="",
            exit_code=0,
        ),
        # CPU load
        "cat /proc/loadavg": SSHResult(
            stdout="0.52 0.58 0.59 2/1234 12345",
            stderr="",
            exit_code=0,
        ),
        # Processes
        "ps aux": SSHResult(
            stdout="""USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND
root           1  0.0  0.1 169104 13256 ?        Ss   Dec01   0:12 /sbin/init
root         123  0.0  0.0  72304  6780 ?        Ss   Dec01   0:00 /usr/sbin/sshd
www-data    1234  0.5  1.2 456789 98765 ?        S    10:00   1:23 nginx: worker
mysql       2345  2.0  5.0 1234567 409600 ?      Sl   Dec01  45:67 mysqld""",
            stderr="",
            exit_code=0,
        ),
        # Service status
        "systemctl status nginx": SSHResult(
            stdout="""● nginx.service - A high performance web server
     Loaded: loaded (/lib/systemd/system/nginx.service; enabled)
     Active: active (running) since Mon 2024-12-01 00:00:00 UTC; 2 weeks ago
   Main PID: 1234 (nginx)
      Tasks: 5 (limit: 4915)
     Memory: 12.3M""",
            stderr="",
            exit_code=0,
        ),
        # Docker
        "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'": SSHResult(
            stdout="""NAMES       STATUS          PORTS
nginx       Up 2 weeks      0.0.0.0:80->80/tcp
redis       Up 2 weeks      6379/tcp
postgres    Up 2 weeks      5432/tcp""",
            stderr="",
            exit_code=0,
        ),
        # File stat (Linux)
        "stat -c '%F|%s|%U|%G|%a|%Y' /etc/passwd": SSHResult(
            stdout="regular file|2847|root|root|644|1701388800",
            stderr="",
            exit_code=0,
        ),
        # Directory listing
        "ls -la /var/log": SSHResult(
            stdout="""total 12345
drwxr-xr-x  12 root root    4096 Dec 12 00:00 .
drwxr-xr-x  14 root root    4096 Dec 01 00:00 ..
-rw-r-----   1 syslog adm  123456 Dec 12 10:00 auth.log
-rw-r-----   1 syslog adm  234567 Dec 12 10:00 syslog
drwxr-xr-x   2 root root    4096 Dec 01 00:00 nginx""",
            stderr="",
            exit_code=0,
        ),
    }
