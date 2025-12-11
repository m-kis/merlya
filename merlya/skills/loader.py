"""
Merlya Skills - Loader.

Loads skills from YAML files in builtin and user directories.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from pydantic import ValidationError

from merlya.skills.models import SkillConfig
from merlya.skills.registry import SkillRegistry, get_registry

# Default paths
BUILTIN_SKILLS_DIR = Path(__file__).parent / "builtin"
USER_SKILLS_DIR = Path.home() / ".merlya" / "skills"


class SkillLoader:
    """Loads skills from YAML files.

    Scans builtin and user directories for skill definitions,
    validates them, and registers them with the registry.

    Example:
        >>> loader = SkillLoader()
        >>> loaded = loader.load_all()
        >>> print(f"Loaded {loaded} skills")
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        builtin_dir: Path | None = None,
        user_dir: Path | None = None,
    ) -> None:
        """
        Initialize the loader.

        Args:
            registry: Registry to load skills into (uses global if None).
            builtin_dir: Directory for builtin skills.
            user_dir: Directory for user skills.
        """
        self.registry = registry or get_registry()
        self.builtin_dir = builtin_dir or BUILTIN_SKILLS_DIR
        self.user_dir = user_dir or USER_SKILLS_DIR

    def load_all(self) -> int:
        """
        Load all skills from builtin and user directories.

        Returns:
            Number of skills loaded.
        """
        count = 0

        # Load builtin skills first
        count += self.load_builtin()

        # Load user skills (can override builtin)
        count += self.load_user()

        return count

    def load_builtin(self) -> int:
        """
        Load builtin skills.

        Returns:
            Number of skills loaded.
        """
        if not self.builtin_dir.exists():
            logger.debug(f"📁 Builtin skills directory not found: {self.builtin_dir}")
            return 0

        return self._load_from_directory(self.builtin_dir, builtin=True)

    def load_user(self) -> int:
        """
        Load user-defined skills.

        Returns:
            Number of skills loaded.
        """
        if not self.user_dir.exists():
            logger.debug(f"📁 User skills directory not found: {self.user_dir}")
            return 0

        return self._load_from_directory(self.user_dir, builtin=False)

    def _load_from_directory(self, directory: Path, builtin: bool = False) -> int:
        """
        Load skills from a directory.

        Args:
            directory: Directory to scan.
            builtin: Whether these are builtin skills.

        Returns:
            Number of skills loaded.
        """
        count = 0

        for yaml_file in directory.glob("*.yaml"):
            skill = self.load_file(yaml_file, builtin=builtin)
            if skill:
                count += 1

        for yml_file in directory.glob("*.yml"):
            skill = self.load_file(yml_file, builtin=builtin)
            if skill:
                count += 1

        logger.debug(f"📁 Loaded {count} skills from {directory}")
        return count

    def load_file(self, path: Path, builtin: bool = False) -> SkillConfig | None:
        """
        Load a single skill from a YAML file.

        Args:
            path: Path to YAML file.
            builtin: Whether this is a builtin skill.

        Returns:
            SkillConfig or None if loading failed.
        """
        try:
            with path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not data:
                logger.warning(f"⚠️ Empty skill file: {path}")
                return None

            # Add metadata
            data["builtin"] = builtin
            data["source_path"] = str(path)

            # Validate and create config
            skill = SkillConfig.model_validate(data)

            # Register
            self.registry.register(skill)

            logger.debug(f"📄 Loaded skill: {skill.name} from {path.name}")
            return skill

        except yaml.YAMLError as e:
            logger.error(f"❌ Invalid YAML in {path}: {e}")
            return None
        except ValidationError as e:
            logger.error(f"❌ Invalid skill config in {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Failed to load skill from {path}: {e}")
            return None

    def load_from_string(self, yaml_content: str, builtin: bool = False) -> SkillConfig | None:
        """
        Load a skill from a YAML string.

        Args:
            yaml_content: YAML content.
            builtin: Whether this is a builtin skill.

        Returns:
            SkillConfig or None if loading failed.
        """
        try:
            data = yaml.safe_load(yaml_content)

            if not data:
                logger.warning("⚠️ Empty skill content")
                return None

            data["builtin"] = builtin

            skill = SkillConfig.model_validate(data)
            self.registry.register(skill)

            logger.debug(f"📄 Loaded skill from string: {skill.name}")
            return skill

        except yaml.YAMLError as e:
            logger.error(f"❌ Invalid YAML: {e}")
            return None
        except ValidationError as e:
            logger.error(f"❌ Invalid skill config: {e}")
            return None

    def save_user_skill(self, skill: SkillConfig) -> Path:
        """
        Save a skill to the user skills directory.

        Args:
            skill: Skill to save.

        Returns:
            Path to the saved file.
        """
        # Ensure directory exists
        self.user_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        filename = f"{skill.name}.yaml"
        path = self.user_dir / filename

        # Convert to dict, excluding source_path and builtin
        data = skill.model_dump(exclude={"source_path", "builtin"}, exclude_none=True)

        # Add header comment
        yaml_content = f"# Merlya Skill: {skill.name}\n"
        yaml_content += f"# Version: {skill.version}\n"
        yaml_content += f"# Created by Merlya SkillWizard\n\n"
        yaml_content += yaml.dump(data, default_flow_style=False, sort_keys=False)

        with path.open("w", encoding="utf-8") as f:
            f.write(yaml_content)

        # Update source_path
        skill.source_path = str(path)
        skill.builtin = False

        logger.info(f"💾 Saved skill to: {path}")
        return path

    def delete_user_skill(self, name: str) -> bool:
        """
        Delete a user skill.

        Args:
            name: Skill name to delete.

        Returns:
            True if deleted, False if not found or is builtin.
        """
        skill = self.registry.get(name)

        if not skill:
            logger.warning(f"⚠️ Skill not found: {name}")
            return False

        if skill.builtin:
            logger.warning(f"⚠️ Cannot delete builtin skill: {name}")
            return False

        if skill.source_path:
            path = Path(skill.source_path)
            if path.exists():
                path.unlink()
                logger.info(f"🗑️ Deleted skill file: {path}")

        self.registry.unregister(name)
        return True


def load_all_skills() -> int:
    """
    Convenience function to load all skills.

    Returns:
        Number of skills loaded.
    """
    loader = SkillLoader()
    return loader.load_all()
