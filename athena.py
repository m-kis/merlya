#!/usr/bin/env python3
"""
Athena - AI-Powered Infrastructure Orchestration
Smart entry point that handles configuration, dependencies, and initialization automatically.
"""
import sys
import os
from pathlib import Path
from rich.console import Console

console = Console()

def main():
    """Main entry point."""
    console.print("\n[bold cyan]🦉 Athena[/bold cyan]")
    console.print("[dim]AI-Powered Infrastructure Orchestration[/dim]\n")

    # 1. Add current directory to path to ensure athena_ai is importable
    root_dir = Path(__file__).parent.absolute()
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    # 2. Validate Configuration & Dependencies
    try:
        from athena_ai.utils.config_validator import ConfigValidator
        validator = ConfigValidator()
        
        if not validator.check_all():
            console.print("\n[yellow]⚠ System is not fully configured.[/yellow]")
            console.print("Starting auto-fix wizard...\n")
            
            if validator.fix_issues():
                console.print("\n[green]✓ Configuration fixed![/green]")
            else:
                console.print("\n[red]✗ Setup cancelled or failed.[/red]")
                sys.exit(1)
                
    except ImportError as e:
        console.print(f"[red]Critical Error: Could not import Athena components.[/red]")
        console.print(f"Error: {e}")
        console.print("Ensure you are running this from the project root.")
        sys.exit(1)

    # 3. Launch REPL
    try:
        from athena_ai.repl import start_repl
        
        # Determine environment (default to dev if not set)
        env = os.getenv("ATHENA_ENV", "dev")
        
        start_repl(env=env)
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Goodbye! 👋[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Fatal Error: {e}[/red]")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
