"""
Merlya Commands - Core handlers.

Implements /help, /exit, /new, /language commands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from merlya.commands.registry import CommandResult, command, get_registry

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("help", "Show help for commands", "/help [command]", aliases=["h", "?"])
async def cmd_help(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show help for commands."""
    registry = get_registry()

    def _localize(command_obj: object, field: str) -> str:
        key = getattr(
            command_obj, "description_key" if field == "description" else "usage_key", None
        )
        if key:
            translated = ctx.t(key)
            if translated != key:
                return str(translated)
        return str(getattr(command_obj, field, ""))

    if args:
        cmd = registry.get(args[0])
        if cmd:
            # Show command details in panel
            description = _localize(cmd, "description")
            usage_text = _localize(cmd, "usage")
            content = f"**/{cmd.name}** - {description}\n\n"
            if usage_text:
                content += f"{ctx.t('commands.help.usage', command=usage_text)}\n\n"
            if cmd.subcommands:
                content += "**Subcommands:**\n"
                for name, sub in cmd.subcommands.items():
                    content += f"  • `{name}` - {_localize(sub, 'description')}\n"
            ctx.ui.panel(content, title=f"❓ Help: /{cmd.name}", style="info")
            return CommandResult(success=True, message="")
        return CommandResult(
            success=False,
            message=f"❌ {ctx.t('commands.help.unknown', name=args[0])}",
        )

    # Show all commands in a table
    ctx.ui.table(
        headers=[
            ctx.t("commands.help.command_header"),
            ctx.t("commands.help.description_header"),
        ],
        rows=[[f"/{cmd.name}", _localize(cmd, "description")] for cmd in registry.all()],
        title=f"❓ {ctx.t('commands.help.title')}",
    )
    ctx.ui.muted(f"\n{ctx.t('commands.help.usage_hint')}")

    return CommandResult(success=True, message="")


@command("exit", "Exit Merlya", "/exit", aliases=["quit", "q"])
async def cmd_exit(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Exit Merlya."""
    return CommandResult(
        success=True,
        message=_ctx.t("commands.exit.goodbye"),
        data={"exit": True},
    )


@command("new", "Start a new conversation", "/new")
async def cmd_new(_ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Start a new conversation."""
    return CommandResult(
        success=True,
        message=_ctx.t("commands.new.started"),
        data={"new_conversation": True},
    )


@command("language", "Change interface language", "/language <fr|en>", aliases=["lang"])
async def cmd_language(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Change interface language."""
    if not args:
        current = ctx.i18n.language
        return CommandResult(
            success=True,
            message=ctx.t("commands.language.current", lang=current)
            + "\n"
            + ctx.t("commands.help.usage", command="/language <fr|en>"),
        )

    lang = args[0].lower()
    if lang not in ["fr", "en"]:
        return CommandResult(
            success=False,
            message=ctx.t("commands.language.available", langs="fr, en"),
        )

    ctx.i18n.set_language(lang)
    ctx.config.general.language = lang
    ctx.config.save()
    return CommandResult(
        success=True,
        message=ctx.t("commands.language.changed", lang=lang),
    )
