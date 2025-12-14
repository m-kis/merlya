"""Tests for SSH jump host (via) functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merlya.ssh.pool import SSHPool


class TestSSHViaParameter:
    """Tests for the 'via' parameter in ssh_execute tool."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_via_resolves_jump_host_from_inventory(self) -> None:
        """Test that 'via' parameter resolves jump host from inventory."""
        from merlya.persistence.models import Host
        from merlya.tools.core import ssh_execute

        # Mock context
        mock_ctx = MagicMock()
        mock_ctx.hosts = AsyncMock()

        # Target host in inventory
        target_host = Host(
            id="target-1",
            name="db-server",
            hostname="10.0.1.50",
            port=22,
            username="admin",
        )

        # Jump host in inventory
        jump_host = Host(
            id="jump-1",
            name="bastion",
            hostname="192.168.1.100",
            port=22,
            username="jump-user",
            private_key="~/.ssh/bastion_key",
        )

        async def get_by_name(name: str) -> Host | None:
            if name == "db-server":
                return target_host
            if name == "bastion":
                return jump_host
            return None

        mock_ctx.hosts.get_by_name = get_by_name

        # Mock SSH pool
        mock_result = MagicMock()
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value=mock_result)
        mock_pool.has_mfa_callback = MagicMock(return_value=True)
        mock_pool.has_passphrase_callback = MagicMock(return_value=True)
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_pool)

        # Execute with via parameter
        result = await ssh_execute(
            ctx=mock_ctx,
            host="db-server",
            command="df -h",
            via="bastion",
        )

        assert result.success
        assert result.data["via"] == "bastion"

        # Verify SSH pool was called with jump host options
        mock_pool.execute.assert_called_once()
        call_kwargs = mock_pool.execute.call_args.kwargs
        opts = call_kwargs.get("options")
        assert opts is not None
        assert opts.jump_host == "192.168.1.100"
        assert opts.jump_username == "jump-user"
        assert opts.jump_private_key == "~/.ssh/bastion_key"

    @pytest.mark.asyncio
    async def test_via_uses_direct_hostname_when_not_in_inventory(self) -> None:
        """Test that 'via' uses hostname directly when not in inventory."""
        from merlya.persistence.models import Host
        from merlya.tools.core import ssh_execute

        mock_ctx = MagicMock()
        mock_ctx.hosts = AsyncMock()

        # Target host in inventory
        target_host = Host(
            id="target-1",
            name="db-server",
            hostname="10.0.1.50",
        )

        async def get_by_name(name: str) -> Host | None:
            if name == "db-server":
                return target_host
            return None  # Jump host not in inventory

        mock_ctx.hosts.get_by_name = get_by_name

        # Mock SSH pool
        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value=mock_result)
        mock_pool.has_mfa_callback = MagicMock(return_value=True)
        mock_pool.has_passphrase_callback = MagicMock(return_value=True)
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_pool)

        # Execute with via as direct IP (not in inventory)
        result = await ssh_execute(
            ctx=mock_ctx,
            host="db-server",
            command="uptime",
            via="192.168.1.100",
        )

        assert result.success
        assert result.data["via"] == "192.168.1.100"

        # Verify jump host is set to the direct hostname
        call_kwargs = mock_pool.execute.call_args.kwargs
        opts = call_kwargs.get("options")
        assert opts is not None
        assert opts.jump_host == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_via_takes_priority_over_inventory_jump_host(self) -> None:
        """Test that 'via' parameter overrides inventory jump_host."""
        from merlya.persistence.models import Host
        from merlya.tools.core import ssh_execute

        mock_ctx = MagicMock()
        mock_ctx.hosts = AsyncMock()

        # Target host with configured jump_host in inventory
        target_host = Host(
            id="target-1",
            name="db-server",
            hostname="10.0.1.50",
            jump_host="old-bastion",  # This should be overridden
        )

        # New jump host specified via 'via' parameter
        new_jump_host = Host(
            id="jump-1",
            name="new-bastion",
            hostname="192.168.2.100",
        )

        async def get_by_name(name: str) -> Host | None:
            if name == "db-server":
                return target_host
            if name == "new-bastion":
                return new_jump_host
            return None

        mock_ctx.hosts.get_by_name = get_by_name

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value=mock_result)
        mock_pool.has_mfa_callback = MagicMock(return_value=True)
        mock_pool.has_passphrase_callback = MagicMock(return_value=True)
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_pool)

        # Execute with via parameter (should override inventory jump_host)
        result = await ssh_execute(
            ctx=mock_ctx,
            host="db-server",
            command="ls",
            via="new-bastion",  # Override the old-bastion
        )

        assert result.success
        assert result.data["via"] == "new-bastion"

        # Verify the new jump host is used, not the old one
        call_kwargs = mock_pool.execute.call_args.kwargs
        opts = call_kwargs.get("options")
        assert opts is not None
        assert opts.jump_host == "192.168.2.100"

    @pytest.mark.asyncio
    async def test_no_via_uses_inventory_jump_host(self) -> None:
        """Test that without 'via', inventory jump_host is used."""
        from merlya.persistence.models import Host
        from merlya.tools.core import ssh_execute

        mock_ctx = MagicMock()
        mock_ctx.hosts = AsyncMock()

        # Jump host in inventory
        inventory_jump = Host(
            id="jump-1",
            name="inventory-bastion",
            hostname="192.168.1.1",
            username="bastion-user",
        )

        # Target host with configured jump_host
        target_host = Host(
            id="target-1",
            name="db-server",
            hostname="10.0.1.50",
            jump_host="inventory-bastion",  # Configured in inventory
        )

        async def get_by_name(name: str) -> Host | None:
            if name == "db-server":
                return target_host
            if name == "inventory-bastion":
                return inventory_jump
            return None

        mock_ctx.hosts.get_by_name = get_by_name

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value=mock_result)
        mock_pool.has_mfa_callback = MagicMock(return_value=True)
        mock_pool.has_passphrase_callback = MagicMock(return_value=True)
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_pool)

        # Execute without via parameter
        result = await ssh_execute(
            ctx=mock_ctx,
            host="db-server",
            command="hostname",
            # No via parameter
        )

        assert result.success
        assert result.data["via"] == "inventory-bastion"

        # Verify inventory jump host is used
        call_kwargs = mock_pool.execute.call_args.kwargs
        opts = call_kwargs.get("options")
        assert opts is not None
        assert opts.jump_host == "192.168.1.1"
        assert opts.jump_username == "bastion-user"

    @pytest.mark.asyncio
    async def test_no_jump_host_without_via_or_inventory(self) -> None:
        """Test that no jump host is used when neither via nor inventory config."""
        from merlya.persistence.models import Host
        from merlya.tools.core import ssh_execute

        mock_ctx = MagicMock()
        mock_ctx.hosts = AsyncMock()

        # Target host without jump_host configured
        target_host = Host(
            id="target-1",
            name="web-server",
            hostname="10.0.1.100",
        )

        async def get_by_name(name: str) -> Host | None:
            if name == "web-server":
                return target_host
            return None

        mock_ctx.hosts.get_by_name = get_by_name

        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.stderr = ""
        mock_result.exit_code = 0

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value=mock_result)
        mock_pool.has_mfa_callback = MagicMock(return_value=True)
        mock_pool.has_passphrase_callback = MagicMock(return_value=True)
        mock_ctx.get_ssh_pool = AsyncMock(return_value=mock_pool)

        # Execute without via and without inventory jump_host
        result = await ssh_execute(
            ctx=mock_ctx,
            host="web-server",
            command="whoami",
        )

        assert result.success
        assert result.data["via"] is None

        # Verify no jump host is configured
        call_kwargs = mock_pool.execute.call_args.kwargs
        opts = call_kwargs.get("options")
        assert opts is not None
        assert opts.jump_host is None


class TestSSHPoolJumpTunnel:
    """Tests for SSH pool jump tunnel setup."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        SSHPool.reset_instance()

    @pytest.mark.asyncio
    async def test_setup_jump_tunnel_returns_none_without_config(self) -> None:
        """Test that _setup_jump_tunnel returns None when no jump host."""
        from merlya.ssh.pool import SSHConnectionOptions

        pool = await SSHPool.get_instance()
        opts = SSHConnectionOptions()

        result = await pool._setup_jump_tunnel(opts)

        assert result is None

    @pytest.mark.asyncio
    async def test_setup_jump_tunnel_connects_to_jump_host(self) -> None:
        """Test that _setup_jump_tunnel creates connection to jump host."""
        from merlya.ssh.pool import SSHConnectionOptions

        pool = await SSHPool.get_instance()
        opts = SSHConnectionOptions(
            jump_host="jump.example.com",
            jump_port=22,
            jump_username="jump-user",
        )

        mock_conn = MagicMock()

        with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_conn
            result = await pool._setup_jump_tunnel(opts)

        assert result is mock_conn
        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args.kwargs
        assert call_kwargs["host"] == "jump.example.com"
        assert call_kwargs["port"] == 22
        assert call_kwargs["username"] == "jump-user"
