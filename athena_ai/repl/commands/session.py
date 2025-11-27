"""
Session and conversation command handlers.

Handles: /session, /conversations, /new, /load, /compact, /delete
"""

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning


class SessionCommandHandler:
    """Handles session and conversation-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def handle_session(self, args: list) -> bool:
        """Show session information."""
        try:
            if 'list' in args:
                sessions = self.repl.session_manager.list_sessions(limit=5)
                table = Table(title="Recent Sessions")
                table.add_column("Session ID", style="cyan")
                table.add_column("Started", style="green")
                table.add_column("Queries", style="magenta")

                for s in sessions:
                    table.add_row(s['id'], s['started_at'], str(s['total_queries']))

                console.print(table)
            else:
                console.print(f"Current session: {self.repl.session_manager.current_session_id}")
                console.print("Use: /session list")

        except Exception as e:
            print_error(f"Failed to get session info: {e}")

        return True

    def handle_conversations(self, args: list) -> bool:
        """Handle /conversations command to list all conversations."""
        conversations = self.repl.conversation_manager.list_conversations(limit=20)
        if not conversations:
            print_warning("No conversations found")
            console.print("[dim]Start chatting to create a conversation[/dim]")
            return True

        table = Table(title="Conversations")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="green")
        table.add_column("Messages", style="yellow")
        table.add_column("Tokens", style="magenta")
        table.add_column("Updated", style="dim")

        current_id = (
            self.repl.conversation_manager.current_conversation.id
            if self.repl.conversation_manager.current_conversation
            else None
        )

        for conv in conversations:
            conv_id = conv.get('id', conv.get('conversation_id', 'N/A'))
            title = conv.get('title', 'Untitled')[:30]
            msg_count = str(conv.get('message_count', 0))
            tokens = str(conv.get('token_count', 0))
            updated = conv.get('updated_at', '')[:16]

            # Mark current conversation
            if conv_id == current_id:
                conv_id = f"[bold]{conv_id}[/bold] *"

            table.add_row(conv_id, title, msg_count, tokens, updated)

        console.print(table)
        console.print("[dim]* = current conversation[/dim]")
        return True

    def handle_new(self, args: list) -> bool:
        """Handle /new command to start a new conversation."""
        title = ' '.join(args) if args else None
        conv = self.repl.conversation_manager.create_conversation(title=title)
        print_success(f"New conversation started: {conv.id}")
        if title:
            console.print(f"  Title: {title}")
        return True

    def handle_load(self, args: list) -> bool:
        """Handle /load command to load a conversation."""
        if not args:
            print_error("Usage: /load <conversation_id>")
            return True

        conv_id = args[0]
        if self.repl.conversation_manager.load_conversation(conv_id):
            conv = self.repl.conversation_manager.current_conversation
            print_success(f"Loaded conversation: {conv_id}")
            console.print(f"  Messages: {len(conv.messages)}")
            console.print(f"  Tokens: {conv.token_count}")
        else:
            print_error(f"Conversation not found: {conv_id}")

        return True

    def handle_compact(self, args: list) -> bool:
        """Handle /compact command to compact current conversation."""
        conv = self.repl.conversation_manager.current_conversation
        if not conv:
            print_error("No active conversation")
            return True

        before_tokens = conv.token_count
        before_messages = len(conv.messages)

        # Compact by summarizing old messages
        with console.status("[cyan]Compacting conversation...[/cyan]", spinner="dots"):
            self.repl.conversation_manager.compact_conversation()

        after_tokens = conv.token_count
        after_messages = len(conv.messages)

        print_success("Conversation compacted")
        console.print(f"  Messages: {before_messages} → {after_messages}")
        console.print(f"  Tokens: {before_tokens} → {after_tokens}")
        console.print(f"  Saved: {before_tokens - after_tokens} tokens")

        return True

    def handle_delete(self, args: list) -> bool:
        """Handle /delete command to delete a conversation."""
        if not args:
            print_error("Usage: /delete <conversation_id>")
            return True

        conv_id = args[0]

        # Confirmation
        try:
            confirm = input(f"Delete conversation {conv_id}? (y/N): ").strip().lower()
            if confirm != 'y':
                print_warning("Cancelled")
                return True
        except (KeyboardInterrupt, EOFError):
            print_warning("Cancelled")
            return True

        if self.repl.conversation_manager.delete_conversation(conv_id):
            print_success(f"Conversation deleted: {conv_id}")
        else:
            print_error(f"Failed to delete conversation: {conv_id}")

        return True

    def handle_reset(self) -> bool:
        """Reset Ag2 agents memory."""
        try:
            if hasattr(self.repl.orchestrator, 'reset_agents'):
                self.repl.orchestrator.reset_agents()
                print_success("Agents memory reset successfully")
            elif hasattr(self.repl.orchestrator, 'reload_agents'):
                self.repl.orchestrator.reload_agents()
                print_success("Agents reloaded (memory cleared)")
            else:
                print_warning("Agent reset not available for current orchestrator")
        except Exception as e:
            print_error(f"Failed to reset agents: {e}")
        return True
