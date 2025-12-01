"""
Session and conversation command handlers.

Handles: /session, /conversations, /new, /load, /compact, /delete, /reset
"""

import logging
import re
from typing import TYPE_CHECKING, Optional

from rich.table import Table

from athena_ai.repl.ui import console, print_error, print_success, print_warning

if TYPE_CHECKING:
    from athena_ai.repl import AthenaREPL

logger = logging.getLogger(__name__)

# Regex pattern for valid conversation IDs (alphanumeric, underscores, hyphens)
CONVERSATION_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')


class SessionCommandHandler:
    """Handles session and conversation-related slash commands."""

    # Display configuration constants
    DEFAULT_CONVERSATION_LIMIT = 20
    MAX_TITLE_LENGTH = 40
    TIMESTAMP_DISPLAY_LENGTH = 16
    PREVIEW_MESSAGE_COUNT = 3
    MAX_CONTENT_PREVIEW_LENGTH = 200
    MAX_CONVERSATION_ID_LENGTH = 255

    def __init__(self, repl: 'AthenaREPL') -> None:
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def _validate_conversation_id(self, conv_id: str) -> tuple[bool, Optional[str]]:
        """
        Validate conversation ID format and safety.

        Args:
            conv_id: The conversation ID to validate.

        Returns:
            Tuple of (is_valid, error_message). If valid, error_message is None.
        """
        if not conv_id or not isinstance(conv_id, str):
            return False, "Conversation ID cannot be empty"

        if len(conv_id) > self.MAX_CONVERSATION_ID_LENGTH:
            return False, f"Conversation ID too long (max {self.MAX_CONVERSATION_ID_LENGTH} chars)"

        # Prevent path traversal
        if '..' in conv_id or '/' in conv_id or '\\' in conv_id:
            return False, "Conversation ID contains invalid characters (path traversal detected)"

        # Enforce expected format
        if not CONVERSATION_ID_PATTERN.match(conv_id):
            return False, "Conversation ID must contain only alphanumeric characters, underscores, and hyphens"

        return True, None

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
        """
        Handle /conversations command with subcommands.

        Args:
            args: List of command arguments. First element is subcommand,
                  remaining elements are subcommand-specific arguments.
                  Empty list defaults to 'list' subcommand.

        Returns:
            bool: Always returns True to indicate command was handled.

        Usage:
            /conversations [list]       - List recent conversations (default)
            /conversations check <id>   - Show details of a conversation
            /conversations set <id>     - Switch to a conversation
            /conversations help         - Show usage help
        """
        try:
            if not args:
                return self._handle_conversations_list([])

            subcommand = args[0].lower()
            sub_args = args[1:]

            if subcommand == 'list':
                return self._handle_conversations_list(sub_args)
            elif subcommand == 'check':
                return self._handle_conversations_check(sub_args)
            elif subcommand == 'set':
                return self._handle_conversations_set(sub_args)
            elif subcommand == 'help':
                return self._handle_conversations_help()
            else:
                print_error(f"Unknown subcommand: {subcommand}")
                return self._handle_conversations_help()

        except Exception as e:
            logger.exception("❌ Unexpected error in conversations command: %s", e)
            print_error(f"Unexpected error: {e}")
            return True

    def _handle_conversations_list(self, args: list) -> bool:
        """List conversations with enhanced formatting."""
        try:
            limit = self.DEFAULT_CONVERSATION_LIMIT
            if args and args[0].isdigit():
                limit = int(args[0])

            conversations = self.repl.conversation_manager.list_conversations(limit=limit)
            if not conversations:
                print_warning("No conversations found")
                console.print("[dim]Start chatting to create a conversation[/dim]")
                return True

            table = Table(title=f"📋 Recent Conversations (Last {limit})")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Title", style="green")
            table.add_column("Msgs", style="yellow", justify="right")
            table.add_column("Tokens", style="magenta", justify="right")
            table.add_column("Updated", style="dim")

            current_id = (
                self.repl.conversation_manager.current_conversation.id
                if self.repl.conversation_manager.current_conversation
                else None
            )

            for conv in conversations:
                conv_id = conv.get('id', conv.get('conversation_id', 'N/A'))
                raw_title = conv.get('title') or 'Untitled'
                title = (
                    raw_title[:self.MAX_TITLE_LENGTH] + "..."
                    if len(raw_title) > self.MAX_TITLE_LENGTH
                    else raw_title
                )
                msg_count = str(conv.get('message_count', 0))
                tokens = str(conv.get('token_count', 0))
                # Safe string conversion for updated_at
                updated_raw = conv.get('updated_at') or ''
                updated = str(updated_raw)[:self.TIMESTAMP_DISPLAY_LENGTH]

                # Highlight current conversation
                id_display = conv_id
                if conv_id == current_id:
                    id_display = f"[bold reverse]{conv_id}[/bold reverse] [bold]*[/bold]"
                    title = f"[bold]{title}[/bold]"

                table.add_row(id_display, title, msg_count, tokens, updated)

            console.print(table)
            console.print("[dim]Use '/conversations check <id>' for details or '/conversations set <id>' to switch[/dim]")

        except Exception as e:
            print_error(f"Error listing conversations: {e}")
            logger.exception("❌ Error listing conversations")

        return True

    def _handle_conversations_check(self, args: list) -> bool:
        """Show details of a specific conversation without loading it."""
        if not args:
            print_error("Usage: /conversations check <conversation_id>")
            return True

        conv_id = args[0]

        # Validate conversation ID
        is_valid, error_msg = self._validate_conversation_id(conv_id)
        if not is_valid:
            print_error(f"Invalid conversation ID: {error_msg}")
            return True

        try:
            # Try to load conversation object directly from store to get full details + messages
            # We access the store via the history manager
            # This allows us to peek without changing the current session state
            conv = None
            try:
                if (
                    hasattr(self.repl.conversation_manager, 'history')
                    and hasattr(self.repl.conversation_manager.history, 'store')
                ):
                    conv = self.repl.conversation_manager.history.store.load_conversation(conv_id)
            except Exception as store_err:
                logger.warning("⚠️ Failed to load conversation from store: %s", store_err)
                conv = None

            if not conv:
                # Fallback to list search if store access fails or returns None
                conversations = self.repl.conversation_manager.list_conversations(limit=100)
                target = next((c for c in conversations if c.get('id') == conv_id), None)

                if not target:
                    print_warning(f"Conversation {conv_id} not found.")
                    return True

                # If found in list but not loaded, we only have metadata
                table = Table(title=f"🔍 Conversation Details: {conv_id}")
                table.add_column("Field", style="cyan")
                table.add_column("Value", style="white")

                table.add_row("ID", target.get('id', 'N/A'))
                table.add_row("Title", target.get('title', 'N/A'))
                table.add_row("Messages", str(target.get('message_count', 0)))
                table.add_row("Tokens", str(target.get('token_count', 0)))
                # Safe string conversion for updated_at
                updated_val = target.get('updated_at')
                table.add_row("Updated", str(updated_val) if updated_val else 'N/A')
                console.print(table)
                console.print("[dim]Full details not available (could not load from store)[/dim]")
                return True

            # Display full details
            table = Table(title=f"🔍 Conversation Details: {conv.id}")
            table.add_column("Field", style="cyan")
            table.add_column("Value", style="white")

            table.add_row("ID", str(conv.id))
            table.add_row("Title", str(conv.title or "Untitled"))
            table.add_row("Messages", str(len(conv.messages)))
            table.add_row("Tokens", str(conv.token_count))
            if hasattr(conv, 'created_at') and conv.created_at:
                table.add_row("Created", str(conv.created_at))
            if hasattr(conv, 'updated_at') and conv.updated_at:
                table.add_row("Updated", str(conv.updated_at))

            console.print(table)

            # Show preview of last few messages
            if conv.messages:
                console.print(f"\n[bold]📜 Recent History (Last {self.PREVIEW_MESSAGE_COUNT} Messages):[/bold]")
                for msg in conv.messages[-self.PREVIEW_MESSAGE_COUNT:]:
                    role_style = "green" if msg.role == "user" else "blue"
                    content = str(msg.content) if msg.content else ""
                    content_preview = (
                        content[:self.MAX_CONTENT_PREVIEW_LENGTH] + "..."
                        if len(content) > self.MAX_CONTENT_PREVIEW_LENGTH
                        else content
                    )
                    console.print(f"[{role_style}]{msg.role.upper()}[/{role_style}]: {content_preview}")
            else:
                console.print("\n[dim]No messages in this conversation[/dim]")

        except Exception as e:
            print_error(f"Error checking conversation: {e}")
            logger.exception("❌ Error checking conversation")

        return True

    def _handle_conversations_set(self, args: list) -> bool:
        """Switch to a specific conversation."""
        if not args:
            print_error("Usage: /conversations set <conversation_id>")
            return True

        return self.handle_load(args)

    def _handle_conversations_help(self) -> bool:
        """Show help for conversations command."""
        table = Table(title="Conversations Command Help")
        table.add_column("Subcommand", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Usage", style="dim")

        table.add_row("list", "List recent conversations", "/conversations [list] [limit]")
        table.add_row("check", "Show conversation details", "/conversations check <id>")
        table.add_row("set", "Switch to conversation", "/conversations set <id>")
        table.add_row("help", "Show this help message", "/conversations help")

        console.print(table)
        return True

    def handle_new(self, args: list) -> bool:
        """Handle /new command to start a new conversation."""
        title = ' '.join(args) if args else None
        try:
            conv = self.repl.conversation_manager.create_conversation(title=title)
        except Exception as e:
            logger.exception("❌ Failed to create conversation: %s", e)
            print_error(f"Failed to create conversation: {e}")
            return True

        if not conv or not getattr(conv, 'id', None):
            logger.error("❌ create_conversation returned invalid result: %r", conv)
            print_error("Failed to create conversation: invalid response")
            return True

        logger.info("✅ New conversation created: %s", conv.id)
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

        # Validate conversation ID
        is_valid, error_msg = self._validate_conversation_id(conv_id)
        if not is_valid:
            print_error(f"Invalid conversation ID: {error_msg}")
            return True

        try:
            loaded = self.repl.conversation_manager.load_conversation(conv_id)
        except Exception as e:
            logger.exception("❌ Failed to load conversation %s: %s", conv_id, e)
            print_error(f"Failed to load conversation: {e}")
            return True

        if loaded:
            try:
                conv = self.repl.conversation_manager.current_conversation
                logger.info("✅ Loaded conversation: %s", conv_id)
                print_success(f"Loaded conversation: {conv_id}")
                console.print(f"  Messages: {len(conv.messages)}")
                console.print(f"  Tokens: {conv.token_count}")
            except Exception as e:
                logger.exception(
                    "❌ Failed to access conversation attributes for %s: %s", conv_id, e
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
            logger.error("❌ Conversation object missing expected attributes: %s", e)
            print_error(f"Cannot compact: conversation object is malformed ({e})")
            return True

        # Compact by summarizing old messages
        try:
            with console.status("[cyan]⏳ Compacting conversation...[/cyan]", spinner="dots"):
                success = self.repl.conversation_manager.compact_conversation()

            if not success:
                # Compaction returned False - log and inform user
                logger.warning(
                    "⚠️ Compaction returned False for conversation %s", original_conv_id
                )
                print_error("Compaction failed - conversation unchanged")
                return True

        except Exception as e:
            # Log full exception with stack trace
            logger.exception(
                "❌ Failed to compact conversation %s: %s", original_conv_id, e
            )
            print_error(f"Compaction failed: {e}")

            # Error Recovery Strategy:
            # 1. Check if current conversation state changed during failed compaction
            # 2. If state is inconsistent (None or different ID), attempt restore
            # 3. Reload original conversation from persistent storage
            # 4. If restore fails, guide user to recovery options (/conversations list)
            current_conv = self.repl.conversation_manager.current_conversation
            if current_conv is None or current_conv.id != original_conv_id:
                # State changed during failed compaction - try to reload original
                logger.info(
                    "🔄 Attempting to restore original conversation %s", original_conv_id
                )
                try:
                    self.repl.conversation_manager.load_conversation(original_conv_id)
                    logger.info("✅ Successfully restored conversation %s", original_conv_id)
                except Exception as restore_err:
                    logger.exception(
                        "❌ Failed to restore conversation %s: %s",
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
            logger.error("❌ Compaction succeeded but no active conversation exists (unexpected state)")
            print_warning("Conversation removed or compaction resulted in no active conversation")
            console.print(f"  Messages: {before_messages} → N/A")
            console.print(f"  Tokens: {before_tokens} → N/A")
            return True

        try:
            after_tokens = conv.token_count
            after_messages = len(conv.messages)
        except AttributeError as e:
            logger.error(
                "❌ Compacted conversation object missing expected attributes: %s", e
            )
            print_error(f"Compaction completed but cannot display results: {e}")
            return True

        logger.info("✅ Conversation compacted: %s -> %s tokens", before_tokens, after_tokens)
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

        # Validate conversation ID
        is_valid, error_msg = self._validate_conversation_id(conv_id)
        if not is_valid:
            print_error(f"Invalid conversation ID: {error_msg}")
            return True

        # Confirmation with proper exception handling
        try:
            confirm = input(f"Delete conversation {conv_id}? (y/N): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print_warning("Cancelled")
            return True
        except Exception as e:
            logger.warning("⚠️ Error during confirmation prompt: %s", e)
            print_warning("Cancelled due to error")
            return True

        if confirm != 'y':
            print_warning("Cancelled")
            return True

        try:
            if self.repl.conversation_manager.delete_conversation(conv_id):
                logger.info("✅ Conversation deleted: %s", conv_id)
                print_success(f"Conversation deleted: {conv_id}")
            else:
                print_error(f"Failed to delete conversation: {conv_id}")
        except Exception as e:
            logger.exception("❌ Failed to delete conversation %s: %s", conv_id, e)
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
