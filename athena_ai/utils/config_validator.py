"""
Configuration Validator for Athena.

Validates configuration and dependencies before starting.
Performs comprehensive checks for all critical components.
"""
import os
import sys
from pathlib import Path
from typing import Dict

from rich.console import Console
from rich.prompt import Confirm

console = Console()


class ConfigValidator:
    """
    Validates configuration and dependencies for Athena.

    Checks:
    - Configuration directory and files
    - AI provider configuration
    - Core dependencies (autogen)
    - Optional dependencies (sentence-transformers for AI-powered features)
    - Database connectivity (if configured)
    """

    def __init__(self, env: str = "dev"):
        self.env = env
        self.config_dir = Path.home() / ".athena"
        self.env_file = self.config_dir / ".env"
        self._status: Dict[str, bool] = {}

    def check_all(self) -> bool:
        """
        Run all checks. Returns True if everything is ready, False otherwise.
        """
        console.print("[bold]🔍 Checking System Readiness...[/bold]")

        # Critical checks (must pass)
        critical_checks = [
            ("Config directory", self.check_config_dir),
            ("Environment file", self.check_env_file),
            ("AI provider", self.check_provider),
            ("Core dependencies", self.check_dependencies),
        ]

        # Optional checks (warn but don't fail)
        optional_checks = [
            ("Embeddings (AI features)", self.check_embeddings),
            ("Web Search (DuckDuckGo)", self.check_web_search),
            ("Database", self.check_database),
        ]

        all_critical_passed = True
        for name, check in critical_checks:
            result = check()
            self._status[name] = result
            if not result:
                all_critical_passed = False

        # Run optional checks (don't fail startup)
        for name, check in optional_checks:
            result = check()
            self._status[name] = result

        if all_critical_passed:
            console.print("[green]✅ System is ready![/green]")
        return all_critical_passed

    def check_config_dir(self) -> bool:
        """Check if config directory exists."""
        if not self.config_dir.exists():
            console.print(f"[yellow]⚠ Config directory not found: {self.config_dir}[/yellow]")
            return False
        return True

    def check_env_file(self) -> bool:
        """Check if .env file exists and load it."""
        if not self.env_file.exists():
            console.print(f"[yellow]⚠ Configuration file not found: {self.env_file}[/yellow]")
            return False

        # Load env vars
        self._load_env()
        return True

    def _load_env(self):
        """Load environment variables from .env file (API keys only)."""
        if self.env_file.exists():
            # ✅ Variables to IGNORE (config, not secrets)
            IGNORED_VARS = {
                "ATHENA_PROVIDER", "OPENROUTER_MODEL",
                "ANTHROPIC_MODEL", "OPENAI_MODEL", "OLLAMA_MODEL"
            }

            with open(self.env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        # ✅ Skip config variables (only load API keys)
                        if key not in IGNORED_VARS:
                            os.environ[key] = value

    def check_provider(self) -> bool:
        """
        Check if a valid AI provider is configured.

        Respects the chosen provider - if one is configured, don't require others.
        """
        provider = os.getenv("ATHENA_PROVIDER", "").lower()

        # Check based on configured provider
        if provider == "ollama":
            # Ollama: just need model name, no API key
            if os.getenv("OLLAMA_MODEL"):
                return True
            console.print("[yellow]⚠ OLLAMA_MODEL not set.[/yellow]")
            return False

        elif provider == "openrouter":
            if os.getenv("OPENROUTER_API_KEY"):
                return True
            console.print("[yellow]⚠ OPENROUTER_API_KEY not set.[/yellow]")
            return False

        elif provider == "anthropic":
            if os.getenv("ANTHROPIC_API_KEY"):
                return True
            console.print("[yellow]⚠ ANTHROPIC_API_KEY not set.[/yellow]")
            return False

        elif provider == "openai":
            if os.getenv("OPENAI_API_KEY"):
                return True
            console.print("[yellow]⚠ OPENAI_API_KEY not set.[/yellow]")
            return False

        # No provider specified - check if any key exists
        has_config = any([
            os.getenv("OLLAMA_MODEL"),
            os.getenv("OPENROUTER_API_KEY"),
            os.getenv("ANTHROPIC_API_KEY"),
            os.getenv("OPENAI_API_KEY"),
        ])

        if not has_config:
            console.print("[yellow]⚠ No AI Provider configuration found.[/yellow]")
            return False

        return True

    def check_dependencies(self) -> bool:
        """Check for core dependencies (autogen)."""
        # Check for new autogen-agentchat API (0.7+)
        try:
            from autogen_agentchat.agents import AssistantAgent as _  # noqa: F401
            return True
        except ImportError:
            pass

        # Fallback: check for old pyautogen API (0.2.x)
        try:
            import autogen  # noqa: F401
            from autogen import AssistantAgent as _Agent  # noqa: F401
            return True
        except ImportError:
            pass

        console.print("[yellow]⚠ 'autogen-agentchat' is not installed.[/yellow]")
        console.print("[dim]It is required for the Multi-Agent system.[/dim]")
        return False

    def check_embeddings(self) -> bool:
        """
        Check if sentence-transformers is available for AI-powered features.

        This is optional - the system falls back to heuristics if unavailable.
        """
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
            return True
        except ImportError:
            console.print("[dim]ℹ️  sentence-transformers not installed (AI features will use heuristic fallback)[/dim]")
            console.print("[dim]   Install with: pip install 'athena-ai-ops[smart-triage]'[/dim]")
            return False

    def check_web_search(self) -> bool:
        """
        Check if DuckDuckGo Search is available for web search features.

        This is optional - web search tools will be disabled if unavailable.
        """
        try:
            from duckduckgo_search import DDGS  # noqa: F401
            return True
        except ImportError:
            pass

        # Fallback: check for ddgs alias
        try:
            from ddgs import DDGS  # noqa: F401
            return True
        except ImportError:
            pass

        console.print("[dim]ℹ️  duckduckgo-search not installed (web search disabled)[/dim]")
        console.print("[dim]   Install with: pip install 'athena-ai-ops[knowledge]'[/dim]")
        return False

    def check_database(self) -> bool:
        """
        Check if database is available (FalkorDB for knowledge graph).

        This is optional - the system works without persistent storage.
        """
        # Check if FalkorDB is configured
        falkor_host = os.getenv("FALKORDB_HOST")
        if not falkor_host:
            # Not configured, skip silently
            return False

        try:
            from athena_ai.knowledge.falkordb_client import get_falkordb_client
            client = get_falkordb_client()
            return client.is_connected if client else False
        except Exception:
            console.print("[dim]ℹ️ Database not available (knowledge persistence disabled)[/dim]")
            return False

    def get_status(self) -> Dict[str, bool]:
        """
        Get status of all checks.

        Returns:
            Dict mapping check name to pass/fail status
        """
        if not self._status:
            # Run checks if not already done
            self.check_all()
        return self._status.copy()

    def fix_issues(self) -> bool:
        """
        Interactive wizard to fix issues.
        """
        console.print("\n[bold cyan]🛠  Auto-Fix Wizard[/bold cyan]")

        # 1. Config Dir
        if not self.config_dir.exists():
            if Confirm.ask(f"Create config directory at {self.config_dir}?"):
                self.config_dir.mkdir(parents=True, exist_ok=True)
                console.print("[green]✅ Directory created[/green]")
            else:
                return False

        # 2. Env File & Provider Config (Combined Init)
        if not self.env_file.exists() or not self.check_provider():
            if Confirm.ask("Initialize configuration now?"):
                from athena_ai.cli import init_interactive
                init_interactive()
                # Reload env after init
                self._load_env()
            else:
                return False

        # 3. Dependencies
        if not self.check_dependencies():
            if Confirm.ask("Install 'pyautogen' and 'autogen-ext[openai]' now?"):
                import subprocess
                try:
                    subprocess.check_call([
                        sys.executable, "-m", "pip", "install",
                        "pyautogen", "autogen-ext[openai]"
                    ])
                    console.print("[green]✅ autogen packages installed[/green]")
                except subprocess.CalledProcessError:
                    console.print("[red]❌ Failed to install autogen packages[/red]")
                    return False
            else:
                console.print("[yellow]Skipping dependency installation. Multi-agent features will be disabled.[/yellow]")
                # We allow proceeding but warn

        console.print("\n[green]✅ Configuration fixed![/green]")
        return True


# Convenience function
def validate_config(env: str = "dev", auto_fix: bool = True) -> bool:
    """
    Validate configuration and optionally fix issues.

    Args:
        env: Environment name
        auto_fix: If True, offer to fix issues interactively

    Returns:
        True if configuration is valid (or was fixed)
    """
    validator = ConfigValidator(env)

    if validator.check_all():
        return True

    if auto_fix:
        return validator.fix_issues()

    return False
