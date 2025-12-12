"""
Merlya Commands - Skill handlers.

Implements /skill command for managing skills.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml
from loguru import logger

from merlya.commands.registry import CommandResult, command, subcommand
from merlya.skills.loader import SkillLoader
from merlya.skills.registry import get_registry
from merlya.skills.wizard import SkillWizard, generate_skill_template

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.skills.models import SkillConfig

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
            "  `/skill list [tag]` - List all registered skills (optionally filter by tag)\n"
            "  `/skill show <name>` - Show skill details\n"
            "  `/skill create` - Create a new skill (wizard)\n"
            "  `/skill template <name>` - Generate a skill template\n"
            "  `/skill reload` - Reload skills from disk\n"
            "  `/skill run <name> [hosts]` - Run a skill\n"
        ),
        show_help=True,
    )


@subcommand("skill", "list", "List all registered skills", "/skill list [tag]")
async def cmd_skill_list(_ctx: SharedContext, args: list[str]) -> CommandResult:
    """List all registered skills, optionally filtered by tag."""
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

    # Filter by tag if provided
    tag_filter = args[0] if args else None
    if tag_filter:
        tagged = registry.find_by_tag(tag_filter)
        if not tagged:
            return CommandResult(
                success=True,
                message=(
                    f"No skills found for tag `{tag_filter}`.\n\n"
                    "Use `/skill list` to see all available skills."
                ),
            )

        lines = [f"**Skills tagged '{tag_filter}'** ({len(tagged)} total)\n"]

        # Split tagged skills into builtin and user
        builtin = [s for s in tagged if s.builtin]
        user = [s for s in tagged if not s.builtin]

        if builtin:
            lines.append("**Builtin:**")
            for skill in sorted(builtin, key=lambda s: s.name):
                lines.append(f"  `{skill.name}` - {skill.description}")
            lines.append("")

        if user:
            lines.append("**User:**")
            for skill in sorted(user, key=lambda s: s.name):
                lines.append(f"  `{skill.name}` - {skill.description}")

        return CommandResult(
            success=True, message="\n".join(lines), data={"tag": tag_filter, "count": len(tagged)}
        )

    # No tag filter - show all skills
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
        ui = ctx.ui
        if hasattr(ui, "confirm"):
            return await ui.confirm(message)
        return await ui.prompt_confirm(message)

    wizard = SkillWizard(
        prompt_callback=prompt_callback,
        confirm_callback=confirm_callback,
    )

    try:
        skill = await wizard.create_skill()
    except Exception as e:
        logger.exception(f"Skill creation failed: {e}")
        return CommandResult(
            success=False,
            message=f"❌ Skill creation failed: {e}",
        )

    if skill:
        # Enhance skill with LLM (full YAML generation with details)
        llm_skill = await _generate_skill_with_llm(ctx, skill)
        if llm_skill:
            skill = llm_skill
        else:
            ctx.ui.warning("LLM generation failed; using local configuration.")

        # Register the skill
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


async def _generate_skill_with_llm(ctx: SharedContext, skill: SkillConfig) -> SkillConfig | None:
    """
    Ask the LLM to enhance the skill YAML with detailed configuration.

    Patterns are already generated locally; LLM adds system_prompt, tools, etc.

    Returns:
        SkillConfig or None on failure.
    """
    try:
        from pydantic_ai import Agent

        from merlya.skills.loader import SkillLoader

        # Keep locally-generated patterns
        local_patterns = skill.intent_patterns

        base_yaml = yaml.safe_dump(
            skill.model_dump(exclude_none=True, exclude={"source_path", "builtin"}),
            sort_keys=False,
        )

        system_prompt = (
            "You are a Merlya skill generator for infrastructure automation. "
            "Given a skill template, enhance it with appropriate configuration. "
            "Output ONLY valid YAML, no markdown fences or explanations. "
            "IMPORTANT: Keep the intent_patterns exactly as provided - do not modify them. "
            "Focus on:\n"
            "- Writing a detailed system_prompt that guides the LLM on how to execute this skill\n"
            "- Selecting appropriate tools_allowed from: ssh_execute, read_file, write_file, "
            "check_service_status, get_raw_log, list_hosts, run_local_command\n"
            "- Setting sensible max_hosts and timeout_seconds\n"
            "- Adding relevant tags for categorization"
        )

        user_prompt = (
            f"Enhance this Merlya skill YAML:\n\n{base_yaml}\n\n"
            "Keep intent_patterns unchanged. Add detailed system_prompt and configuration."
        )

        model_id = f"{ctx.config.model.provider}:{ctx.config.model.model}"
        agent = Agent(model_id, system_prompt=system_prompt)

        with ctx.ui.spinner("Generating skill details with LLM..."):
            result = await agent.run(user_prompt)

        # pydantic_ai Agent result has .output attribute (not .data)
        yaml_text = getattr(result, "output", None) or getattr(result, "data", None)
        if not yaml_text:
            logger.warning("LLM returned empty output")
            return None

        # Clean up potential markdown fences
        yaml_text = str(yaml_text).strip()
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            yaml_text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        loader = SkillLoader()
        llm_skill = loader.load_from_string(yaml_text, builtin=False)

        if not llm_skill:
            logger.warning("LLM returned unusable skill YAML")
            return None

        # Preserve locally-generated patterns (don't let LLM override)
        llm_skill.intent_patterns = local_patterns

        return llm_skill
    except ImportError:
        logger.debug("pydantic_ai not available, skipping LLM enhancement")
        return None
    except Exception as e:
        logger.warning(f"LLM skill generation failed: {e}")
        return None


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

    # Check if exists and ask for confirmation
    if output_path.exists() and not await ctx.ui.confirm(
        f"Overwrite existing file `{output_path}`?"
    ):
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
    for skill in registry.get_user():
        registry.unregister(skill.name)

    # Reload from disk (load_all already registers skills via registry)
    with ctx.ui.spinner("Reloading skills..."):
        loader.load_all()

    stats = registry.get_stats()
    return CommandResult(
        success=True,
        message=(
            f"✅ Skills reloaded!\n\n"
            f"  Builtin: {stats['builtin']}\n"
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
                "Available hosts:\n" + "\n".join(f"  - `{h.name}`" for h in all_hosts[:10])
            ),
        )

    # Check host limit
    if len(hosts) > skill.max_hosts:
        return CommandResult(
            success=False,
            message=(
                f"Too many hosts ({len(hosts)}). Skill `{name}` allows max {skill.max_hosts} hosts."
            ),
        )

    # Execute skill
    from merlya.skills.executor import SkillExecutor

    executor = SkillExecutor(context=ctx)

    ctx.ui.info(f"Running skill `{name}` on {len(hosts)} host(s)...")

    with ctx.ui.spinner(f"Executing {name}..."):
        result = await executor.execute(
            skill=skill,
            hosts=[h.name for h in hosts],
            task=f"Run {name} skill",
        )

    if result.is_success:
        return CommandResult(
            success=True,
            message=f"✅ Skill `{name}` completed!\n\n{result.to_summary()}",
            data=result,
        )
    if result.is_partial:
        return CommandResult(
            success=False,
            message=f"⚠️ Skill `{name}` partially succeeded:\n\n{result.to_summary()}",
            data=result,
        )
    return CommandResult(
        success=False,
        message=f"❌ Skill `{name}` failed:\n\n{result.to_summary()}",
        data=result,
    )
