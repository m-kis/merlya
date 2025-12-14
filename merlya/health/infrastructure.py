"""
Merlya Health - Infrastructure checks module.

Provides infrastructure health checks (SSH, keyring).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from merlya.core.types import CheckStatus, HealthCheck
from merlya.i18n import t


def check_ssh_available() -> HealthCheck:
    """Check SSH availability."""
    details: dict[str, Any] = {}

    # Check asyncssh
    try:
        import asyncssh

        details["asyncssh"] = True
        details["asyncssh_version"] = asyncssh.__version__
    except ImportError:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.DISABLED,
            message=t("health.ssh.disabled"),
            details={"asyncssh": False},
        )

    # Check system SSH client
    ssh_path = shutil.which("ssh")
    details["ssh_client"] = ssh_path is not None
    details["ssh_path"] = ssh_path

    # Check for SSH key
    ssh_key_paths = [
        Path.home() / ".ssh" / "id_rsa",
        Path.home() / ".ssh" / "id_ed25519",
        Path.home() / ".ssh" / "id_ecdsa",
    ]
    has_key = any(p.exists() for p in ssh_key_paths)
    details["has_ssh_key"] = has_key

    if ssh_path:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.OK,
            message=t("health.ssh.ok"),
            details=details,
        )
    else:
        return HealthCheck(
            name="ssh",
            status=CheckStatus.WARNING,
            message=t("health.ssh.warning"),
            details=details,
        )


def check_keyring() -> HealthCheck:
    """Check keyring accessibility with real write/read test."""
    try:
        import keyring
        from keyring.errors import KeyringError

        # Test write/read/delete
        test_key = "__merlya_health_test__"
        test_value = f"test_{time.time()}"

        try:
            keyring.set_password("merlya", test_key, test_value)
            result = keyring.get_password("merlya", test_key)
            keyring.delete_password("merlya", test_key)

            if result == test_value:
                # Get backend info
                backend = keyring.get_keyring()
                backend_name = type(backend).__name__

                return HealthCheck(
                    name="keyring",
                    status=CheckStatus.OK,
                    message=t("health.keyring.ok") + f" ({backend_name})",
                    details={"backend": backend_name},
                )
            else:
                return HealthCheck(
                    name="keyring",
                    status=CheckStatus.WARNING,
                    message=t("health.keyring.warning", error="value mismatch"),
                    details={"error": "value_mismatch"},
                )

        except KeyringError as e:
            return HealthCheck(
                name="keyring",
                status=CheckStatus.WARNING,
                message=t("health.keyring.warning", error=str(e)),
                details={"error": str(e)},
            )

    except ImportError:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=t("health.keyring.warning", error="not installed"),
            details={"error": "not_installed"},
        )
    except Exception as e:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=t("health.keyring.warning", error=str(e)),
            details={"error": str(e)},
        )
