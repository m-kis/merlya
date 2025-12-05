"""
Merlya Health - Health check implementations.

Checks system capabilities at startup.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from merlya.core.types import CheckStatus, HealthCheck
from merlya.i18n import t


@dataclass
class StartupHealth:
    """Results of all startup health checks."""

    checks: list[HealthCheck] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    model_tier: str | None = None

    @property
    def can_start(self) -> bool:
        """Check if all critical checks passed."""
        return not any(c.critical and c.status == CheckStatus.ERROR for c in self.checks)

    @property
    def has_warnings(self) -> bool:
        """Check if any warnings were raised."""
        return any(c.status == CheckStatus.WARNING for c in self.checks)

    def get_check(self, name: str) -> HealthCheck | None:
        """Get check by name."""
        for check in self.checks:
            if check.name == name:
                return check
        return None


def check_ram() -> tuple[HealthCheck, str]:
    """
    Check available RAM and determine model tier.

    Returns:
        Tuple of (HealthCheck, tier name).
    """
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024**3)

    if available_gb >= 4.0:
        tier = "performance"
        status = CheckStatus.OK
    elif available_gb >= 2.0:
        tier = "balanced"
        status = CheckStatus.OK
    elif available_gb >= 0.5:
        tier = "lightweight"
        status = CheckStatus.WARNING
    else:
        tier = "llm_fallback"
        status = CheckStatus.WARNING

    message_key = "health.ram.ok" if status == CheckStatus.OK else "health.ram.warning"
    message = t(message_key, available=f"{available_gb:.1f}", tier=tier)

    return (
        HealthCheck(
            name="ram",
            status=status,
            message=message,
            details={"available_gb": available_gb, "tier": tier},
        ),
        tier,
    )


def check_disk_space(min_mb: int = 500) -> HealthCheck:
    """Check available disk space."""
    merlya_dir = Path.home() / ".merlya"
    merlya_dir.mkdir(parents=True, exist_ok=True)

    _total, _used, free = shutil.disk_usage(merlya_dir)
    free_mb = free // (1024 * 1024)

    if free_mb >= min_mb:
        status = CheckStatus.OK
        message = t("health.disk.ok", free=free_mb)
    elif free_mb >= 100:
        status = CheckStatus.WARNING
        message = t("health.disk.warning", free=free_mb)
    else:
        status = CheckStatus.ERROR
        message = t("health.disk.error", free=free_mb)

    return HealthCheck(
        name="disk_space",
        status=status,
        message=message,
        details={"free_mb": free_mb},
    )


async def check_llm_provider(api_key: str | None = None) -> HealthCheck:
    """Check LLM provider accessibility."""
    from merlya.config import get_config

    config = get_config()

    # Check if API key is configured
    if not api_key:
        # Try to get from environment or keyring
        import os

        from merlya.secrets import get_secret

        key_env = config.model.api_key_env or f"{config.model.provider.upper()}_API_KEY"
        api_key = os.getenv(key_env) or get_secret(key_env)

    if not api_key:
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.ERROR,
            message=t("health.llm.error"),
            critical=True,
        )

    # Try to ping provider (simplified check)
    try:
        # TODO: Implement actual provider ping
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.OK,
            message=t("health.llm.ok", provider=config.model.provider),
            details={"provider": config.model.provider, "model": config.model.model},
        )
    except Exception as e:
        return HealthCheck(
            name="llm_provider",
            status=CheckStatus.WARNING,
            message=t("health.llm.warning", error=str(e)),
            details={"error": str(e)},
        )


def check_ssh_available() -> HealthCheck:
    """Check SSH availability."""
    details: dict[str, Any] = {}

    # Check asyncssh
    try:
        import asyncssh  # noqa: F401 - import needed for availability check

        details["asyncssh"] = True
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
    """Check keyring accessibility."""
    try:
        import keyring

        # Test write/read/delete
        test_key = "__merlya_health_test__"
        test_value = "test"

        keyring.set_password("merlya", test_key, test_value)
        result = keyring.get_password("merlya", test_key)
        keyring.delete_password("merlya", test_key)

        if result == test_value:
            return HealthCheck(
                name="keyring",
                status=CheckStatus.OK,
                message=t("health.keyring.ok"),
            )
        else:
            return HealthCheck(
                name="keyring",
                status=CheckStatus.WARNING,
                message=t("health.keyring.warning", error="value mismatch"),
            )

    except ImportError:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=t("health.keyring.warning", error="not installed"),
        )
    except Exception as e:
        return HealthCheck(
            name="keyring",
            status=CheckStatus.WARNING,
            message=t("health.keyring.warning", error=str(e)),
        )


def check_web_search() -> HealthCheck:
    """Check DuckDuckGo search availability."""
    try:
        from ddgs import DDGS

        # Just check if it initializes
        with DDGS():
            pass

        return HealthCheck(
            name="web_search",
            status=CheckStatus.OK,
            message=t("health.web_search.ok"),
        )

    except ImportError:
        return HealthCheck(
            name="web_search",
            status=CheckStatus.DISABLED,
            message=t("health.web_search.disabled"),
        )
    except Exception as e:
        return HealthCheck(
            name="web_search",
            status=CheckStatus.WARNING,
            message=t("health.web_search.warning", error=str(e)),
        )


async def run_startup_checks() -> StartupHealth:
    """Run all startup health checks."""
    health = StartupHealth()

    # RAM check (determines model tier)
    ram_check, tier = check_ram()
    health.checks.append(ram_check)
    health.model_tier = tier

    # Disk space
    health.checks.append(check_disk_space())

    # LLM provider
    health.checks.append(await check_llm_provider())

    # SSH
    ssh_check = check_ssh_available()
    health.checks.append(ssh_check)
    health.capabilities["ssh"] = ssh_check.status == CheckStatus.OK

    # Keyring
    keyring_check = check_keyring()
    health.checks.append(keyring_check)
    health.capabilities["keyring"] = keyring_check.status == CheckStatus.OK

    # Web search
    ws_check = check_web_search()
    health.checks.append(ws_check)
    health.capabilities["web_search"] = ws_check.status == CheckStatus.OK

    return health
