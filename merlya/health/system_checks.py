"""
Merlya Health - System checks module.

Provides system-level health checks (RAM, disk space).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import psutil

from merlya.core.types import CheckStatus, HealthCheck
from merlya.i18n import t


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
