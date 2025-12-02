"""
Log management command handler.

Handles: /log

Provides runtime log configuration, viewing, and management.
"""
import logging
from typing import List

from rich.table import Table

from merlya.repl.ui import console, print_error, print_success, print_warning

log = logging.getLogger(__name__)


class LogCommandHandler:
    """
    Handles log-related slash commands.

    Commands:
    - /log show                     : Show current log configuration
    - /log level <level> [target]   : Set log level (DEBUG, INFO, WARNING, ERROR)
    - /log tail [N]                 : Show last N lines of log (default: 50)
    - /log clear [--all]            : Clear rotated logs (keep current unless --all)
    - /log stats                    : Show log file statistics
    - /log dir                      : Show/open log directory
    - /log set <key> <value>        : Set config option
    - /log format [json|text]       : Set log format
    """

    def __init__(self, repl):
        """Initialize with reference to the main REPL instance."""
        self.repl = repl

    def handle(self, args: List[str]) -> bool:
        """Handle /log command and subcommands."""
        if not args:
            return self._show_config()

        cmd = args[0].lower()

        try:
            if cmd == "show":
                return self._show_config()
            elif cmd == "level":
                return self._handle_level(args[1:])
            elif cmd == "tail":
                return self._handle_tail(args[1:])
            elif cmd == "clear":
                return self._handle_clear(args[1:])
            elif cmd == "stats":
                return self._show_stats()
            elif cmd == "dir":
                return self._show_dir()
            elif cmd == "set":
                return self._handle_set(args[1:])
            elif cmd == "format":
                return self._handle_format(args[1:])
            elif cmd == "rotate":
                return self._handle_rotate()
            else:
                print_warning(f"Unknown subcommand: {cmd}")
                self._show_help()
                return False

        except Exception as e:
            log.exception("Log operation failed: %s", e)
            print_error(f"Log operation failed: {e}")
            return False

    def _show_config(self) -> bool:
        """Show current log configuration."""
        from merlya.utils.log_config import get_log_config

        config = get_log_config()

        console.print("\n[bold]Log Configuration[/bold]\n")

        table = Table(show_header=False, box=None)
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Log Directory", config.log_dir)
        table.add_row("App Log File", config.app_log_name)
        table.add_row("File Level", config.file_level)
        table.add_row("Console Level", config.console_level)
        table.add_row("Console Enabled", str(config.console_enabled))
        table.add_row("Rotation Size", config.rotation_size)
        table.add_row("Rotation Time", config.rotation_time)
        table.add_row("Rotation Strategy", config.rotation_strategy)
        table.add_row("Retention", config.retention)
        table.add_row("Max Files", str(config.max_files))
        table.add_row("Compression", config.compression or "none")
        table.add_row("JSON Format", str(config.json_logs))

        console.print(table)

        console.print("\n[dim]Use '/log set <key> <value>' to change settings[/dim]")
        return True

    def _handle_level(self, args: List[str]) -> bool:
        """
        Set log level.

        Usage:
            /log level DEBUG           - Set both console and file to DEBUG
            /log level INFO console    - Set console level only
            /log level WARNING file    - Set file level only
        """
        from merlya.utils.logger import set_log_level

        if not args:
            print_error("Usage: /log level <level> [console|file|both]")
            console.print("[dim]Levels: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL[/dim]")
            return False

        level = args[0].upper()
        target = args[1].lower() if len(args) > 1 else "both"

        if target not in ("console", "file", "both"):
            print_error(f"Invalid target: {target} (use: console, file, both)")
            return False

        if set_log_level(level, target):
            print_success(f"Log level set to {level} for {target}")
            return True
        else:
            print_error(f"Invalid log level: {level}")
            return False

    def _handle_tail(self, args: List[str]) -> bool:
        """
        Show last N lines of log.

        Usage:
            /log tail        - Show last 50 lines
            /log tail 100    - Show last 100 lines
        """
        from merlya.utils.logger import tail_log

        lines = 50
        if args:
            try:
                lines = int(args[0])
                if lines < 1:
                    lines = 50
            except ValueError:
                pass

        log_content = tail_log(lines)

        if not log_content:
            print_warning("Log file is empty or doesn't exist yet")
            return True

        console.print(f"\n[bold]Last {lines} lines of log:[/bold]\n")
        console.print(log_content)
        return True

    def _handle_clear(self, args: List[str]) -> bool:
        """
        Clear log files.

        Usage:
            /log clear       - Clear rotated logs, keep current
            /log clear --all - Clear all logs including current
        """
        from merlya.utils.logger import clear_logs

        keep_current = "--all" not in args and "-a" not in args

        if not keep_current:
            console.print("\n[yellow]This will delete ALL log files including the current one.[/yellow]")
            confirm = input("Type 'yes' to confirm: ")
            if confirm.lower() != "yes":
                print_warning("Cancelled")
                return False

        deleted = clear_logs(keep_current=keep_current)

        if deleted > 0:
            print_success(f"Deleted {deleted} log file(s)")
        else:
            print_warning("No log files to delete")

        return True

    def _show_stats(self) -> bool:
        """Show log file statistics."""
        from merlya.utils.logger import get_log_stats

        stats = get_log_stats()

        console.print("\n[bold]Log Statistics[/bold]\n")

        # Config summary
        config = stats["config"]
        console.print(f"[cyan]Directory:[/cyan] {config['log_dir']}")
        console.print(f"[cyan]Current Log:[/cyan] {config['app_log']}")
        console.print(f"[cyan]Levels:[/cyan] File={config['file_level']}, Console={config['console_level']}")
        console.print(f"[cyan]Rotation:[/cyan] {config['rotation']}, Retention: {config['retention']}")
        console.print()

        # File list
        if stats["files"]:
            table = Table(title="Log Files")
            table.add_column("File", style="cyan")
            table.add_column("Size", style="green", justify="right")
            table.add_column("Modified", style="yellow")

            for f in stats["files"]:
                table.add_row(f["name"], f["size_human"], f["modified"][:19])

            console.print(table)
            console.print(f"\n[bold]Total Size:[/bold] {stats['total_size_human']}")
        else:
            print_warning("No log files found")

        return True

    def _show_dir(self) -> bool:
        """Show log directory path."""
        from merlya.utils.log_config import get_log_config

        config = get_log_config()
        console.print(f"\n[bold]Log Directory:[/bold] {config.log_dir}")

        # Check if directory exists
        from pathlib import Path
        log_dir = Path(config.log_dir)
        if log_dir.exists():
            files = list(log_dir.glob("*.log*"))
            console.print(f"[dim]Contains {len(files)} log file(s)[/dim]")
        else:
            console.print("[dim]Directory will be created on first log write[/dim]")

        return True

    def _handle_set(self, args: List[str]) -> bool:
        """
        Set a configuration option.

        Usage:
            /log set rotation_size "20 MB"
            /log set file_level DEBUG
            /log set json_logs true
            /log set console_enabled true
        """
        from merlya.utils.log_config import get_log_config, save_log_config
        from merlya.utils.logger import setup_logger

        if len(args) < 2:
            print_error("Usage: /log set <key> <value>")
            console.print("\n[dim]Available settings:[/dim]")
            console.print("  log_dir, app_log_name")
            console.print("  console_level, file_level")
            console.print("  rotation_size, rotation_time, rotation_strategy")
            console.print("  retention, max_files, compression")
            console.print("  json_logs, include_caller, use_emoji")
            console.print("  console_enabled")
            return False

        key = args[0]
        value = " ".join(args[1:])  # Allow spaces in values

        config = get_log_config()

        # Handle type conversion
        bool_keys = {"json_logs", "include_caller", "use_emoji", "console_enabled"}
        int_keys = {"max_files"}

        try:
            if key in bool_keys:
                value = value.lower() in ("1", "true", "yes", "on")
            elif key in int_keys:
                value = int(value)
            elif key == "compression":
                if value.lower() in ("none", "null", ""):
                    value = None

            if not hasattr(config, key):
                print_error(f"Unknown setting: {key}")
                return False

            setattr(config, key, value)

            # Validate by calling __post_init__
            config.__post_init__()

            # Save and apply
            if save_log_config(config):
                setup_logger(config=config)
                print_success(f"Set {key} = {value}")
                return True
            else:
                print_error("Failed to save configuration")
                return False

        except ValueError as e:
            print_error(f"Invalid value: {e}")
            return False

    def _handle_format(self, args: List[str]) -> bool:
        """
        Set log format.

        Usage:
            /log format json    - Use JSON format
            /log format text    - Use text format (default)
        """
        from merlya.utils.log_config import get_log_config, save_log_config
        from merlya.utils.logger import setup_logger

        if not args:
            print_error("Usage: /log format <json|text>")
            return False

        fmt = args[0].lower()

        if fmt not in ("json", "text"):
            print_error(f"Invalid format: {fmt} (use: json, text)")
            return False

        config = get_log_config()
        config.json_logs = (fmt == "json")

        if save_log_config(config):
            setup_logger(config=config)
            print_success(f"Log format set to {fmt}")
            return True
        else:
            print_error("Failed to save configuration")
            return False

    def _handle_rotate(self) -> bool:
        """Force log rotation (closes current file)."""
        from loguru import logger as loguru_logger

        from merlya.utils.logger import setup_logger

        # Remove all handlers and re-setup to force rotation
        loguru_logger.remove()
        setup_logger()
        print_success("Log file rotated")
        return True

    def _show_help(self) -> None:
        """Show help for /log command."""
        console.print("[bold]Log Management[/bold]\n")
        console.print("[yellow]Commands:[/yellow]")
        console.print("  /log show                  Show current configuration")
        console.print("  /log level <lvl> [target]  Set level (DEBUG/INFO/WARNING/ERROR)")
        console.print("  /log tail [N]              Show last N log lines (default: 50)")
        console.print("  /log stats                 Show log file statistics")
        console.print("  /log dir                   Show log directory path")
        console.print("  /log clear [--all]         Clear old logs (--all includes current)")
        console.print("  /log set <key> <value>     Set configuration option")
        console.print("  /log format <json|text>    Set log format")
        console.print("  /log rotate                Force log rotation")
        console.print()
        console.print("[yellow]Examples:[/yellow]")
        console.print("  /log level DEBUG")
        console.print("  /log level WARNING console")
        console.print("  /log set rotation_size \"20 MB\"")
        console.print("  /log set console_enabled true")
        console.print("  /log tail 100")
