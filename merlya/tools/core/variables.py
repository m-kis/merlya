"""
Merlya Tools - Variable management.

Get and set user-defined variables.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from merlya.tools.core.models import ToolResult

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Environment variables that should never be set by the agent
# These can be used for privilege escalation, code injection, or security bypass
DANGEROUS_ENV_VARS: frozenset[str] = frozenset(
    {
        # Path manipulation - can execute arbitrary code
        "PATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",  # macOS equivalent of LD_PRELOAD
        "PYTHONPATH",
        "NODE_PATH",
        "PERL5LIB",
        "RUBYLIB",
        # Shell/execution control
        "HOME",
        "SHELL",
        "IFS",  # Can break shell parsing
        "BASH_ENV",
        "ENV",
        "PS4",  # DEBUG trap can exfiltrate data
        # Sudo/privilege escalation
        "SUDO_ASKPASS",
        "SSH_ASKPASS",
        # History manipulation (anti-forensics)
        "HISTFILE",
        "HISTIGNORE",
        "HISTCONTROL",
        # Language-specific injection vectors
        "NODE_OPTIONS",  # Node.js code injection
        "PERL5OPT",  # Perl code injection
        "PYTHONSTARTUP",  # Python code injection
        "RUBYOPT",  # Ruby code injection
    }
)


async def get_variable(
    ctx: SharedContext,
    name: str,
) -> ToolResult:
    """
    Get a variable value.

    Args:
        ctx: Shared context.
        name: Variable name.

    Returns:
        ToolResult with variable value.
    """
    # Validate variable name
    if not name or not name.strip():
        return ToolResult(
            success=False,
            data=None,
            error="Variable name cannot be empty",
        )

    try:
        variable = await ctx.variables.get(name)
        if variable:
            return ToolResult(success=True, data=variable.value)
        return ToolResult(
            success=False,
            data=None,
            error=f"Variable '{name}' not found",
        )
    except Exception as e:
        logger.error(f"❌ Failed to get variable: {e}")
        return ToolResult(success=False, data=None, error=str(e))


async def set_variable(
    ctx: SharedContext,
    name: str,
    value: str,
    is_env: bool = False,
) -> ToolResult:
    """
    Set a variable.

    Args:
        ctx: Shared context.
        name: Variable name.
        value: Variable value.
        is_env: Whether to export as environment variable.

    Returns:
        ToolResult confirming set.
    """
    # Validate variable name
    if not name or not name.strip():
        return ToolResult(
            success=False,
            data=None,
            error="Variable name cannot be empty",
        )

    # Security: Prevent setting dangerous env vars
    if is_env and name.upper() in DANGEROUS_ENV_VARS:
        logger.warning(f"🔒 Blocked attempt to set dangerous env var: {name}")
        return ToolResult(
            success=False,
            data=None,
            error=f"⚠️ SECURITY: Cannot set dangerous environment variable '{name}'",
        )

    try:
        await ctx.variables.set(name, value, is_env=is_env)
        return ToolResult(success=True, data={"name": name, "is_env": is_env})
    except Exception as e:
        logger.error(f"❌ Failed to set variable: {e}")
        return ToolResult(success=False, data=None, error=str(e))
