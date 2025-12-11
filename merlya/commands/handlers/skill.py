"""
Merlya Commands - Skill handlers.

Implements /skill command for managing skills.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.skills.loader import SkillLoader
from merlya.skills.registry import get_registry
from merlya.skills.wizard import SkillWizard, generate_skill_template

if TYPE_CHECKING:
    from merlya.core.context import SharedContext

# Valid skill name pattern (alphanumeric, underscores, hyphens, 2-50 chars)
_VALID_SKILL_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,49}$")


@command("skill", "Manage skills for automated workflows", "/skill <subcommand>")
async def cmd_skill(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Manage skills (workflows) for infrastructure automation."""
    if not args:
        return await cmd_skill_list(ctx, [])

    return CommandResult(
        success=False,
        message=(
            "**Skill Commands:**\n\n"
            "  `/skill list` - List all registered skills\n"
            "  `/skill show <name>` - Show skill details\n"
            "  `/skill create` - Create a new skill (wizard)\n"
            "  `/skill template <name>` - Generate a skill template\n"
            "  `/skill reload` - Reload skills from disk\n"
            "  `/skill run <name> [hosts]` - Run a skill\n"
        ),
        show_help=True,
    )


@subcommand("skill", "list", "List all registered skills", "/skill list")
async def cmd_skill_list(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """List all registered skills."""
    registry = get_registry()
    stats = registry.get_stats()

    if stats["total"] == 0:
        return CommandResult(
            success=True,
            message=(
                "No skills registered.\n\n"
                "Use `/skill create` to create a new skill or\n"
                "`/skill reload` to load skills from disk."
            ),
        )

    lines = [f"**Registered Skills** ({stats['total']} total)\n"]

    # Builtin skills
    builtin = registry.get_builtin()
    if builtin:
        lines.append("**Builtin:**")
        for skill in sorted(builtin, key=lambda s: s.name):
            lines.append(f"  `{skill.name}` - {skill.description}")
        lines.append("")

    # User skills
    user = registry.get_user()
    if user:
        lines.append("**User:**")
        for skill in sorted(user, key=lambda s: s.name):
            lines.append(f"  `{skill.name}` - {skill.description}")

    # Show tag filter if provided
    if args:
        tag = args[0]
        tagged = registry.find_by_tag(tag)
        if tagged:
            lines.append(f"\n**Tagged '{tag}':** {len(tagged)} skills")

    return CommandResult(success=True, message="\n".join(lines), data=stats)


@subcommand("skill", "show", "Show skill details", "/skill show <name>")
async def cmd_skill_show(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """Show detailed information about a skill."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/skill show <name>`",
            show_help=True,
        )

    name = args[0]
    skill = get_registry().get(name)

    if not skill:
        return CommandResult(
            success=False,
            message=f"Skill not found: `{name}`\n\nUse `/skill list` to see available skills.",
        )

    lines = [
        f"**Skill: {skill.name}**\n",
        f"  Version: `{skill.version}`",
        f"  Description: {skill.description}",
        f"  Type: {'builtin' if skill.builtin else 'user'}",
        "",
        "**Configuration:**",
        f"  Max hosts: `{skill.max_hosts}`",
        f"  Timeout: `{skill.timeout_seconds}s`",
    ]

    if skill.tools_allowed:
        lines.append(f"  Tools: `{', '.join(skill.tools_allowed)}`")
    else:
        lines.append("  Tools: `all`")

    if skill.intent_patterns:
        patterns = ", ".join(f"`{p}`" for p in skill.intent_patterns[:3])
        if len(skill.intent_patterns) > 3:
            patterns += f" (+{len(skill.intent_patterns) - 3} more)"
        lines.append(f"  Patterns: {patterns}")

    if skill.require_confirmation_for:
        lines.append(f"  Requires confirmation for: `{', '.join(skill.require_confirmation_for)}`")

    if skill.tags:
        lines.append(f"  Tags: `{', '.join(skill.tags)}`")

    if skill.source_path:
        lines.append(f"\n  Source: `{skill.source_path}`")

    return CommandResult(success=True, message="\n".join(lines), data=skill)


@subcommand("skill", "create", "Create a new skill interactively", "/skill create")
async def cmd_skill_create(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Create a new skill using the interactive wizard."""
    # Create callbacks that use the UI
    async def prompt_callback(message: str, default: str | None) -> str | None:
        return await ctx.ui.prompt(message, default)

    async def confirm_callback(message: str) -> bool:
        return await ctx.ui.confirm(message)

    wizard = SkillWizard(
        prompt_callback=prompt_callback,
        confirm_callback=confirm_callback,
    )

    skill = await wizard.create_skill()

    if skill:
        # Register the new skill
        get_registry().register(skill)
        return CommandResult(
            success=True,
            message=f"✅ Skill `{skill.name}` created and registered!",
            data=skill,
        )
    else:
        return CommandResult(
            success=False,
            message="Skill creation cancelled.",
        )


@subcommand("skill", "template", "Generate a skill template file", "/skill template <name>")
async def cmd_skill_template(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Generate a YAML template for a new skill."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/skill template <name> [description]`",
            show_help=True,
        )

    name = args[0]

    # Validate name (security: prevent path traversal)
    if not _VALID_SKILL_NAME.match(name):
        return CommandResult(
            success=False,
            message=(
                f"Invalid skill name: `{name}`\n\n"
                "Name must start with a letter, contain only alphanumeric characters, "
                "underscores or hyphens, and be 2-50 characters long."
            ),
        )

    description = " ".join(args[1:]) if len(args) > 1 else ""

    # Generate template
    template = generate_skill_template(name, description)

    # Determine output path
    from pathlib import Path

    user_skills_dir = Path.home() / ".merlya" / "skills"
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    output_path = user_skills_dir / f"{name}.yaml"

    # Check if exists
    if output_path.exists():
        if not await ctx.ui.confirm(f"Overwrite existing file `{output_path}`?"):
            return CommandResult(success=False, message="Template generation cancelled.")

    # Write template
    output_path.write_text(template)
    logger.info(f"✅ Skill template created: {output_path}")

    return CommandResult(
        success=True,
        message=(
            f"✅ Template created: `{output_path}`\n\n"
            f"Edit the file to customize the skill, then use `/skill reload` to load it."
        ),
        data={"path": str(output_path), "name": name},
    )


@subcommand("skill", "reload", "Reload skills from disk", "/skill reload")
async def cmd_skill_reload(ctx: SharedContext, _args: list[str]) -> CommandResult:
    """Reload all skills from disk."""
    registry = get_registry()
    loader = SkillLoader()

    # Clear user skills (keep builtin)
    builtin_count = len(registry.get_builtin())
    for skill in registry.get_user():
        registry.unregister(skill.name)

    # Reload from disk
    with ctx.ui.spinner("Reloading skills..."):
        loaded = loader.load_all()
        for skill in loaded:
            registry.register(skill)

    stats = registry.get_stats()
    return CommandResult(
        success=True,
        message=(
            f"✅ Skills reloaded!\n\n"
            f"  Builtin: {builtin_count}\n"
            f"  User: {stats['user']}\n"
            f"  Total: {stats['total']}"
        ),
        data=stats,
    )


@subcommand("skill", "run", "Run a skill on hosts", "/skill run <name> [hosts...]")
async def cmd_skill_run(ctx: SharedContext, args: list[str]) -> CommandResult:
    """Run a skill on specified hosts."""
    if not args:
        return CommandResult(
            success=False,
            message="Usage: `/skill run <name> [host1] [host2] ...`",
            show_help=True,
        )

    name = args[0]
    host_names = args[1:] if len(args) > 1 else []

    skill = get_registry().get(name)
    if not skill:
        return CommandResult(
            success=False,
            message=f"Skill not found: `{name}`",
        )

    # Resolve hosts
    hosts = []
    for host_name in host_names:
        host = await ctx.hosts.get_by_name(host_name)
        if not host:
            return CommandResult(
                success=False,
                message=f"Host not found: `{host_name}`",
            )
        hosts.append(host)

    # If no hosts specified, prompt for selection
    if not hosts:
        all_hosts = await ctx.hosts.get_all()
        if not all_hosts:
            return CommandResult(
                success=False,
                message="No hosts configured. Use `/hosts add` first.",
            )

        # For now, just list hosts
        return CommandResult(
            success=False,
            message=(
                f"Please specify hosts to run `{name}` on:\n\n"
                f"Usage: `/skill run {name} host1 host2 ...`\n\n"
                "Available hosts:\n"
                + "\n".join(f"  - `{h.name}`" for h in all_hosts[:10])
            ),
        )

    # Check host limit
    if len(hosts) > skill.max_hosts:
        return CommandResult(
            success=False,
            message=(
                f"Too many hosts ({len(hosts)}). "
                f"Skill `{name}` allows max {skill.max_hosts} hosts."
            ),
        )

    # Execute skill
    from merlya.skills.executor import SkillExecutor

    executor = SkillExecutor()

    ctx.ui.info(f"Running skill `{name}` on {len(hosts)} host(s)...")

    with ctx.ui.spinner(f"Executing {name}..."):
        result = await executor.execute(
            skill=skill,
            ctx=ctx,
            hosts=[h.name for h in hosts],
            user_input=f"Run {name} skill",
        )

    if result.success:
        return CommandResult(
            success=True,
            message=f"✅ Skill `{name}` completed!\n\n{result.summary}",
            data=result,
        )
    else:
        return CommandResult(
            success=False,
            message=f"❌ Skill `{name}` failed:\n\n{result.error or 'Unknown error'}",
            data=result,
        )
