"""
Merlya Agent - Security tool registration.

Registers security-related tools (ports, SSH keys, sudo, users, config).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, ModelRetry, RunContext

from merlya.agent.tools_common import check_recoverable_error
from merlya.agent.types import (
    OpenPortsResponse,
    SecurityConfigResponse,
    SSHKeyAuditResponse,
    SudoConfigResponse,
    UsersAuditResponse,
)

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any


def register_security_tools(agent: Agent[Any, Any]) -> None:
    """Register security tools with the agent."""

    @agent.tool
    async def check_open_ports(
        ctx: RunContext[AgentDependencies],
        host: str,
        include_established: bool = False,
    ) -> OpenPortsResponse:
        """
        Check open ports on a host.

        Args:
            host: Host name from inventory.
            include_established: Include established connections (default: False).

        Returns:
            List of open ports with process info.
        """
        from merlya.tools.security import check_open_ports as _check_open_ports

        result = await _check_open_ports(
            ctx.deps.context, host, include_established=include_established
        )
        if result.success:
            from typing import cast

            return OpenPortsResponse(
                ports=cast("list[Any]", result.data) if result.data else [],
                severity=result.severity,
            )
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return OpenPortsResponse(error=result.error)

    @agent.tool
    async def audit_ssh_keys(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> SSHKeyAuditResponse:
        """
        Audit SSH keys on a host.

        Args:
            host: Host name from inventory.

        Returns:
            SSH key audit results with security issues.
        """
        from merlya.tools.security import audit_ssh_keys as _audit_ssh_keys

        result = await _audit_ssh_keys(ctx.deps.context, host)
        if result.success:
            from typing import cast

            return SSHKeyAuditResponse(
                audit=cast("list[Any]", result.data) if result.data else [],
                severity=result.severity,
            )
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return SSHKeyAuditResponse(error=result.error)

    @agent.tool
    async def check_security_config(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> SecurityConfigResponse:
        """
        Check security configuration on a host.

        Args:
            host: Host name from inventory.

        Returns:
            Security configuration audit with issues.
        """
        from merlya.tools.security import check_security_config as _check_security_config

        result = await _check_security_config(ctx.deps.context, host)
        if result.success:
            from typing import cast

            return SecurityConfigResponse(
                config=cast("dict[str, Any]", result.data) if result.data else {},
                severity=result.severity,
            )
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return SecurityConfigResponse(error=result.error)

    @agent.tool
    async def check_users(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> UsersAuditResponse:
        """
        Audit user accounts on a host.

        Args:
            host: Host name from inventory.

        Returns:
            User audit with security issues.
        """
        from merlya.tools.security import check_users as _check_users

        result = await _check_users(ctx.deps.context, host)
        if result.success:
            from typing import cast

            return UsersAuditResponse(
                users=cast("list[Any]", result.data) if result.data else [],
                severity=result.severity,
            )
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return UsersAuditResponse(error=result.error)

    @agent.tool
    async def check_sudo_config(
        ctx: RunContext[AgentDependencies],
        host: str,
    ) -> SudoConfigResponse:
        """
        Audit sudo configuration on a host.

        Args:
            host: Host name from inventory.

        Returns:
            Sudo audit with security issues.
        """
        from merlya.tools.security import check_sudo_config as _check_sudo_config

        result = await _check_sudo_config(ctx.deps.context, host)
        if result.success:
            from typing import cast

            return SudoConfigResponse(
                config=cast("dict[str, Any]", result.data) if result.data else {},
                severity=result.severity,
            )
        if check_recoverable_error(result.error):
            raise ModelRetry(f"Host '{host}' not found. Check the name or use list_hosts().")
        return SudoConfigResponse(error=result.error)
