"""
Merlya Health - Startup Health data structure.

Provides a container for startup health check results.
"""

from __future__ import annotations

from typing import Any

from merlya.core.types import CheckStatus


class StartupHealth:
    """
    Container for startup health check results.

    This class aggregates health check results and provides convenient
    methods to determine if Merlya can start successfully.
    """

    def __init__(
        self,
        checks: list[Any],
        model_tier: str | None = None,
        can_start: bool | None = None,
        has_warnings: bool | None = None,
        capabilities: dict[str, bool] | None = None,
    ):
        """
        Initialize StartupHealth with check results.

        Args:
            checks: List of HealthCheck results.
            model_tier: Recommended model tier based on system resources.
            can_start: Whether Merlya can start (computed from checks if None).
            has_warnings: Whether any checks have warnings (computed if None).
            capabilities: Dict of system capabilities (onnx_router, etc.).
        """
        self.checks = checks
        self.model_tier = model_tier

        # Compute values if not provided
        if can_start is None:
            self._compute_can_start()
        else:
            self.can_start = can_start

        if has_warnings is None:
            self._compute_has_warnings()
        else:
            self.has_warnings = has_warnings

        if capabilities is None:
            self._compute_capabilities()
        else:
            self.capabilities = capabilities

    def _compute_can_start(self) -> None:
        """Compute can_start from checks."""
        self.can_start = True
        for check in self.checks:
            if check.status == CheckStatus.ERROR and getattr(check, "critical", False):
                self.can_start = False
                break

    def _compute_has_warnings(self) -> None:
        """Compute has_warnings from checks."""
        self.has_warnings = any(check.status == CheckStatus.WARNING for check in self.checks)

    def _compute_capabilities(self) -> None:
        """Compute system capabilities from health checks."""
        self.capabilities = {}

        # Check for ONNX router capability
        # ONNX is considered available if:
        # - Model is present (status=OK)
        # - OR model can be downloaded (status=WARNING with can_download=True)
        onnx_check = self.get_check("onnx_model")
        if onnx_check:
            if onnx_check.status == CheckStatus.OK:
                self.capabilities["onnx_router"] = True
            elif (
                onnx_check.status == CheckStatus.WARNING
                and onnx_check.details
                and onnx_check.details.get("can_download", False)
            ):
                # Model missing but downloadable - router should try to download
                self.capabilities["onnx_router"] = True
            else:
                self.capabilities["onnx_router"] = False
        else:
            self.capabilities["onnx_router"] = False

        # Add more capabilities as needed
        mcp_check = self.get_check("mcp")
        if mcp_check and mcp_check.status == CheckStatus.OK:
            self.capabilities["mcp_servers"] = True
        else:
            self.capabilities["mcp_servers"] = False

    def get_check(self, name: str) -> Any | None:
        """
        Get a specific health check by name.

        Args:
            name: Name of the check to retrieve.

        Returns:
            HealthCheck instance if found, None otherwise.
        """
        for check in self.checks:
            if check.name == name:
                return check
        return None

    def get_summary(self) -> dict[str, Any]:
        """
        Get a summary of startup health status.

        Returns:
            Dictionary with summary information.
        """
        return {
            "can_start": self.can_start,
            "has_warnings": self.has_warnings,
            "total_checks": len(self.checks),
            "model_tier": self.model_tier,
            "checks": {check.name: check.status.value for check in self.checks},
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert StartupHealth into a JSON-friendly dict."""
        return {
            "can_start": self.can_start,
            "has_warnings": self.has_warnings,
            "model_tier": self.model_tier,
            "capabilities": self.capabilities,
            "checks": self.checks,
        }

    def __repr__(self) -> str:
        """String representation of StartupHealth."""
        return (
            f"StartupHealth(can_start={self.can_start}, "
            f"has_warnings={self.has_warnings}, "
            f"checks={len(self.checks)})"
        )
