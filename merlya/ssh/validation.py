"""
Merlya SSH - Key validation utilities.

Validate SSH private keys.
"""

from __future__ import annotations

from pathlib import Path


async def validate_private_key(
    key_path: str | Path,
    passphrase: str | None = None,
) -> tuple[bool, str]:
    """
    Validate that a private key can be loaded (with passphrase if needed).

    Args:
        key_path: Path to private key file.
        passphrase: Optional passphrase for encrypted keys.

    Returns:
        Tuple of (success, message).
    """
    import asyncssh

    path = Path(key_path).expanduser()

    if not path.exists():
        return False, f"Key file not found: {path}"

    # Check permissions (should be 600 or 400)
    mode = path.stat().st_mode & 0o777
    if mode not in (0o600, 0o400):
        return False, f"Key permissions too open ({oct(mode)}). Should be 600 or 400."

    try:
        # Try to read the key
        if passphrase:
            key = asyncssh.read_private_key(str(path), passphrase)
        else:
            key = asyncssh.read_private_key(str(path))

        # Get key info
        key_type = key.get_algorithm()
        key_comment = getattr(key, "comment", None) or "no comment"

        return True, f"Valid {key_type} key ({key_comment})"

    except asyncssh.KeyEncryptionError:
        return False, "Key is encrypted - passphrase required"
    except asyncssh.KeyImportError as e:
        return False, f"Invalid key format: {e}"
    except Exception as e:
        return False, f"Failed to load key: {e}"
