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
            [
                f"@{v.name}",
                v.value[:50] + "..." if len(v.value) > 50 else v.value,
                "env" if v.is_env else "var",
            ]
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


@subcommand(
    "variable",
    "import",
    "Import variables from file",
    "/variable import <file> [--merge|--replace] [--dry-run]",
)
async def cmd_variable_import(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Import variables from a file (YAML, JSON, or .env format)."""
    from pathlib import Path

    from merlya.commands.handlers.variables_io import (
        check_file_size,
        detect_import_format,
        import_variables,
        validate_file_path,
    )

    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/variable import <file> [--merge|--replace] [--dry-run]`",
        )

    file_path = Path(args[0]).expanduser()
    merge = "--replace" not in args
    dry_run = "--dry-run" in args

    # Validate file path
    is_valid, error = validate_file_path(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error}")

    # Check file exists
    if not file_path.exists():
        return CommandResult(success=False, message=f"❌ File not found: {file_path}")

    # Check file size
    is_valid, error = check_file_size(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error}")

    # Detect format
    file_format = detect_import_format(file_path)

    try:
        var_count, _secret_count, host_count, secrets, errors = await import_variables(
            ctx, file_path, file_format, merge, dry_run
        )
    except Exception as e:
        return CommandResult(success=False, message=f"❌ Import failed: {e}")

    # Build result message
    lines = []
    if dry_run:
        lines.append("**Dry run** - no changes made\n")

    if var_count > 0:
        lines.append(f"✅ {var_count} variable(s) {'would be ' if dry_run else ''}imported")
    if host_count > 0:
        lines.append(f"✅ {host_count} host(s) {'would be ' if dry_run else ''}imported")

    # Prompt for secrets
    if secrets and not dry_run:
        lines.append(f"\n🔐 **{len(secrets)} secret(s) to set:**")
        for secret_name in secrets:
            lines.append(f"  - `{secret_name}`")
            value = await ctx.ui.prompt_secret(f"Enter {secret_name}")
            if value:
                ctx.secrets.set(secret_name, value)
                lines.append("    ✅ Set")
            else:
                lines.append("    ⏭️ Skipped")
    elif secrets and dry_run:
        lines.append(f"\n🔐 {len(secrets)} secret(s) would be prompted")

    if errors:
        lines.append(f"\n⚠️ **{len(errors)} warning(s):**")
        for error in errors[:5]:  # Limit to 5 errors
            lines.append(f"  - {error}")
        if len(errors) > 5:
            lines.append(f"  - ... and {len(errors) - 5} more")

    if not lines:
        lines.append("No variables found in file")

    return CommandResult(success=var_count > 0 or host_count > 0, message="\n".join(lines))


@subcommand(
    "variable",
    "export",
    "Export variables to file",
    "/variable export <file> [--include-secrets]",
)
async def cmd_variable_export(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Export variables to a file (YAML, JSON, or .env format)."""
    from pathlib import Path

    from merlya.commands.handlers.variables_io import (
        detect_export_format,
        export_variables,
        validate_file_path,
    )

    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/variable export <file> [--include-secrets]`",
        )

    file_path = Path(args[0]).expanduser()
    include_secrets = "--include-secrets" in args

    # Validate file path
    is_valid, error = validate_file_path(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error}")

    # Detect format
    file_format = detect_export_format(file_path)

    try:
        content = await export_variables(ctx, file_format, include_secrets)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    except Exception as e:
        return CommandResult(success=False, message=f"❌ Export failed: {e}")

    return CommandResult(
        success=True,
        message=f"✅ Variables exported to `{file_path}` ({file_format} format)",
    )


@subcommand(
    "variable",
    "template",
    "Generate a template file",
    "/variable template <file>",
)
async def cmd_variable_template(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Generate a template file for variable import."""
    from pathlib import Path

    from merlya.commands.handlers.variables_io import (
        detect_export_format,
        generate_template,
        validate_file_path,
    )

    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/variable template <file>`",
        )

    file_path = Path(args[0]).expanduser()

    # Validate file path
    is_valid, error = validate_file_path(file_path)
    if not is_valid:
        return CommandResult(success=False, message=f"❌ {error}")

    # Check if file exists
    if file_path.exists():
        return CommandResult(
            success=False,
            message=f"❌ File already exists: {file_path}",
        )

    # Detect format
    file_format = detect_export_format(file_path)

    try:
        content = generate_template(file_format)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    except Exception as e:
        return CommandResult(success=False, message=f"❌ Template generation failed: {e}")

    return CommandResult(
        success=True,
        message=f"✅ Template created at `{file_path}` ({file_format} format)\n\n"
        f"Edit the file and import with: `/variable import {file_path}`",
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


@subcommand(
    "secret",
    "clear-elevation",
    "Clear stored elevation passwords",
    "/secret clear-elevation [<host>|--all]",
)
async def cmd_secret_clear_elevation(ctx: SharedContext, args: list[str]) -> CommandResult:
    """
    Clear stored elevation (sudo/su) passwords.

    These passwords are cached when using sudo_with_password or su methods.
    Use this to force re-prompting for password.

    Examples:
        /secret clear-elevation           - List elevation passwords
        /secret clear-elevation myhost    - Clear password for myhost
        /secret clear-elevation --all     - Clear all elevation passwords
    """
    # List all elevation secrets
    all_secrets = ctx.secrets.list_keys()
    elevation_secrets = [s for s in all_secrets if s.startswith("elevation:")]

    if not args:
        # Just list them
        if not elevation_secrets:
            return CommandResult(
                success=True,
                message="No stored elevation passwords.",
            )

        lines = ["**Stored elevation passwords:**"]
        for secret in elevation_secrets:
            # Format: elevation:hostname:password -> hostname
            parts = secret.split(":")
            host = parts[1] if len(parts) >= 2 else secret
            lines.append(f"  - `{host}`")
        lines.append("\nUse `/secret clear-elevation <host>` or `--all` to clear.")
        return CommandResult(success=True, message="\n".join(lines))

    if "--all" in args:
        # Clear all elevation passwords
        count = 0
        for secret in elevation_secrets:
            ctx.secrets.delete(secret)
            count += 1

        if count == 0:
            return CommandResult(success=True, message="No elevation passwords to clear.")
        return CommandResult(
            success=True,
            message=f"✅ Cleared {count} elevation password(s).",
        )

    # Clear specific host
    host = args[0]
    secret_key = f"elevation:{host}:password"

    if secret_key not in elevation_secrets:
        return CommandResult(
            success=False,
            message=f"No stored elevation password for '{host}'.",
        )

    ctx.secrets.delete(secret_key)

    return CommandResult(
        success=True,
        message=f"✅ Cleared elevation password for '{host}'.",
    )
