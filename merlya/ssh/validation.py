"""
Merlya SSH - Key validation utilities.

Validate SSH private keys.
"""

from __future__ import annotations

from pathlib import Path


def _is_ppk_format(path: Path) -> bool:
    """Check if a key file is in PuTTY PPK format.

    PPK files start with "PuTTY-User-Key-File-" followed by version number.
    """
    try:
        with path.open("rb") as f:
            # Read first 50 bytes to check header
            header = f.read(50)
            return header.startswith(b"PuTTY-User-Key-File-")
    except OSError:
        return False


def _get_ppk_conversion_message(key_path: Path) -> str:
    """Generate helpful error message for PPK format keys."""
    return (
        f"PuTTY PPK format is not supported: {key_path}\n\n"
        "Please convert to OpenSSH format using one of these methods:\n\n"
        "  Option 1 - Using puttygen (Linux/Mac):\n"
        f"    puttygen {key_path} -O private-openssh -o {key_path.stem}_openssh\n\n"
        "  Option 2 - Using PuTTYgen (Windows):\n"
        "    1. Open PuTTYgen\n"
        "    2. Load your .ppk file\n"
        "    3. Conversions → Export OpenSSH key\n\n"
        "  Option 3 - Using ssh-keygen:\n"
        f"    ssh-keygen -i -f {key_path} > {key_path.stem}_openssh"
    )


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

    # Check for PuTTY PPK format (not supported by asyncssh)
    if _is_ppk_format(path):
        return False, _get_ppk_conversion_message(path)

    # Check permissions (should be 600 or 400) - only on Unix
    import sys

    if sys.platform != "win32":
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
