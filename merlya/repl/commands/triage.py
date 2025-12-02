"""
Triage command handler.
"""
from merlya.repl.ui import console, print_error, print_success, print_warning
from merlya.triage import classify_priority, describe_behavior, Intent, Priority

def handle_triage_command(repl, args):
    """Handle /triage command to test priority classification."""

    if not args:
        console.print("[yellow]Usage:[/yellow] /triage <query>")
        console.print("Example: /triage production database is down")
        return True

    query = ' '.join(args)
    result = classify_priority(query)

    console.print("\n[bold]🎯 Triage Analysis[/bold]")
    console.print(f"  Query: [dim]{query}[/dim]")
    console.print(f"  Priority: [{result.priority.color}]{result.priority.label}[/{result.priority.color}]")
    console.print(f"  🖥️ Environment: {result.environment or 'unknown'}")
    console.print(f"  📊 Impact: {result.impact or 'unknown'}")
    console.print(f"  ⚙️ Service: {result.service or 'unknown'}")
    console.print("\n[bold]📋 Behavior Profile:[/bold]")
    console.print(describe_behavior(result.priority))

    return True

def handle_feedback_command(repl, args):
    """Handle /feedback command to correct triage classification."""

    if not args:
        _show_feedback_help()
        return True

    # Parse arguments: /feedback <intent> <priority> [query]
    # or: /feedback --last <intent> <priority>
    use_last = '--last' in args
    if use_last:
        args = [a for a in args if a != '--last']

    if len(args) < 2:
        _show_feedback_help()
        return True

    intent_str = args[0].lower()
    priority_str = args[1].upper()
    query = ' '.join(args[2:]) if len(args) > 2 else None

    # Validate intent
    intent_map = {
        'query': Intent.QUERY,
        'action': Intent.ACTION,
        'analysis': Intent.ANALYSIS,
    }
    if intent_str not in intent_map:
        print_error(f"Invalid intent: {intent_str}")
        console.print("[dim]Valid intents: query, action, analysis[/dim]")
        return True

    # Validate priority
    if priority_str not in ('P0', 'P1', 'P2', 'P3'):
        print_error(f"Invalid priority: {priority_str}")
        console.print("[dim]Valid priorities: P0, P1, P2, P3[/dim]")
        return True

    intent = intent_map[intent_str]
    priority = Priority[priority_str]

    # Get query to correct
    if not query and use_last:
        # Use last query from intent parser
        if hasattr(repl.orchestrator, 'intent_parser') and repl.orchestrator.intent_parser._last_query:
            query = repl.orchestrator.intent_parser._last_query
        else:
            print_error("No previous query to correct. Use: /feedback <intent> <priority> <query>")
            return True

    if not query:
        print_error("Please provide a query to correct")
        _show_feedback_help()
        return True

    # Provide feedback
    try:
        success = repl.orchestrator.intent_parser.provide_feedback(
            query=query,
            correct_intent=intent,
            correct_priority=priority,
        )

        if success:
            print_success("Feedback recorded!")
            console.print(f"  Query: [dim]{query[:50]}{'...' if len(query) > 50 else ''}[/dim]")
            console.print(f"  Intent: [cyan]{intent.value}[/cyan]")
            console.print(f"  Priority: [{priority.color}]{priority.label}[/{priority.color}]")
            console.print("[dim]This correction will improve future classifications.[/dim]")
        else:
            print_warning("Could not store feedback (FalkorDB may not be available)")

    except Exception as e:
        print_error(f"Feedback failed: {e}")

    return True

def _show_feedback_help():
    """Show help for /feedback command."""
    console.print("[yellow]Usage:[/yellow]")
    console.print("  /feedback <intent> <priority> <query>  - Correct a specific query")
    console.print("  /feedback --last <intent> <priority>   - Correct last query")
    console.print()
    console.print("[yellow]Intents:[/yellow]")
    console.print("  [cyan]query[/cyan]    - Information request (list, show, what is)")
    console.print("  [cyan]action[/cyan]   - Execute/modify (restart, check, deploy)")
    console.print("  [cyan]analysis[/cyan] - Investigation (diagnose, why, troubleshoot)")
    console.print()
    console.print("[yellow]Priorities:[/yellow]")
    console.print("  [bold red]P0[/bold red] - CRITICAL (production down, data loss)")
    console.print("  [bold yellow]P1[/bold yellow] - URGENT (degraded, security issue)")
    console.print("  [cyan]P2[/cyan] - IMPORTANT (performance, warnings)")
    console.print("  [dim]P3[/dim] - NORMAL (maintenance, questions)")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print("  /feedback query P3 list my servers")
    console.print("  /feedback action P1 restart nginx on prod")
    console.print("  /feedback --last analysis P2")
