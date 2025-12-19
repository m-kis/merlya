"""
Merlya Secrets - Session password store.

Keeps passwords in memory only for the current session.
NOT persisted to keyring - cleared when session ends.

Security:
- Passwords stored in memory only
- Automatically cleared on session end
- Uses getpass for secure terminal input
- Thread-safe with lock
"""

from __future__ import annotations

import asyncio
import getpass
import hashlib
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.ui.console import ConsoleUI


def _get_key_fingerprint(key: str) -> str:
    """
    Generate a deterministic fingerprint for logging sensitive keys.

    Uses SHA256 hash truncated to first 8 characters to provide
    sufficient uniqueness for debugging while avoiding PII exposure.

    Args:
        key: The sensitive key to fingerprint

    Returns:
        8-character hex string fingerprint
    """
    return hashlib.sha256(key.encode()).hexdigest()[:8]


@dataclass
class SessionPasswordStore:
    """
    In-memory password store for the current session.

    Passwords are NOT persisted to keyring - they exist only
    in memory and are cleared when the session ends.

    Use this for:
    - Interactive password prompts during SSH commands
    - Temporary credentials that shouldn't be persisted
    - sudo/su passwords that user doesn't want stored

    Thread-safe with internal lock.
    """

    _passwords: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _ui: ConsoleUI | None = field(default=None, repr=False)

    def set_ui(self, ui: ConsoleUI) -> None:
        """Set UI for async password prompts."""
        self._ui = ui

    def get(self, key: str) -> str | None:
        """Get password from session store."""
        with self._lock:
            return self._passwords.get(key)

    def set(self, key: str, value: str) -> None:
        """Store password in session (memory only)."""
        with self._lock:
            self._passwords[key] = value
            logger.debug("🔐 Session password stored")

    def has(self, key: str) -> bool:
        """Check if password exists in session."""
        with self._lock:
            return key in self._passwords

    def delete(self, key: str) -> None:
        """Remove password from session."""
        with self._lock:
            if key in self._passwords:
                del self._passwords[key]
                logger.debug("🔐 Session password removed")

    def clear(self) -> None:
        """Clear all session passwords."""
        with self._lock:
            count = len(self._passwords)
            self._passwords.clear()
            if count > 0:
                logger.debug(f"🔐 Cleared {count} session password(s)")

    def prompt_password_sync(self, prompt: str, host: str | None = None) -> str:
        """
        Prompt for password synchronously using getpass.

        This is the secure, blocking version for use in sync contexts.
        Password is NOT stored automatically - call set() to store.

        Args:
            prompt: Prompt message to display.
            host: Optional host for logging.

        Returns:
            Password entered by user (may be empty).
        """
        display_prompt = f"🔐 {prompt}"
        if host:
            display_prompt = f"🔐 [{host}] {prompt}"

        try:
            password = getpass.getpass(f"{display_prompt}: ")
            return password
        except (KeyboardInterrupt, EOFError):
            logger.debug("Password prompt cancelled")
            return ""

    async def prompt_password_async(self, prompt: str, host: str | None = None) -> str:
        """
        Prompt for password asynchronously using UI.

        Uses prompt_toolkit if UI is set, falls back to getpass.
        Password is NOT stored automatically - call set() to store.

        Args:
            prompt: Prompt message to display.
            host: Optional host for logging.

        Returns:
            Password entered by user (may be empty).
        """
        display_prompt = f"🔐 {prompt}"
        if host:
            display_prompt = f"🔐 [{host}] {prompt}"

        if self._ui:
            try:
                return await self._ui.prompt_secret(display_prompt)
            except Exception:
                logger.debug("Async prompt failed, falling back to getpass")

        # Fallback to sync getpass
        return await asyncio.to_thread(self.prompt_password_sync, prompt, host)

    def get_or_prompt_sync(
        self,
        key: str,
        prompt: str,
        host: str | None = None,
        *,
        store: bool = True,
    ) -> str:
        """
        Get password from session or prompt for it (sync).

        Args:
            key: Key for the password (e.g., "sudo:192.168.1.7").
            prompt: Prompt message if password not found.
            host: Optional host for display.
            store: Whether to store the password in session.

        Returns:
            Password (from cache or newly entered).
        """
        # Check cache first
        cached = self.get(key)
        if cached:
            logger.debug("🔐 Using cached session password")
            return cached

        # Prompt user
        password = self.prompt_password_sync(prompt, host)

        # Store if requested and non-empty
        if store and password:
            self.set(key, password)

        return password

    async def get_or_prompt_async(
        self,
        key: str,
        prompt: str,
        host: str | None = None,
        *,
        store: bool = True,
    ) -> str:
        """
        Get password from session or prompt for it (async).

        Args:
            key: Key for the password (e.g., "sudo:192.168.1.7").
            prompt: Prompt message if password not found.
            host: Optional host for display.
            store: Whether to store the password in session.

        Returns:
            Password (from cache or newly entered).
        """
        # Check cache first
        cached = self.get(key)
        if cached:
            logger.debug("🔐 Using cached session password")
            return cached

        # Prompt user
        password = await self.prompt_password_async(prompt, host)

        # Store if requested and non-empty
        if store and password:
            self.set(key, password)

        return password


# Global session store instance (created per session)
_session_store: SessionPasswordStore | None = None
_store_lock = threading.Lock()


def get_session_store() -> SessionPasswordStore:
    """Get or create the global session password store."""
    global _session_store
    with _store_lock:
        if _session_store is None:
            _session_store = SessionPasswordStore()
        return _session_store


def clear_session_store() -> None:
    """Clear and reset the global session store."""
    global _session_store
    with _store_lock:
        if _session_store is not None:
            _session_store.clear()
            _session_store = None
