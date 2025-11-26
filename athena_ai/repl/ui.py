"""
UI components for Athena REPL.
Handles console output, messages, and formatting.
"""
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console()

# UI translations
MESSAGES = {
    'en': {
        'welcome_title': 'Welcome',
        'welcome_header': '🚀 Athena AI Interactive Mode',
        'welcome_env': 'Environment',
        'welcome_session': 'Session',
        'welcome_intro': 'Type your questions naturally or use slash commands:',
        'welcome_help': 'Show commands',
        'welcome_scan': 'Scan infrastructure',
        'welcome_exit': 'Exit',
        'welcome_start': 'Start by asking me anything about your infrastructure!',
        'processing': 'Processing',
        'error': 'Error',
    },
    'fr': {
        'welcome_title': 'Bienvenue',
        'welcome_header': '🚀 Athena AI Mode Interactif',
        'welcome_env': 'Environnement',
        'welcome_session': 'Session',
        'welcome_intro': 'Posez vos questions naturellement ou utilisez les commandes slash :',
        'welcome_help': 'Afficher les commandes',
        'welcome_scan': 'Scanner l\'infrastructure',
        'welcome_exit': 'Quitter',
        'welcome_start': 'Commencez par me poser n\'importe quelle question sur votre infrastructure !',
        'processing': 'Traitement en cours',
        'error': 'Erreur',
    }
}

def show_welcome(env: str, session_id: str, language: str = 'en', conversation_info: str = ""):
    """Show welcome message."""
    msg = MESSAGES.get(language, MESSAGES['en'])

    welcome = f"""
# {msg['welcome_header']}

**{msg['welcome_env']}**: {env}
**{msg['welcome_session']}**: {session_id}
{conversation_info}
{msg['welcome_intro']}
- `/help` - {msg['welcome_help']}
- `/conversations` - List all conversations
- `/new [title]` - Start new conversation
- `/scan` - {msg['welcome_scan']}
- `/exit` - {msg['welcome_exit']}

{msg['welcome_start']}
"""
    console.print(Panel(Markdown(welcome), title=msg['welcome_title'], border_style="cyan"))

    # Warning banner - experimental software
    console.print()
    console.print(Panel(
        "[bold yellow]⚠️  EXPERIMENTAL SOFTWARE[/bold yellow]\n\n"
        "[yellow]This tool is in early development. Use for debugging/testing only, NOT production.[/yellow]\n\n"
        "[bold]Tips for best results:[/bold]\n"
        "• Be specific in your requests\n"
        "• Specify the target server name or ip if possible \n"
        "• Provide context (service name, error message, etc.)\n\n"
        "[dim]Issues? → https://github.com/m-kis/athena/issues[/dim]",
        title="⚠️  Warning",
        border_style="yellow",
    ))

def print_markdown(text: str):
    """Print markdown text."""
    console.print(Markdown(text))

def print_message(text: str, style: str = None):
    """Print a styled message."""
    if style:
        console.print(f"[{style}]{text}[/{style}]")
    else:
        console.print(text)

def print_error(text: str):
    """Print an error message."""
    console.print(f"[red]Error: {text}[/red]")

def print_success(text: str):
    """Print a success message."""
    console.print(f"[green]✓ {text}[/green]")

def print_warning(text: str):
    """Print a warning message."""
    console.print(f"[yellow]⚠ {text}[/yellow]")
