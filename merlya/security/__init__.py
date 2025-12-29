"""
Merlya Security utilities.

Provides privilege elevation helpers.
"""

from merlya.security.permissions import (
    CenterMode,
    ElevationDeniedError,
    ElevationManager,
    ElevationResult,
)

__all__ = [
    "CenterMode",
    "ElevationDeniedError",
    "ElevationManager",
    "ElevationResult",
]
