import os
import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm

console = Console()

class ConfigValidator:
    """
    Validates configuration and dependencies for Athena.
    """

    def __init__(self, env: str = "dev"):
        self.env = env
        self.config_dir = Path.home() / ".athena"
        self.env_file = self.config_dir / ".env"

    def check_all(self) -> bool:
        """
        Run all checks. Returns True if everything is ready, False otherwise.
        """
        console.print("[bold]🔍 Checking System Readiness...[/bold]")

        checks = [
            self.check_config_dir,
            self.check_env_file,
            self.check_api_keys,
            self.check_dependencies
        ]

        for check in checks:
            if not check():
                # We stop at the first failure to guide the user step-by-step
                # or we could continue to show all issues.
                # For a "wizard" feel, stopping might be better to fix one thing at a time.
                # But let's show all issues for now, or maybe return False immediately if critical?
                # Let's return False immediately to trigger the fix flow for that specific issue.
                return False

        console.print("[green]✓ System is ready![/green]")
        return True

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
        """Load environment variables from .env file."""
        if self.env_file.exists():
            with open(self.env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ[key] = value

    def check_api_keys(self) -> bool:
        """Check if essential API keys are present."""
        # Check for at least one provider
        providers = ["OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_MODEL"]

        # If OLLAMA_MODEL is set, we assume Ollama is used and key is not strictly required
        # ATHENA_PROVIDER can also be checked for provider configuration

        has_key = any(os.getenv(k) for k in providers)

        if not has_key:
            console.print("[yellow]⚠ No AI Provider configuration found.[/yellow]")
            return False

        return True

    def check_dependencies(self) -> bool:
        """Check for optional but recommended dependencies."""
        try:
            import autogen
        except ImportError:
            console.print("[yellow]⚠ 'pyautogen' is not installed.[/yellow]")
            console.print("[dim]It is required for the Multi-Agent system.[/dim]")
            return False

        return True

    def fix_issues(self) -> bool:
        """
        Interactive wizard to fix issues.
        """
        console.print("\n[bold cyan]🛠  Auto-Fix Wizard[/bold cyan]")

        # 1. Config Dir
        if not self.config_dir.exists():
            if Confirm.ask(f"Create config directory at {self.config_dir}?"):
                self.config_dir.mkdir(parents=True, exist_ok=True)
                console.print("[green]✓ Directory created[/green]")
            else:
                return False

        # 2. Env File & API Keys (Combined Init)
        if not self.env_file.exists() or not self.check_api_keys():
            if Confirm.ask("Initialize configuration now?"):
                from athena_ai.cli import init_interactive
                init_interactive()
                # Reload env after init
                self._load_env()
            else:
                return False

        # 3. Dependencies
        try:
            import autogen
        except ImportError:
            if Confirm.ask("Install 'pyautogen' now?"):
                import subprocess
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyautogen"])
                    console.print("[green]✓ pyautogen installed[/green]")
                except subprocess.CalledProcessError:
                    console.print("[red]✗ Failed to install pyautogen[/red]")
                    return False
            else:
                console.print("[yellow]Skipping dependency installation. Ag2 features will be disabled.[/yellow]")
                # We allow proceeding but warn

        return True
