"""
Custom completers for Athena REPL.

Provides intelligent autocompletion for:
- Slash commands (/help, /scan, etc.)
- Host names from inventory
- Variables (@variable_name)
- Service names
"""
import logging
from typing import Iterable, List

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document

from athena_ai.repl.commands import SLASH_COMMANDS

logger = logging.getLogger(__name__)


class AthenaCompleter(Completer):
    """
    Custom completer for Athena REPL.

    Provides context-aware completion for:
    - Slash commands at line start
    - Hostnames after keywords like "on", "from"
    - Variables starting with @
    - Service names in relevant contexts
    """

    # Common services for completion
    SERVICES = [
        "mysql", "mariadb", "postgres", "postgresql", "mongodb", "mongo",
        "redis", "memcached", "nginx", "apache", "httpd", "docker",
        "kubernetes", "k8s", "haproxy", "elasticsearch", "kafka",
        "rabbitmq", "systemd", "ssh", "backup", "cron"
    ]

    # Keywords that precede hostnames
    HOST_KEYWORDS = ["on", "from", "to", "for", "serveur", "server", "host"]

    def __init__(self, context_manager=None, credentials_manager=None):
        """
        Initialize completer with optional managers for dynamic completion.

        Args:
            context_manager: ContextManager for hostname inventory
            credentials_manager: CredentialManager for variables
        """
        self.context_manager = context_manager
        self.credentials_manager = credentials_manager
        self._cached_hosts: List[str] = []
        self._cached_variables: List[str] = []
        self._cached_inventory_hosts: List[str] | None = None

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        """Generate completions based on current context."""
        text = document.text_before_cursor
        word = document.get_word_before_cursor()

        # Slash commands at line start
        if text.startswith('/'):
            yield from self._complete_slash_commands(text)
            return

        # Variables starting with @
        if '@' in text:
            at_pos = text.rfind('@')
            partial = text[at_pos + 1:]
            yield from self._complete_variables(partial)
            return

        # Hostnames after keywords
        words = text.lower().split()
        if len(words) >= 1:
            last_word = words[-1] if words else ''
            prev_word = words[-2] if len(words) >= 2 else ''

            # Complete hostname after "on", "from", etc.
            if prev_word in self.HOST_KEYWORDS:
                yield from self._complete_hostnames(last_word)
                return

            # Complete service names in context
            if 'check' in words or 'status' in words or 'restart' in words:
                yield from self._complete_services(word)

    def _complete_slash_commands(self, text: str) -> Iterable[Completion]:
        """Complete slash commands."""
        for cmd, description in SLASH_COMMANDS.items():
            if cmd.startswith(text):
                yield Completion(
                    cmd,
                    start_position=-len(text),
                    display=cmd,
                    display_meta=description[:50]
                )

    def _complete_hostnames(self, partial: str) -> Iterable[Completion]:
        """Complete hostnames from inventory."""
        hosts = self._get_hosts()
        partial_lower = partial.lower()

        for host in hosts:
            if host.lower().startswith(partial_lower):
                yield Completion(
                    host,
                    start_position=-len(partial),
                    display=host,
                    display_meta="host"
                )

    def _complete_variables(self, partial: str) -> Iterable[Completion]:
        """Complete @variables and @inventory_hosts."""
        variables = self._get_variables()
        partial_lower = partial.lower()

        # Pre-compute lowercase variable set for O(1) lookups
        # This avoids O(n×m) complexity when filtering inventory hosts
        variables_lower = {v.lower() for v in variables}

        # Complete user-defined variables
        for var in variables:
            if var.lower().startswith(partial_lower):
                yield Completion(
                    f"@{var}",
                    start_position=-len(partial) - 1,  # Include @
                    display=f"@{var}",
                    display_meta="variable"
                )

        # Complete inventory hosts
        inventory_hosts = self._get_inventory_hosts()
        for host in inventory_hosts:
            host_lower = host.lower()
            # Skip if already a user variable (user vars take priority)
            if host_lower in variables_lower:
                continue
            if host_lower.startswith(partial_lower):
                yield Completion(
                    f"@{host}",
                    start_position=-len(partial) - 1,  # Include @
                    display=f"@{host}",
                    display_meta="inventory host"
                )

    def _complete_services(self, partial: str) -> Iterable[Completion]:
        """Complete service names."""
        partial_lower = partial.lower()

        for service in self.SERVICES:
            if service.startswith(partial_lower):
                yield Completion(
                    service,
                    start_position=-len(partial),
                    display=service,
                    display_meta="service"
                )

    def _get_hosts(self) -> List[str]:
        """Get list of hostnames from context manager."""
        if self.context_manager:
            try:
                context = self.context_manager.get_context()
                inventory = context.get('inventory', {})
                return list(inventory.keys())
            except Exception as e:
                logger.debug("Failed to get hosts from context manager: %s", e)
        return self._cached_hosts

    def _get_variables(self) -> List[str]:
        """Get list of variables from credentials manager."""
        if self.credentials_manager:
            try:
                variables = self.credentials_manager.list_variables()
                return list(variables.keys())
            except Exception as e:
                logger.debug("Failed to get variables from credentials manager: %s", e)
        return self._cached_variables

    def _get_inventory_hosts(self) -> List[str]:
        """Get list of hostnames from inventory (cached after first call)."""
        # Return cached value if available
        if self._cached_inventory_hosts is not None:
            return self._cached_inventory_hosts

        # Try credentials manager first (has get_inventory_hosts method)
        if self.credentials_manager:
            try:
                hosts = self.credentials_manager.get_inventory_hosts()
                self._cached_inventory_hosts = hosts
                return hosts
            except AttributeError:
                # credentials_manager doesn't have get_inventory_hosts method
                logger.debug("Credentials manager lacks get_inventory_hosts method")
            except Exception as e:
                logger.exception("Failed to list hosts from credentials manager: %s", e)

        # Direct fallback to inventory repository
        try:
            from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
            repo = get_inventory_repository()
            hosts = repo.list_hosts()
            result = [h["hostname"] for h in hosts]
            self._cached_inventory_hosts = result
            return result
        except Exception as e:
            logger.exception("Failed to list hosts from inventory repository: %s", e)
            self._cached_inventory_hosts = []
            return []

    def update_hosts(self, hosts: List[str]) -> None:
        """Update cached host list."""
        self._cached_hosts = hosts

    def update_variables(self, variables: List[str]) -> None:
        """Update cached variable list."""
        self._cached_variables = variables

    def update_inventory_hosts(self, hosts: List[str] | None = None) -> None:
        """Update or invalidate cached inventory host list.

        Args:
            hosts: New host list, or None to invalidate cache (force refresh on next access)
        """
        self._cached_inventory_hosts = hosts


def create_completer(context_manager=None, credentials_manager=None) -> AthenaCompleter:
    """
    Factory function to create an AthenaCompleter.

    Args:
        context_manager: Optional ContextManager for hostname completion
        credentials_manager: Optional CredentialManager for variable completion

    Returns:
        Configured AthenaCompleter instance
    """
    return AthenaCompleter(
        context_manager=context_manager,
        credentials_manager=credentials_manager
    )
