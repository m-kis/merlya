"""
Graceful fallback helper for parser failures.

Provides interactive user prompts when automatic parsing fails.
"""
from typing import List, Optional, Tuple

from merlya.repl.ui import console, print_error, print_warning


def prompt_fallback_action(
    format_type: str,
    error_message: str,
    available_formats: List[str],
) -> Tuple[Optional[str], bool]:
    """Prompt user for action when parsing fails.

    Args:
        format_type: Detected format that failed to parse
        error_message: Error message from parser
        available_formats: List of manually-specifiable formats

    Returns:
        Tuple of (selected_format, should_skip_errors)
        - selected_format: User-selected format to retry with, or None to abort
        - should_skip_errors: Whether to skip non-parseable lines

    Raises:
        KeyboardInterrupt: If user cancels (Ctrl+C)
    """
    console.print("\n[bold red]❌ Parsing Failed[/bold red]")
    console.print(f"[yellow]Format detected:[/yellow] {format_type}")
    console.print(f"[yellow]Error:[/yellow] {error_message}\n")

    console.print("[bold]What would you like to do?[/bold]\n")
    console.print("1. [cyan]Specify format manually[/cyan] (csv, json, yaml, ini, etc.)")
    console.print("2. [cyan]Skip unparseable lines[/cyan] (parse what's possible)")
    console.print("3. [cyan]Export sample for debugging[/cyan]")
    console.print("4. [red]Abort import[/red]\n")

    try:
        choice = input("Choose an option (1-4): ").strip()

        if choice == "1":
            # Manual format selection
            console.print("\n[bold]Available formats:[/bold]")
            for i, fmt in enumerate(available_formats, 1):
                console.print(f"  {i}. {fmt}")

            fmt_choice = input(f"\nSelect format (1-{len(available_formats)}): ").strip()
            try:
                fmt_idx = int(fmt_choice) - 1
                if 0 <= fmt_idx < len(available_formats):
                    selected_format = available_formats[fmt_idx]
                    console.print(f"[green]✓[/green] Retrying with format: {selected_format}")
                    return selected_format, False
                else:
                    print_error("Invalid selection")
                    return None, False
            except ValueError:
                print_error("Invalid input")
                return None, False

        elif choice == "2":
            # Skip errors and parse what's possible
            console.print("[yellow]⚠️  Will parse valid entries and skip errors[/yellow]")
            return None, True

        elif choice == "3":
            # Export sample for debugging
            console.print("\n[cyan]Sample export feature:[/cyan]")
            console.print("To export a sample for debugging:")
            console.print("1. Take first 100 lines: head -100 yourfile.txt > sample.txt")
            console.print("2. Share sample.txt for format analysis")
            console.print("3. Or try converting to standard format (CSV, JSON, YAML)\n")
            return None, False

        elif choice == "4":
            # Abort
            print_warning("Import aborted by user")
            return None, False

        else:
            print_error("Invalid choice")
            return None, False

    except (KeyboardInterrupt, EOFError):
        print_warning("\nImport cancelled")
        return None, False


def suggest_format_conversion(content: str, detected_format: str) -> None:
    """Suggest how to convert content to standard format.

    Args:
        content: File content that failed to parse
        detected_format: Format that was auto-detected
    """
    console.print("\n[bold cyan]💡 Conversion Suggestions:[/bold cyan]\n")

    if detected_format == "txt":
        console.print("[yellow]TXT format detected but parsing failed.[/yellow]")
        console.print("\nTo convert to CSV:")
        console.print("1. Open file in text editor")
        console.print("2. Ensure first line has headers: hostname,ip_address,environment")
        console.print("3. Ensure data rows are comma-separated")
        console.print("4. Save and retry import\n")

    elif detected_format == "unknown":
        console.print("[yellow]Unrecognized format.[/yellow]")
        console.print("\nRecommended formats:")
        console.print("• CSV: hostname,ip_address,environment")
        console.print("• JSON: [{\"hostname\": \"...\", \"ip_address\": \"...\"}]")
        console.print("• YAML: List of hosts with fields")
        console.print("• /etc/hosts: IP hostname [aliases...]")
        console.print("\nYou can also use AI parsing (requires LLM):")
        console.print("  export MERLYA_ENABLE_LLM_FALLBACK=true")
        console.print("  export MERLYA_LLM_COMPLIANCE_ACKNOWLEDGED=true\n")

    else:
        console.print(f"[yellow]Format '{detected_format}' detected but contains errors.[/yellow]")
        console.print("\nValidation tips:")
        console.print("• Check for missing required fields (hostname)")
        console.print("• Verify data types (IP addresses, port numbers)")
        console.print("• Look for special characters that need escaping")
        console.print("• Ensure consistent format across all lines\n")


def prompt_retry_with_llm() -> bool:
    """Ask user if they want to retry with LLM parsing.

    Returns:
        True if user wants to retry with LLM, False otherwise
    """
    try:
        console.print("\n[bold cyan]🤖 AI-Powered Parsing Available[/bold cyan]")
        console.print("[yellow]Standard parsers failed, but AI can analyze non-standard formats.[/yellow]\n")
        console.print("[bold]Would you like to try AI parsing?[/bold]")
        console.print("  • Requires: LLM configuration (OpenAI, Anthropic, etc.)")
        console.print("  • Privacy: Content sent to LLM provider")
        console.print("  • Accuracy: Best effort, review results carefully\n")

        choice = input("Try AI parsing? (y/N): ").strip().lower()
        return choice == "y"

    except (KeyboardInterrupt, EOFError):
        print_warning("\nCancelled")
        return False
