"""
Merlya Skills - Loader.

Loads skills from YAML files in builtin and user directories.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml
from loguru import logger
from pydantic import ValidationError

from merlya.skills.models import SkillConfig
from merlya.skills.registry import SkillRegistry, get_registry

# Default paths
BUILTIN_SKILLS_DIR = Path(__file__).parent / "builtin"
USER_SKILLS_DIR = Path.home() / ".merlya" / "skills"

# File size limits
MAX_YAML_FILE_SIZE = 1_000_000  # 1MB max for YAML files
MAX_YAML_STRING_SIZE = 100_000  # 100KB max for YAML strings
YAML_EXTENSIONS = ("*.yaml", "*.yml")


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
            Total number of unique skills loaded.
        """
        # Load builtin skills first
        builtin_new, _ = self.load_builtin()

        # Load user skills (can override builtin)
        user_new, _user_overwritten = self.load_user()

        # Return unique skill count (builtin + new user skills, not counting overwrites)
        return builtin_new + user_new

    def load_builtin(self) -> tuple[int, int]:
        """
        Load builtin skills.

        Returns:
            Tuple of (new_count, overwritten_count).
        """
        if not self.builtin_dir.exists():
            logger.debug(f"📁 Builtin skills directory not found: {self.builtin_dir}")
            return 0, 0

        return self._load_from_directory(self.builtin_dir, builtin=True)

    def load_user(self) -> tuple[int, int]:
        """
        Load user-defined skills.

        Returns:
            Tuple of (new_count, overwritten_count).
        """
        if not self.user_dir.exists():
            logger.debug(f"📁 User skills directory not found: {self.user_dir}")
            return 0, 0

        return self._load_from_directory(self.user_dir, builtin=False)

    def _load_from_directory(self, directory: Path, builtin: bool = False) -> tuple[int, int]:
        """
        Load skills from a directory.

        Args:
            directory: Directory to scan.
            builtin: Whether these are builtin skills.

        Returns:
            Tuple of (new_skills_count, overwritten_count).
        """
        new_count = 0
        overwritten = 0

        for extension in YAML_EXTENSIONS:
            for skill_file in directory.glob(extension):
                # Check if skill already exists before loading
                try:
                    with skill_file.open(encoding="utf-8", errors="replace") as f:
                        data = yaml.safe_load(f)
                    skill_name = data.get("name", "").lower() if data else None
                    existed = skill_name and self.registry.has(skill_name)
                except Exception:
                    existed = False

                skill = self.load_file(skill_file, builtin=builtin)
                if skill:
                    if existed:
                        overwritten += 1
                    else:
                        new_count += 1

        logger.debug(
            f"📁 Loaded {new_count} new skills from {directory} ({overwritten} overwritten)"
        )
        return new_count, overwritten

    def _is_safe_path(self, path: Path, allowed_dir: Path) -> bool:
        """Check if path is within allowed directory (path traversal protection)."""
        try:
            resolved = path.resolve()
            allowed_resolved = allowed_dir.resolve()
            return str(resolved).startswith(str(allowed_resolved))
        except (OSError, ValueError):
            return False

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
            # Path traversal protection
            allowed_dir = self.builtin_dir if builtin else self.user_dir
            if not self._is_safe_path(path, allowed_dir):
                logger.warning(f"⚠️ Path traversal blocked: {path}")
                return None

            # File size check
            file_size = path.stat().st_size
            if file_size > MAX_YAML_FILE_SIZE:
                logger.warning(f"⚠️ File too large ({file_size} bytes): {path}")
                return None

            # Read with UTF-8 error handling
            with path.open(encoding="utf-8", errors="replace") as f:
                data = yaml.safe_load(f)

            # Type validation
            if not data or not isinstance(data, dict):
                logger.warning(f"⚠️ Invalid skill file format: {path}")
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
        except OSError as e:
            logger.error(f"❌ Failed to read file {path}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Unexpected error loading {path}: {type(e).__name__}: {e}")
            return None

    def load_from_string(self, yaml_content: str, builtin: bool = False) -> SkillConfig | None:
        """
        Load a skill from a YAML string.

        Args:
            yaml_content: YAML content (max 100KB).
            builtin: Whether this is a builtin skill.

        Returns:
            SkillConfig or None if loading failed.
        """
        try:
            # Size validation
            if len(yaml_content) > MAX_YAML_STRING_SIZE:
                logger.warning(f"⚠️ YAML content too large ({len(yaml_content)} bytes)")
                return None

            data = yaml.safe_load(yaml_content)

            # Type validation
            if not data or not isinstance(data, dict):
                logger.warning("⚠️ Invalid skill content format")
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
        Save a skill to the user skills directory using atomic write.

        Args:
            skill: Skill to save.

        Returns:
            Path to the saved file.

        Raises:
            OSError: If writing fails.
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
        yaml_content += "# Created by Merlya SkillWizard\n\n"
        yaml_content += yaml.dump(data, default_flow_style=False, sort_keys=False)

        # Atomic write: write to temp file then rename
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.user_dir,
                suffix=".yaml.tmp",
                delete=False,
            ) as f:
                f.write(yaml_content)
                temp_path = Path(f.name)

            # Atomic rename
            temp_path.rename(path)
        except OSError as e:
            logger.error(f"❌ Failed to save skill: {e}")
            # Cleanup temp file if exists
            if "temp_path" in locals() and temp_path.exists():
                temp_path.unlink()
            raise

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
