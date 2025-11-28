"""
Session and conversation command handlers.

Handles: /session, /conversations, /new, /load, /compact, /delete, /reset
"""

import logging

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning

logger = logging.getLogger(__name__)


class SessionCommandHandler:
    """Handles session and conversation-related slash commands."""

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def handle_session(self, args: list) -> bool:
        """Show session information."""
        try:
            if args and args[0] == 'list':
                sessions = self.repl.session_manager.list_sessions(limit=5)
                table = Table(title="Recent Sessions")
                table.add_column("Session ID", style="cyan")
                table.add_column("Started", style="green")
                table.add_column("Queries", style="magenta")

                for s in sessions:
                    table.add_row(
                        s.get('id', 'N/A'),
                        s.get('started_at', 'N/A'),
                        str(s.get('total_queries', 0))
                    )

                console.print(table)
            else:
                console.print(f"Current session: {self.repl.session_manager.current_session_id}")
                console.print("Use: /session list")

        except Exception as e:
            print_error(f"Failed to get session info: {e}")

        return True

    def handle_conversations(self, args: list) -> bool:
        """Handle /conversations command to list all conversations."""
        try:
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
                title = (conv.get('title') or 'Untitled')[:30]
                msg_count = str(conv.get('message_count', 0))
                tokens = str(conv.get('token_count', 0))
                updated = (conv.get('updated_at') or '')[:16]

                # Mark current conversation
                if conv_id == current_id:
                    conv_id = f"[bold]{conv_id}[/bold] *"

                table.add_row(conv_id, title, msg_count, tokens, updated)

            console.print(table)
            console.print("[dim]* = current conversation[/dim]")

        except Exception as e:
            print_error(f"Error listing conversations: {e}")
            console.print("[dim]Check database connection or try /new[/dim]")

        return True

    def handle_new(self, args: list) -> bool:
        """Handle /new command to start a new conversation."""
        title = ' '.join(args) if args else None
        try:
            conv = self.repl.conversation_manager.create_conversation(title=title)
        except Exception as e:
            logger.exception("Failed to create conversation: %s", e)
            print_error(f"Failed to create conversation: {e}")
            return True

        if not conv or not getattr(conv, 'id', None):
            logger.error("create_conversation returned invalid result: %r", conv)
            print_error("Failed to create conversation: invalid response")
            return True

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
        try:
            loaded = self.repl.conversation_manager.load_conversation(conv_id)
        except Exception as e:
            logger.exception("Failed to load conversation %s: %s", conv_id, e)
            print_error(f"Failed to load conversation: {e}")
            return True

        if loaded:
            try:
                conv = self.repl.conversation_manager.current_conversation
                print_success(f"Loaded conversation: {conv_id}")
                console.print(f"  Messages: {len(conv.messages)}")
                console.print(f"  Tokens: {conv.token_count}")
            except Exception as e:
                logger.exception(
                    "Failed to access conversation attributes for %s: %s", conv_id, e
                )
                print_error(f"Loaded conversation but failed to display details: {e}")
        else:
            print_error(f"Conversation not found: {conv_id}")

        return True

    def handle_compact(self, args: list) -> bool:
        """Handle /compact command to compact current conversation."""
        conv = self.repl.conversation_manager.current_conversation
        if not conv:
            print_error("No active conversation")
            return True

        try:
            original_conv_id = conv.id
            before_tokens = conv.token_count
            before_messages = len(conv.messages)
        except AttributeError as e:
            logger.error("Conversation object missing expected attributes: %s", e)
            print_error(f"Cannot compact: conversation object is malformed ({e})")
            return True

        # Compact by summarizing old messages
        try:
            with console.status("[cyan]Compacting conversation...[/cyan]", spinner="dots"):
                success = self.repl.conversation_manager.compact_conversation()

            if not success:
                # Compaction returned False - log and inform user
                logger.warning(
                    "Compaction returned False for conversation %s", original_conv_id
                )
                print_error("Compaction failed - conversation unchanged")
                return True

        except Exception as e:
            # Log full exception with stack trace
            logger.exception(
                "Failed to compact conversation %s: %s", original_conv_id, e
            )
            print_error(f"Compaction failed: {e}")

            # Attempt to restore/reload original conversation if state is inconsistent
            current_conv = self.repl.conversation_manager.current_conversation
            if current_conv is None or current_conv.id != original_conv_id:
                # State changed during failed compaction - try to reload original
                logger.info(
                    "Attempting to restore original conversation %s", original_conv_id
                )
                try:
                    self.repl.conversation_manager.load_conversation(original_conv_id)
                    logger.info("Successfully restored conversation %s", original_conv_id)
                except Exception as restore_err:
                    logger.exception(
                        "Failed to restore conversation %s: %s",
                        original_conv_id,
                        restore_err,
                    )
                    print_error(
                        "Warning: Could not restore original conversation. "
                        "Use /conversations to list available conversations."
                    )
            return True

        # Get updated conversation (may be new after compaction)
        conv = self.repl.conversation_manager.current_conversation
        if conv is None:
            print_warning("Conversation removed or compaction resulted in no active conversation")
            console.print(f"  Messages: {before_messages} → N/A")
            console.print(f"  Tokens: {before_tokens} → N/A")
            return True

        try:
            after_tokens = conv.token_count
            after_messages = len(conv.messages)
        except AttributeError as e:
            logger.error(
                "Compacted conversation object missing expected attributes: %s", e
            )
            print_error(f"Compaction completed but cannot display results: {e}")
            return True

        print_success("Conversation compacted")
        console.print(f"  Messages: {before_messages} → {after_messages}")
        console.print(f"  Tokens: {before_tokens} → {after_tokens}")
        delta = before_tokens - after_tokens
        if delta >= 0:
            console.print(f"  Saved: {delta} tokens")
        else:
            console.print(f"  Increased: {abs(delta)} tokens")

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

        try:
            if self.repl.conversation_manager.delete_conversation(conv_id):
                print_success(f"Conversation deleted: {conv_id}")
            else:
                print_error(f"Failed to delete conversation: {conv_id}")
        except Exception as e:
            logger.exception("Failed to delete conversation %s: %s", conv_id, e)
            print_error(f"Failed to delete conversation: {e}")

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
