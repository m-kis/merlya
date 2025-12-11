"""
Merlya Skills - Interactive Wizard.

Guides users through creating custom skills interactively.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from merlya.skills.loader import SkillLoader
from merlya.skills.models import SkillConfig
from merlya.skills.registry import get_registry

if TYPE_CHECKING:
    from pathlib import Path

# Default tools that are commonly used
DEFAULT_TOOLS = [
    "ssh_execute",
    "read_file",
    "write_file",
    "check_service_status",
    "get_raw_log",
    "list_hosts",
]

# Common intent patterns by category
COMMON_PATTERNS = {
    "diagnostic": [
        r"diagnos.*",
        r"troubleshoot.*",
        r"debug.*",
        r"investigate.*",
    ],
    "disk": [
        r"disk.*",
        r"storage.*",
        r"space.*",
        r"df.*",
    ],
    "logs": [
        r"log.*",
        r"tail.*",
        r"journalctl.*",
    ],
    "services": [
        r"service.*",
        r"restart.*",
        r"status.*",
        r"systemctl.*",
    ],
    "network": [
        r"network.*",
        r"ping.*",
        r"connectivity.*",
        r"port.*",
    ],
}


class SkillWizard:
    """Interactive wizard for creating skills.

    Guides users through creating a skill step by step,
    with sensible defaults and validation.

    Example:
        >>> wizard = SkillWizard(prompt_callback=my_prompt_fn)
        >>> skill = await wizard.create_skill()
        >>> print(f"Created skill: {skill.name}")
    """

    def __init__(
        self,
        prompt_callback: Callable[[str, str | None], Any] | None = None,
        select_callback: Callable[[str, list[str]], Any] | None = None,
        confirm_callback: Callable[[str], Any] | None = None,
        loader: SkillLoader | None = None,
    ) -> None:
        """
        Initialize the wizard.

        Args:
            prompt_callback: Async callback for text prompts.
            select_callback: Async callback for selection prompts.
            confirm_callback: Async callback for confirmations.
            loader: Skill loader for saving.
        """
        self.prompt = prompt_callback
        self.select = select_callback
        self.confirm = confirm_callback
        self.loader = loader or SkillLoader()

    async def create_skill(self) -> SkillConfig | None:
        """
        Create a new skill interactively.

        Returns:
            Created SkillConfig or None if cancelled.
        """
        if not self.prompt:
            logger.error("❌ No prompt callback provided")
            return None

        logger.info("🧙 Starting skill creation wizard")

        # Step 1: Name
        name = await self._prompt_name()
        if not name:
            return None

        # Step 2: Description
        description = await self._prompt_description()

        # Step 3: Intent patterns
        patterns = await self._prompt_patterns()

        # Step 4: Tools
        tools = await self._prompt_tools()

        # Step 5: Limits
        max_hosts, timeout = await self._prompt_limits()

        # Step 6: Confirmation operations
        confirm_ops = await self._prompt_confirmations()

        # Step 7: System prompt (optional)
        system_prompt = await self._prompt_system_prompt(name, description)

        # Normalize optional values to avoid None/invalid entries in validators
        patterns = [p.strip() for p in (patterns or []) if isinstance(p, str) and p.strip()] or [r".*"]
        tools = [t.strip() for t in (tools or []) if isinstance(t, str) and t.strip()]
        confirm_ops = [
            c.strip() for c in (confirm_ops or []) if isinstance(c, str) and c.strip()
        ]
        description = description or ""
        system_prompt = system_prompt or None

        # Create config
        skill = SkillConfig(
            name=name,
            description=description,
            intent_patterns=patterns,
            tools_allowed=tools,
            max_hosts=max_hosts,
            timeout_seconds=timeout,
            require_confirmation_for=confirm_ops,
            system_prompt=system_prompt,
        )

        # Confirm and save
        if self.confirm:
            confirmed = await self.confirm(f"Create skill '{name}'?")
            if not confirmed:
                logger.info("🚫 Skill creation cancelled")
                return None

        # Save to user directory
        path = self.loader.save_user_skill(skill)
        logger.info(f"✅ Skill '{name}' created at {path}")

        return skill

    async def _prompt_name(self) -> str | None:
        """Prompt for skill name."""
        if not self.prompt:
            return None

        while True:
            name = await self.prompt("📝 Skill name (e.g., disk_audit):", None)
            if not name:
                return None

            # Validate name
            name = name.strip().lower().replace(" ", "_")

            if len(name) < 2:
                logger.warning("⚠️ Name too short (min 2 characters)")
                continue

            if len(name) > 50:
                logger.warning("⚠️ Name too long (max 50 characters)")
                continue

            # Check if exists
            if get_registry().has(name):
                logger.warning(f"⚠️ Skill '{name}' already exists")
                if self.confirm and not await self.confirm("Overwrite existing skill?"):
                    continue

            return name

    async def _prompt_description(self) -> str:
        """Prompt for description."""
        if not self.prompt:
            return ""

        desc = await self.prompt("📋 Description:", None)
        return desc.strip() if desc else ""

    async def _prompt_patterns(self) -> list[str]:
        """Prompt for intent patterns."""
        patterns: list[str] = []

        if self.select:
            # Offer common patterns
            category = await self.select(
                "🎯 Select pattern category:",
                list(COMMON_PATTERNS.keys()) + ["custom"],
            )

            if category and category != "custom":
                patterns = COMMON_PATTERNS.get(category, [])

        # Patterns that are too generic and not allowed
        forbidden = {".*", ".+", "^.*$", "^.+$", r"[\s\S]*", r"[\s\S]+"}

        if self.prompt and not patterns:
            while True:
                input_str = await self.prompt(
                    "🎯 Intent patterns (comma-separated, e.g., 'git.*', 'deploy.*'):",
                    None,
                )
                if not input_str:
                    logger.info("ℹ️ No patterns specified - skill won't auto-match (manual invocation only)")
                    break

                raw_patterns = [p.strip() for p in input_str.split(",") if p.strip()]
                valid = [p for p in raw_patterns if p not in forbidden]
                rejected = [p for p in raw_patterns if p in forbidden]

                if rejected:
                    logger.warning(f"⚠️ Catch-all patterns rejected: {rejected}")
                    logger.info("💡 Use specific patterns like 'git.*' or 'deploy.*web' instead")
                    if valid:
                        patterns = valid
                        break
                    # Loop to ask again
                    continue
                else:
                    patterns = valid
                    break

        return patterns  # Empty = no auto-match (agent handles)

    async def _prompt_tools(self) -> list[str]:
        """Prompt for allowed tools."""
        tools: list[str] = []

        if self.select:
            # Multi-select from default tools
            selected = await self.select(
                "🔧 Select allowed tools:",
                DEFAULT_TOOLS + ["all"],
            )

            # Handle None explicitly - treat as "all"
            if selected is None:
                tools = []  # Empty means all allowed
            elif isinstance(selected, str):
                # Handle string: "all" or single tool name
                if selected == "all":
                    tools = []  # Empty means all allowed
                elif selected.strip():
                    tools = [selected.strip()]
            elif isinstance(selected, (list, tuple, set)):
                # Handle iterables: filter for valid string entries
                tools = [
                    s.strip()
                    for s in selected
                    if isinstance(s, str) and s.strip()
                ]
            else:
                # Unexpected type (int, float, etc.) - log and treat as "all"
                logger.warning(
                    f"Unexpected type from select callback: {type(selected).__name__}, "
                    "treating as 'all tools allowed'"
                )
                tools = []

        if self.prompt and not tools:
            input_str = await self.prompt(
                "🔧 Allowed tools (comma-separated, empty=all):",
                None,
            )
            if input_str:
                tools = [t.strip() for t in input_str.split(",") if t.strip()]

        return tools

    async def _prompt_limits(self) -> tuple[int, int]:
        """Prompt for execution limits."""
        max_hosts = 5
        timeout = 120

        if self.prompt:
            hosts_str = await self.prompt("🖥️ Max hosts (default=5):", "5")
            if hosts_str:
                try:
                    max_hosts = max(1, min(int(hosts_str), 100))
                except ValueError:
                    pass

            timeout_str = await self.prompt("⏱️ Timeout seconds (default=120):", "120")
            if timeout_str:
                try:
                    timeout = max(10, min(int(timeout_str), 600))
                except ValueError:
                    pass

        return max_hosts, timeout

    async def _prompt_confirmations(self) -> list[str]:
        """Prompt for operations requiring confirmation."""
        default_ops = ["restart", "kill", "delete", "stop"]

        if self.prompt:
            input_str = await self.prompt(
                "⚠️ Operations requiring confirmation (comma-separated):",
                ",".join(default_ops),
            )
            if input_str:
                return [op.strip() for op in input_str.split(",") if op.strip()]

        return default_ops

    async def _prompt_system_prompt(self, name: str, description: str) -> str | None:
        """Prompt for optional system prompt."""
        if self.confirm:
            want_prompt = await self.confirm("Add custom system prompt?")
            if not want_prompt:
                return None

        if self.prompt:
            prompt = await self.prompt(
                "💬 System prompt for LLM (or empty to skip):",
                None,
            )
            if prompt and prompt.strip():
                return prompt.strip()

        # Generate a default
        return f"You are executing the '{name}' skill. {description}"

    async def edit_skill(self, name: str) -> SkillConfig | None:
        """
        Edit an existing skill.

        Args:
            name: Skill name to edit.

        Returns:
            Updated SkillConfig or None if cancelled.
        """
        skill = get_registry().get(name)
        if not skill:
            logger.error(f"❌ Skill not found: {name}")
            return None

        if skill.builtin:
            logger.warning(f"⚠️ Cannot edit builtin skill: {name}")
            return None

        # TODO: Implement full edit flow
        # For now, just re-run create with existing values as defaults
        logger.info(f"🧙 Editing skill: {name}")
        return await self.create_skill()

    async def duplicate_skill(self, name: str, new_name: str) -> SkillConfig | None:
        """
        Duplicate a skill with a new name.

        Args:
            name: Skill to duplicate.
            new_name: New skill name.

        Returns:
            New SkillConfig or None if failed.
        """
        skill = get_registry().get(name)
        if not skill:
            logger.error(f"❌ Skill not found: {name}")
            return None

        # Validate new_name
        if not new_name or not new_name.strip():
            logger.error("❌ New skill name cannot be empty")
            return None

        new_name = new_name.strip().lower().replace(" ", "_")

        if len(new_name) < 2:
            logger.error("❌ New skill name too short (min 2 characters)")
            return None

        if len(new_name) > 50:
            logger.error("❌ New skill name too long (max 50 characters)")
            return None

        # Check if new_name already exists
        if get_registry().has(new_name):
            if self.confirm:
                confirmed = await self.confirm(
                    f"Skill '{new_name}' already exists. Overwrite?"
                )
                if not confirmed:
                    logger.info("🚫 Skill duplication cancelled")
                    return None
            else:
                logger.error(f"❌ Skill '{new_name}' already exists")
                return None

        # Create copy with new name
        new_skill = SkillConfig(
            name=new_name,
            version=skill.version,
            description=f"Copy of {skill.description}",
            intent_patterns=skill.intent_patterns.copy(),
            tools_allowed=skill.tools_allowed.copy(),
            max_hosts=skill.max_hosts,
            timeout_seconds=skill.timeout_seconds,
            require_confirmation_for=skill.require_confirmation_for.copy(),
            system_prompt=skill.system_prompt,
            tags=skill.tags.copy(),
        )

        # Save with error handling
        try:
            path = self.loader.save_user_skill(new_skill)
            logger.info(f"✅ Skill '{new_name}' created at {path}")
        except OSError as e:
            logger.error(f"❌ Failed to save skill '{new_name}': {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error saving skill '{new_name}': {e}")
            return None

        return new_skill


def generate_skill_template(name: str, description: str = "") -> str:
    """
    Generate a YAML template for a new skill.

    Args:
        name: Skill name.
        description: Skill description.

    Returns:
        YAML string template.
    """
    # Generate specific patterns based on name
    name_pattern = name.replace("_", ".*")  # disk_audit -> disk.*audit
    return f"""# Merlya Skill: {name}
# Edit this file to customize the skill behavior

name: {name}
version: "1.0"
description: "{description or 'Custom skill'}"

# Intent patterns (regex) - when should this skill be triggered?
# IMPORTANT: Don't use catch-all patterns like '.*' - be specific!
# Examples: 'disk.*audit', 'git.*push', 'deploy.*prod'
intent_patterns:
  - "{name_pattern}"

# Allowed tools - empty list means all tools
tools_allowed:
  - ssh_execute
  - read_file

# Execution limits
max_hosts: 5
timeout_seconds: 120

# Operations requiring user confirmation
require_confirmation_for:
  - restart
  - kill
  - delete
  - stop

# Custom system prompt for LLM (optional)
# system_prompt: |
#   You are an expert in {name}.
#   Focus on...

# Tags for categorization
tags:
  - custom
"""
