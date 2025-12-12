"""
Merlya Skills - Interactive Wizard.

Guides users through creating custom skills interactively.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.skills.loader import SkillLoader
from merlya.skills.models import SkillConfig
from merlya.skills.registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable

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

        # Step 2: Description (important for pattern generation)
        description = await self._prompt_description()
        if not description:
            logger.warning("⚠️ Une description est recommandée pour générer de bons patterns")

        # Step 3: Generate patterns automatically with LLM
        logger.info("🤖 Génération automatique des patterns d'intention...")
        patterns = await self._generate_patterns_with_llm(name, description or name)
        if patterns:
            logger.info(f"✅ Patterns générés: {', '.join(patterns)}")

        # Step 4: Advanced options (optional - use defaults if skipped)
        tools: list[str] = []  # Empty = all tools allowed
        max_hosts = 5
        timeout = 120
        confirm_ops = ["restart", "kill", "delete", "stop", "rm", "reboot"]

        if self.confirm:
            want_advanced = await self.confirm("Configurer les options avancées? (outils, limites)")
            if want_advanced:
                tools = await self._prompt_tools()
                max_hosts, timeout = await self._prompt_limits()
                confirm_ops = await self._prompt_confirmations()

        # Step 5: System prompt (auto-generated from description)
        system_prompt = f"Tu exécutes le skill '{name}'. {description}" if description else None

        # Normalize optional values
        patterns = [p.strip() for p in (patterns or []) if isinstance(p, str) and p.strip()]
        tools = [t.strip() for t in (tools or []) if isinstance(t, str) and t.strip()]
        confirm_ops = [c.strip() for c in (confirm_ops or []) if isinstance(c, str) and c.strip()]
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

            return str(name)

    async def _prompt_description(self) -> str:
        """Prompt for description."""
        if not self.prompt:
            return ""

        desc = await self.prompt("📋 Description:", None)
        return desc.strip() if desc else ""

    async def _prompt_patterns(self) -> list[str]:
        """Generate intent patterns automatically from name and description."""
        # Patterns are now generated by LLM in create_skill()
        # This method is kept for backward compatibility but returns empty
        return []

    async def _generate_patterns_with_llm(self, name: str, description: str) -> list[str]:
        """Use LLM to generate appropriate intent patterns from name and description."""
        try:
            from pydantic_ai import Agent

            # Get LLM model from config or use a default
            model = "openrouter:google/gemini-2.0-flash-lite-001"

            system_prompt = """Tu es un expert en création de patterns regex pour matcher des intentions utilisateur.

Génère 3-5 patterns regex SPÉCIFIQUES pour détecter quand un utilisateur veut utiliser ce skill.

RÈGLES IMPORTANTES:
1. NE JAMAIS utiliser .* ou .+ seuls - ils matchent TOUT
2. Utiliser des mots-clés spécifiques du domaine
3. Les patterns doivent être en français ET anglais
4. Chaque pattern doit matcher au moins 3 caractères spécifiques

EXEMPLES:
- Skill "git_flow" → ["git.*commit", "git.*push", "pull.*request", "merge.*branch", "gh.*"]
- Skill "disk_audit" → ["disk.*usage", "espace.*disque", "df.*", "storage.*check", "stockage.*"]
- Skill "web_search" → ["recherche.*web", "cherche.*internet", "google.*", "search.*online"]

Réponds UNIQUEMENT avec les patterns séparés par des virgules, rien d'autre."""

            agent = Agent(model, system_prompt=system_prompt)

            prompt = f"Skill: {name}\nDescription: {description}\n\nGénère les patterns:"
            response = await agent.run(prompt)

            # Parse response
            raw = str(getattr(response, "data", response))
            patterns = [p.strip() for p in raw.split(",") if p.strip()]

            # Filter out catch-all patterns
            forbidden = {".*", ".+", "^.*$", "^.+$", r"[\s\S]*", r"[\s\S]+"}
            valid_patterns = [p for p in patterns if p not in forbidden and len(p) >= 3]

            if valid_patterns:
                logger.info(f"🤖 Patterns générés: {valid_patterns}")
                return valid_patterns[:5]  # Max 5 patterns

        except Exception as e:
            logger.debug(f"LLM pattern generation failed: {e}")

        # Fallback: generate simple patterns from name
        return self._generate_fallback_patterns(name, description)

    def _generate_fallback_patterns(self, name: str, description: str) -> list[str]:
        """Generate simple patterns when LLM is not available."""
        patterns = []

        # From name: disk_audit -> ["disk.*audit", "disk.*"]
        parts = name.lower().split("_")
        if len(parts) >= 2:
            patterns.append(f"{parts[0]}.*{parts[1]}")
        if parts:
            patterns.append(f"{parts[0]}.*")

        # From description: extract key words
        if description:
            # Common action words to look for
            keywords = []
            desc_lower = description.lower()
            for word in [
                "audit",
                "check",
                "verify",
                "scan",
                "search",
                "deploy",
                "build",
                "test",
                "monitor",
            ]:
                if word in desc_lower:
                    keywords.append(word)
            for kw in keywords[:2]:
                patterns.append(f"{kw}.*")

        return patterns[:5] if patterns else [f"{name}.*"]

    async def _prompt_tools(self) -> list[str]:
        """Prompt for allowed tools."""
        tools: list[str] = []

        if self.select:
            # Multi-select from default tools
            selected = await self.select(
                "🔧 Select allowed tools:",
                [*DEFAULT_TOOLS, "all"],
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
                tools = [s.strip() for s in selected if isinstance(s, str) and s.strip()]
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
                with contextlib.suppress(ValueError):
                    max_hosts = max(1, min(int(hosts_str), 100))

            timeout_str = await self.prompt("⏱️ Timeout seconds (default=120):", "120")
            if timeout_str:
                with contextlib.suppress(ValueError):
                    timeout = max(30, min(int(timeout_str), 600))  # Min 30s per model

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
                return str(prompt).strip()

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
                confirmed = await self.confirm(f"Skill '{new_name}' already exists. Overwrite?")
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
description: "{description or "Custom skill"}"

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
