"""
Language command handler.
"""
from merlya.repl.ui import console, print_error, print_success

def handle_language_command(repl, args):
    """Handle /language command to change language preference."""
    if not args:
        current = repl.config.language or 'en'
        console.print(f"Current language: [cyan]{current}[/cyan]")
        console.print("Usage: /language <en|fr>")
        return True

    lang = args[0].lower()
    if lang in ['en', 'english']:
        repl.config.language = 'en'
        print_success("Language set to English")
    elif lang in ['fr', 'french', 'français']:
        repl.config.language = 'fr'
        print_success("Langue définie sur Français")
    else:
        print_error("Supported languages: en, fr")

    return True
