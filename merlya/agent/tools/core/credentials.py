"""
Credentials management tool for Merlya agent.

Provides credential collection from users.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, ModelRetry, RunContext

if TYPE_CHECKING:
    from merlya.agent.main import AgentDependencies
else:
    AgentDependencies = Any


async def request_credentials(
    ctx: RunContext[AgentDependencies],
    service: str,
    host: str | None = None,
    fields: list[str] | None = None,
    format_hint: str | None = None,
) -> dict[str, Any]:
    """
    Request credentials from the user interactively.

    Use this tool when authentication fails and you need username/password
    or API keys from the user.

    Args:
        service: Service name requiring credentials (e.g., "mongodb", "api").
        host: Target host for these credentials (optional).
        fields: List of field names to collect (default: ["username", "password"]).
        format_hint: Hint about expected format (e.g., "JSON key file").

    Returns:
        Collected credentials with service, host, and values.
    """
    from merlya.tools.interaction import request_credentials as _request_credentials

    result = await _request_credentials(
        ctx.deps.context,
        service=service,
        host=host,
        fields=fields,
        format_hint=format_hint,
    )
    if result.success:
        bundle = result.data
        # Build explicit next_step hint for elevation services
        next_step = None
        elevation_method = bundle.values.pop("_elevation_method", "sudo")
        if bundle.service.lower() in {"sudo", "root", "su", "doas"}:
            password_ref = bundle.values.get("password", "")
            if password_ref and bundle.host:
                # Give explicit instructions based on which method works
                if elevation_method == "su":
                    next_step = (
                        f"NOW use ssh_execute with stdin parameter (USE su -c, NOT sudo): "
                        f"ssh_execute(host='{bundle.host}', "
                        f"command=\"su -c '<your_command>'\", "
                        f"stdin='{password_ref}')"
                    )
                else:
                    next_step = (
                        f"NOW use ssh_execute with stdin parameter: "
                        f"ssh_execute(host='{bundle.host}', "
                        f"command='sudo -S <your_command>', "
                        f"stdin='{password_ref}')"
                    )
        return {
            "service": bundle.service,
            "host": bundle.host,
            "values": bundle.values,
            "stored": bundle.stored,
            "elevation_method": elevation_method,  # "sudo" or "su"
            "next_step": next_step,
        }
    raise ModelRetry(f"Failed to collect credentials: {getattr(result, 'error', result.message)}")


def register(agent: Agent[Any, Any]) -> None:
    """Register credentials tool on agent."""
    agent.tool(request_credentials)
