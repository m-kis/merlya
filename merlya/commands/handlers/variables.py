"""
Merlya Commands - Variable and secret handlers.

Implements /variable and /secret commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


# =============================================================================
# Variable Commands
# =============================================================================


@command("variable", "Manage variables", "/variable <subcommand>", aliases=["var"])
async def cmd_variable(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage variables."""
    if not args:
        return await cmd_variable_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help variable` for available commands.",
        show_help=True,
    )


@subcommand("variable", "list", "List all variables", "/variable list")
async def cmd_variable_list(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """List all variables."""
    variables = await ctx.variables.get_all()

    if not variables:
        return CommandResult(
            success=True,
            message=ctx.t("commands.variable.empty"),
        )

    # Use Rich table for better display
    ctx.ui.table(
        headers=["Name", "Value", "Type"],
        rows=[
            [f"@{v.name}", v.value[:50] + "..." if len(v.value) > 50 else v.value, "env" if v.is_env else "var"]
            for v in variables
        ],
        title=f"📝 {ctx.t('commands.variable.list_title')} ({len(variables)})",
    )

    return CommandResult(success=True, message="")


@subcommand("variable", "set", "Set a variable", "/variable set <name> <value> [--env]")
async def cmd_variable_set(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set a variable."""
    if len(args) < 2:
        return CommandResult(
            success=False,
            message="Usage: `/variable set <name> <value> [--env]`",
        )

    is_env = "--env" in args
    args_filtered = [a for a in args if a != "--env"]

    if len(args_filtered) < 2:
        return CommandResult(
            success=False,
            message="Usage: `/variable set <name> <value> [--env]`",
        )

    name = args_filtered[0]
    value = " ".join(args_filtered[1:])

    await ctx.variables.set(name, value, is_env=is_env)

    return CommandResult(success=True, message=ctx.t("commands.variable.set", name=name))


@subcommand("variable", "get", "Get a variable value", "/variable get <name>")
async def cmd_variable_get(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Get a variable value."""
    if not args:
        return CommandResult(success=False, message="Usage: `/variable get <name>`")

    var = await ctx.variables.get(args[0])
    if not var:
        return CommandResult(
            success=False,
            message=ctx.t("commands.variable.not_found", name=args[0]),
        )

    return CommandResult(
        success=True,
        message=f"`@{var.name}` = `{var.value}`",
        data=var.value,
    )


@subcommand("variable", "delete", "Delete a variable", "/variable delete <name>")
async def cmd_variable_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a variable."""
    if not args:
        return CommandResult(success=False, message="Usage: `/variable delete <name>`")

    deleted = await ctx.variables.delete(args[0])
    if deleted:
        return CommandResult(
            success=True,
            message=ctx.t("commands.variable.deleted", name=args[0]),
        )
    return CommandResult(
        success=False,
        message=ctx.t("commands.variable.not_found", name=args[0]),
    )


# =============================================================================
# Secret Commands
# =============================================================================


@command("secret", "Manage secrets (securely stored)", "/secret <subcommand>")
async def cmd_secret(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage secrets."""
    if not args:
        return await cmd_secret_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help secret` for available commands.",
        show_help=True,
    )


@subcommand("secret", "list", "List all secrets (names only)", "/secret list")
async def cmd_secret_list(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """List all secrets (names only)."""
    secrets = ctx.secrets.list_keys()

    if not secrets:
        return CommandResult(
            success=True,
            message=ctx.t("commands.secret.empty"),
        )

    lines = [f"**{ctx.t('commands.secret.list_title')}** ({len(secrets)})\n"]
    for name in secrets:
        lines.append(f"  `@{name}`")

    return CommandResult(success=True, message="\n".join(lines))


@subcommand("secret", "set", "Set a secret (prompted securely)", "/secret set <name>")
async def cmd_secret_set(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Set a secret."""
    if not args:
        return CommandResult(success=False, message="Usage: `/secret set <name>`")

    name = args[0]
    value = await ctx.ui.prompt_secret(ctx.t("prompts.enter_value", field=name))

    if not value:
        return CommandResult(
            success=False,
            message=ctx.t("errors.validation.required", field=name),
        )

    ctx.secrets.set(name, value)

    return CommandResult(success=True, message=ctx.t("commands.secret.set", name=name))


@subcommand("secret", "delete", "Delete a secret", "/secret delete <name>")
async def cmd_secret_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a secret."""
    if not args:
        return CommandResult(success=False, message="Usage: `/secret delete <name>`")

    ctx.secrets.delete(args[0])
    return CommandResult(
        success=True,
        message=ctx.t("commands.secret.deleted", name=args[0]),
    )
