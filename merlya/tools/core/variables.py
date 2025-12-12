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
    dangerous_env_vars = {"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "HOME"}
    if is_env and name.upper() in dangerous_env_vars:
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
