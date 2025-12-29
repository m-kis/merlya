"""
Elevation manager for privilege escalation.

Explicit per-host elevation configuration (no auto-detection).
Simplified from 754 lines to ~200 lines by removing:
- Automatic capability detection (SSH probes)
- Multi-layer caching (memory, DB, SSH)
- Complex priority-based method selection

Now uses:
- host.elevation_method configured in inventory
- Simple session password caching (opt-in)
- Different HITL levels for DIAGNOSTIC vs CHANGE centers
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.secrets.store import SecretStore

# Regex to strip pre-existing sudo/doas prefixes from commands
_SUDO_PREFIX_RE = re.compile(
    r"^\s*sudo(?:"
    r"(?:\s+-(?:n|S|E|H|k|i|s)\b)"
    r"|(?:\s+-u\s+\S+)"
    r"|(?:\s+-p\s+\S+)"
    r")*\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
_DOAS_PREFIX_RE = re.compile(
    r"^\s*doas(?:"
    r"(?:\s+-(?:n|s)\b)"
    r"|(?:\s+-u\s+\S+)"
    r")*\s+(?P<rest>.+)$",
    re.IGNORECASE,
)


class CenterMode(str, Enum):
    """Operation mode for centers."""

    DIAGNOSTIC = "diagnostic"  # Read-only investigation
    CHANGE = "change"  # Controlled mutation


@dataclass
class ElevationResult:
    """Result of preparing an elevated command."""

    command: str
    input_data: str | None = None
    method: str | None = None
    elevated: bool = False


class ElevationDeniedError(Exception):
    """Raised when elevation is declined by user."""

    pass


class ElevationManager:
    """Explicit elevation manager (no auto-detection).

    Uses host.elevation_method from inventory configuration.
    Password caching is opt-in per session.
    """

    def __init__(self, ctx: SharedContext) -> None:
        self.ctx = ctx
        self._session_passwords: dict[str, str] = {}  # host_name -> password

    @property
    def _secrets(self) -> SecretStore:
        """Get secret store from context."""
        return self.ctx.secrets

    def _password_key(self, host_name: str, method: str) -> str:
        """Get keyring key for elevation password."""
        if method == "su":
            return f"elevation:{host_name}:root:password"
        return f"elevation:{host_name}:password"

    def _method_needs_password(self, method: str) -> bool:
        """Check if elevation method requires a password."""
        return method in {"sudo_password", "doas_password", "su"}

    async def prepare_command(
        self,
        host: Host,
        command: str,
        center: CenterMode = CenterMode.DIAGNOSTIC,
    ) -> ElevationResult:
        """Prepare a command with elevation if configured.

        Args:
            host: Host with elevation_method configured.
            command: Command to execute.
            center: Center mode (affects HITL level).

        Returns:
            ElevationResult with prepared command.

        Raises:
            ElevationDeniedError: If user declines elevation.
        """
        from merlya.persistence.models import ElevationMethod

        # Handle both enum and string (due to use_enum_values=True in Host)
        method_value = host.elevation_method
        if isinstance(method_value, ElevationMethod):
            method = method_value.value
        else:
            method = str(method_value)

        # No elevation configured
        if method == ElevationMethod.NONE.value or method == "none":
            return ElevationResult(command=command, method=None, elevated=False)

        # Request confirmation based on center mode
        confirmed = await self._request_confirmation(host, command, center)
        if not confirmed:
            raise ElevationDeniedError(f"Elevation declined for {host.name}")

        # Get password if needed
        password = (
            await self._get_password(host, method) if self._method_needs_password(method) else None
        )

        # Build elevated command
        elevated_cmd, input_data = self._build_elevated_command(command, method, password)

        return ElevationResult(
            command=elevated_cmd,
            input_data=input_data,
            method=method,
            elevated=True,
        )

    async def _request_confirmation(
        self,
        host: Host,
        command: str,
        center: CenterMode,
    ) -> bool:
        """Request user confirmation for elevation."""
        from merlya.persistence.models import ElevationMethod

        # Get method as string
        method_value = host.elevation_method
        if isinstance(method_value, ElevationMethod):
            method_str = method_value.value
        else:
            method_str = str(method_value)

        if center == CenterMode.DIAGNOSTIC:
            # Simple confirmation for read-only operations
            return await self.ctx.ui.prompt_confirm(
                f"Executer '{command[:50]}...' en tant que {host.elevation_user} sur {host.name}?",
                default=True,
            )
        else:
            # Full HITL for CHANGE operations - more detailed prompt
            return await self.ctx.ui.prompt_confirm(
                f"CHANGE: Elevation vers {host.elevation_user} sur {host.name}\n"
                f"Commande: {command}\n"
                f"Methode: {method_str}\n"
                f"Confirmer?",
                default=False,
            )

    async def _get_password(self, host: Host, method: str) -> str | None:
        """Get password for elevation (no auto-cache)."""
        # Check session cache first
        if host.name in self._session_passwords:
            return self._session_passwords[host.name]

        # Check keyring
        password_key = self._password_key(host.name, method)
        stored = self._secrets.get(password_key)
        if stored:
            return stored

        # Prompt user
        password = await self.ctx.ui.prompt_secret(f"Mot de passe pour {method} sur {host.name}:")

        if not password:
            return None

        # Offer to cache for session
        cache = await self.ctx.ui.prompt_confirm(
            "Memoriser pour cette session?",
            default=False,
        )
        if cache:
            self._session_passwords[host.name] = password

        return password

    def _build_elevated_command(
        self,
        command: str,
        method: str,
        password: str | None,
    ) -> tuple[str, str | None]:
        """Build elevated command with appropriate prefix."""
        # Strip any existing sudo/doas prefix
        m = _SUDO_PREFIX_RE.match(command)
        if m:
            command = m.group("rest")
        else:
            m = _DOAS_PREFIX_RE.match(command)
            if m:
                command = m.group("rest")

        if method == "sudo":
            return f"sudo -n {command}", None

        if method == "sudo_password":
            if password:
                return f"sudo -S -p '' {command}", f"{password}\n"
            return f"sudo -n {command}", None

        if method == "doas":
            return f"doas {command}", None

        if method == "doas_password":
            if password:
                escaped = command.replace("'", "'\"'\"'")
                return f"doas sh -c '{escaped}'", f"{password}\n"
            return f"doas {command}", None

        if method == "su":
            escaped = command.replace("'", "'\"'\"'")
            return f"su -c '{escaped}'", f"{password}\n" if password else None

        logger.warning(f"Unknown elevation method {method}, running without elevation")
        return command, None

    def store_password(self, host_name: str, password: str, method: str) -> str:
        """Store elevation password in keyring."""
        password_key = self._password_key(host_name, method)
        self._secrets.set(password_key, password)
        logger.debug(f"Stored elevation password for {host_name}")
        return f"@{password_key}"

    def clear_session_cache(self, host_name: str | None = None) -> None:
        """Clear session password cache."""
        if host_name:
            self._session_passwords.pop(host_name, None)
        else:
            self._session_passwords.clear()

    def clear_keyring(self, host_name: str) -> None:
        """Clear stored passwords from keyring for a host."""
        for method in ["sudo_password", "doas_password", "su"]:
            key = self._password_key(host_name, method)
            self._secrets.remove(key)
