"""
Merlya Commands - Conversation management handlers.

Implements /conv command with subcommands: list, show, load, delete, rename, search, export.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from merlya.commands.registry import CommandResult, command, subcommand

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


@command("conv", "Manage conversation history", "/conv <subcommand>", aliases=["conversation"])
async def cmd_conv(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage conversation history."""
    if not args:
        return await cmd_conv_list(ctx, [])

    return CommandResult(
        success=False,
        message="Unknown subcommand. Use `/help conv` for available commands.",
        show_help=True,
    )


@subcommand("conv", "list", "List recent conversations", "/conv list [--limit=N]")
async def cmd_conv_list(ctx: SharedContext, args: list[str]) -> CommandResult:
    """List recent conversations."""
    limit = 10
    for arg in args:
        if arg.startswith("--limit="):
            with contextlib.suppress(ValueError):
                limit = int(arg[8:])

    conversations = await ctx.conversations.get_recent(limit=limit)

    if not conversations:
        return CommandResult(
            success=True,
            message="No conversations yet. Start chatting to create one!",
        )

    rows: list[list[str]] = []
    for conv in conversations:
        date_str = conv.updated_at.strftime("%Y-%m-%d %H:%M") if conv.updated_at else "?"
        title = conv.title or "(untitled)"
        msg_count = len(conv.messages) if conv.messages else 0
        rows.append([f"`{conv.id[:8]}`", f"[bold]{title}[/bold]", str(msg_count), date_str])

    ctx.ui.table(
        headers=["ID", "Title", "Messages", "Updated"],
        rows=rows,
        title=f"🗄️ Recent Conversations ({len(conversations)})",
    )
    ctx.ui.muted("\nUse `/conv load <id>` to resume.")
    titles_preview = ", ".join([(conv.title or conv.id[:8]) for conv in conversations])
    return CommandResult(
        success=True,
        message=f"Recent conversations: {titles_preview}",
    )


@subcommand("conv", "show", "Show conversation details", "/conv show <id>")
async def cmd_conv_show(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show conversation details."""
    if not args:
        return CommandResult(success=False, message="Usage: `/conv show <id>`")

    conv = await _find_conversation(ctx, args[0])
    if isinstance(conv, CommandResult):
        return conv

    lines = [
        f"**Conversation: {conv.title or '(untitled)'}**\n",
        f"  ID: `{conv.id}`",
        f"  Created: `{conv.created_at}`",
        f"  Messages: `{len(conv.messages) if conv.messages else 0}`",
    ]

    if conv.summary:
        lines.append(f"\n**Summary:**\n{conv.summary}")

    if conv.messages:
        lines.append("\n**Last messages:**")
        for msg in conv.messages[-5:]:
            role = msg.get("role", "?")
            content = msg.get("content", "")[:100]
            lines.append(f"  [{role}] {content}...")

    return CommandResult(success=True, message="\n".join(lines), data=conv)


@subcommand("conv", "load", "Load/resume a conversation", "/conv load <id>")
async def cmd_conv_load(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Load and resume a conversation."""
    if not args:
        return CommandResult(success=False, message="Usage: `/conv load <id>`")

    conv = await _find_conversation(ctx, args[0])
    if isinstance(conv, CommandResult):
        return conv

    return CommandResult(
        success=True,
        message=f"✅ Loaded conversation: {conv.title or conv.id[:8]}",
        data={"load_conversation": conv},
    )


@subcommand("conv", "delete", "Delete a conversation", "/conv delete <id>")
async def cmd_conv_delete(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Delete a conversation."""
    if not args:
        return CommandResult(success=False, message="Usage: `/conv delete <id>`")

    conv = await ctx.conversations.get_by_id(args[0])
    if not conv:
        return CommandResult(success=False, message=f"Conversation `{args[0]}` not found.")

    confirmed = await ctx.ui.prompt_confirm(f"Delete conversation '{conv.title or args[0][:8]}'?")
    if not confirmed:
        return CommandResult(success=True, message="Cancelled.")

    await ctx.conversations.delete(args[0])
    return CommandResult(success=True, message="✅ Conversation deleted.")


@subcommand("conv", "rename", "Rename a conversation", "/conv rename <id> <title>")
async def cmd_conv_rename(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Rename a conversation."""
    if len(args) < 2:
        return CommandResult(success=False, message="Usage: `/conv rename <id> <title>`")

    conv_id = args[0]
    new_title = " ".join(args[1:])

    conv = await ctx.conversations.get_by_id(conv_id)
    if not conv:
        return CommandResult(success=False, message=f"Conversation `{conv_id}` not found.")

    conv.title = new_title
    await ctx.conversations.update(conv)

    return CommandResult(success=True, message=f"✅ Conversation renamed to: {new_title}")


@subcommand("conv", "search", "Search conversations", "/conv search <query>")
async def cmd_conv_search(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Search in conversation history."""
    if not args:
        return CommandResult(success=False, message="Usage: `/conv search <query>`")

    query = " ".join(args)
    results = await ctx.conversations.search(query)

    if not results:
        return CommandResult(success=True, message=f"No conversations matching `{query}`")

    lines = [f"**Search Results for `{query}`** ({len(results)})\n"]
    for conv in results[:10]:
        title = conv.title or "(untitled)"
        lines.append(f"  `{conv.id[:8]}` - {title}")

    return CommandResult(success=True, message="\n".join(lines))


@subcommand("conv", "export", "Export conversation", "/conv export <id> <file>")
async def cmd_conv_export(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Export a conversation to file."""
    if len(args) < 2:
        return CommandResult(
            success=False,
            message="Usage: `/conv export <id> <file>`\nSupports: .json, .md",
        )

    conv_id = args[0]
    file_path = Path(args[1]).expanduser()

    conv = await ctx.conversations.get_by_id(conv_id)
    if not conv:
        return CommandResult(success=False, message=f"Conversation `{conv_id}` not found.")

    content = _export_conversation(conv, file_path.suffix)

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)

    return CommandResult(success=True, message=f"✅ Exported to `{file_path}`")


async def _find_conversation(ctx: SharedContext, conv_id: str) -> Any:
    """Find conversation by ID or partial ID."""
    conv = await ctx.conversations.get_by_id(conv_id)

    if not conv:
        all_convs = await ctx.conversations.get_recent(limit=100)
        matches = [c for c in all_convs if c.id.startswith(conv_id)]
        if len(matches) == 1:
            return matches[0]
        elif len(matches) > 1:
            return CommandResult(
                success=False,
                message=f"Multiple matches for `{conv_id}`. Be more specific.",
            )
        else:
            return CommandResult(success=False, message=f"Conversation `{conv_id}` not found.")

    return conv


def _export_conversation(conv: Any, file_suffix: str) -> str:
    """Export conversation to string format."""
    if file_suffix == ".json":
        return json.dumps(
            {
                "id": conv.id,
                "title": conv.title,
                "created_at": str(conv.created_at),
                "messages": conv.messages,
            },
            indent=2,
        )
    else:
        lines = [f"# {conv.title or 'Conversation'}", "", f"*{conv.created_at}*", ""]
        for msg in conv.messages or []:
            role = msg.get("role", "?").upper()
            content = msg.get("content", "")
            lines.append(f"## {role}")
            lines.append(content)
            lines.append("")
        return "\n".join(lines)
