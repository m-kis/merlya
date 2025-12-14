"""
Merlya SSH - MFA/2FA authentication support.

Provides keyboard-interactive authentication and MFA callbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


class MFAAuthHandler:
    """Handler for MFA/2FA authentication challenges."""

    def __init__(
        self,
        mfa_callback: Callable[[str], str] | None = None,
        passphrase_callback: Callable[[str], str] | None = None,
    ) -> None:
        """
        Initialize MFA auth handler.

        Args:
            mfa_callback: Callback for MFA/2FA responses.
            passphrase_callback: Callback for SSH key passphrases.
        """
        self._mfa_callback = mfa_callback
        self._passphrase_callback = passphrase_callback

    def create_mfa_client(self) -> type | None:
        """Create MFA client factory if callback is set."""
        if not self._mfa_callback:
            return None

        import asyncssh

        mfa_cb = self._mfa_callback

        class _MFAClient(asyncssh.SSHClient):
            """SSH client with MFA support."""

            def kbdint_auth_requested(self) -> str:
                """Return empty string to let server pick keyboard-interactive method."""
                return ""

            def kbdint_challenge_received(
                self,
                name: str,
                instructions: str,
                _lang: str,  # Required by interface
                prompts: Sequence[tuple[str, bool]],
            ) -> list[str] | None:
                """Handle keyboard-interactive (MFA/2FA) challenges."""
                from loguru import logger

                logger.debug(f"🔐 MFA challenge received: {name or 'Authentication'}")
                if instructions:
                    logger.debug(f"   Instructions: {instructions}")

                responses: list[str] = []
                for prompt, _echo in prompts:
                    response = mfa_cb(prompt)
                    responses.append(response)
                return responses

        return _MFAClient

    def has_mfa_callback(self) -> bool:
        """Check if MFA callback is configured."""
        return self._mfa_callback is not None

    def has_passphrase_callback(self) -> bool:
        """Check if passphrase callback is configured."""
        return self._passphrase_callback is not None

    def get_mfa_callback(self) -> Callable[[str], str] | None:
        """Get MFA callback."""
        return self._mfa_callback

    def get_passphrase_callback(self) -> Callable[[str], str] | None:
        """Get passphrase callback."""
        return self._passphrase_callback
