"""
Command Loader for Athena.

Loads slash commands from markdown files with YAML frontmatter.
Follows Claude Code's extensible command pattern.

Command locations (in priority order):
1. Built-in: athena_ai/commands/builtin/*.md
2. User: ~/.athena/commands/*.md
3. Project: .athena/commands/*.md (current directory)

Example command file (~/.athena/commands/incident.md):

    ---
    name: incident
    description: Start incident response workflow
    aliases: [inc, ir]
    ---

    # Incident Response for {{$1}}

    Perform the following steps:
    1. Check status of {{$1}}
    2. Gather recent logs
    3. Diagnose root cause
    4. Suggest mitigation

    Priority: {{$2|P2}}
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import re
import yaml

from athena_ai.utils.logger import logger


@dataclass
class CommandDef:
    """
    Definition of a slash command.

    Attributes:
        name: Command name (without /)
        description: Short description for /help
        prompt_template: Markdown template with {{$N}} placeholders
        aliases: Alternative names for the command
        source: File path where command was loaded from
    """
    name: str
    description: str
    prompt_template: str
    aliases: List[str] = field(default_factory=list)
    source: str = ""


class CommandLoader:
    """
    Singleton loader for extensible slash commands.

    Loads commands from markdown files with YAML frontmatter.
    Commands from later sources override earlier ones (project > user > builtin).
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._commands: Dict[str, CommandDef] = {}
            cls._instance._aliases: Dict[str, str] = {}
            cls._instance._loaded = False
        return cls._instance

    def load_all(self, force: bool = False):
        """
        Load commands from all sources.

        Args:
            force: Reload even if already loaded
        """
        if self._loaded and not force:
            return

        self._commands.clear()
        self._aliases.clear()

        # Load in priority order (later overrides earlier)
        sources = [
            Path(__file__).parent / "builtin",  # Built-in commands
            Path.home() / ".athena" / "commands",  # User commands
            Path.cwd() / ".athena" / "commands",  # Project commands
        ]

        for source_dir in sources:
            if source_dir.exists() and source_dir.is_dir():
                self._load_directory(source_dir)

        self._loaded = True
        logger.debug(f"CommandLoader: loaded {len(self._commands)} commands")

    def _load_directory(self, path: Path):
        """Load all .md files from a directory."""
        for md_file in path.glob("*.md"):
            try:
                cmd = self._parse_markdown(md_file)
                if cmd:
                    self._register_command(cmd)
            except Exception as e:
                logger.warning(f"Failed to load command from {md_file}: {e}")

    def _parse_markdown(self, path: Path) -> Optional[CommandDef]:
        """
        Parse a markdown file with YAML frontmatter.

        Format:
            ---
            name: command-name
            description: Short description
            aliases: [alias1, alias2]
            ---

            Template content with {{$1}}, {{$2}}, {{$@}} placeholders
        """
        content = path.read_text(encoding="utf-8")

        # Parse YAML frontmatter
        frontmatter_match = re.match(
            r'^---\s*\n(.*?)\n---\s*\n(.*)$',
            content,
            re.DOTALL
        )

        if frontmatter_match:
            try:
                meta = yaml.safe_load(frontmatter_match.group(1))
                template = frontmatter_match.group(2).strip()
            except yaml.YAMLError as e:
                logger.warning(f"Invalid YAML in {path}: {e}")
                return None
        else:
            # No frontmatter - use filename as name
            meta = {"name": path.stem}
            template = content.strip()

        if not meta:
            meta = {}

        return CommandDef(
            name=meta.get("name", path.stem),
            description=meta.get("description", f"Custom command: {path.stem}"),
            prompt_template=template,
            aliases=meta.get("aliases", []),
            source=str(path)
        )

    def _register_command(self, cmd: CommandDef):
        """Register command and its aliases."""
        self._commands[cmd.name] = cmd

        # Register aliases
        for alias in cmd.aliases:
            self._aliases[alias] = cmd.name

        logger.debug(f"Registered command: /{cmd.name} (aliases: {cmd.aliases})")

    def get(self, name: str) -> Optional[CommandDef]:
        """
        Get command by name or alias.

        Args:
            name: Command name (without /)

        Returns:
            CommandDef or None if not found
        """
        if not self._loaded:
            self.load_all()

        # Direct lookup
        if name in self._commands:
            return self._commands[name]

        # Alias lookup
        if name in self._aliases:
            return self._commands.get(self._aliases[name])

        return None

    def expand(self, cmd: CommandDef, args: List[str]) -> str:
        """
        Expand command template with arguments.

        Placeholders:
        - {{$1}}, {{$2}}, ... : Positional arguments
        - {{$@}} : All arguments joined
        - {{$N|default}} : With default value

        Args:
            cmd: Command definition
            args: Arguments passed to command

        Returns:
            Expanded prompt string
        """
        template = cmd.prompt_template

        # Replace positional args with defaults: {{$1|default}}
        def replace_with_default(match):
            idx = int(match.group(1)) - 1
            default = match.group(2) if match.group(2) else ""
            return args[idx] if idx < len(args) else default

        template = re.sub(
            r'\{\{\$(\d+)\|?([^}]*)\}\}',
            replace_with_default,
            template
        )

        # Replace {{$@}} with all args
        template = template.replace("{{$@}}", " ".join(args))

        return template

    def list_commands(self) -> Dict[str, str]:
        """
        List all available commands with descriptions.

        Returns:
            Dict of {name: description}
        """
        if not self._loaded:
            self.load_all()

        return {
            name: cmd.description
            for name, cmd in sorted(self._commands.items())
        }

    def reload(self):
        """Force reload all commands."""
        self.load_all(force=True)


# Singleton accessor
_command_loader: Optional[CommandLoader] = None


def get_command_loader() -> CommandLoader:
    """Get the global CommandLoader instance."""
    global _command_loader
    if _command_loader is None:
        _command_loader = CommandLoader()
        _command_loader.load_all()
    return _command_loader
