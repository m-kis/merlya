"""
Merlya Capabilities - Detector.

Dynamic detection of host and local tool capabilities.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess  # nosec B404 - required for tool detection
from typing import TYPE_CHECKING

from loguru import logger

from merlya.capabilities.cache import CapabilityCache
from merlya.capabilities.models import (
    HostCapabilities,
    LocalCapabilities,
    SSHCapability,
    ToolCapability,
    ToolName,
)

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.persistence.models import Host
    from merlya.ssh.pool import SSHPool


class CapabilityDetector:
    """
    Detects capabilities for hosts and local environment.

    Follows the principle of explicit configuration over auto-detection
    for critical capabilities like elevation (see ElevationManager).
    This detector focuses on tool availability and connectivity.
    """

    def __init__(self, ctx: SharedContext, cache: CapabilityCache | None = None):
        """
        Initialize capability detector.

        Args:
            ctx: Shared context with SSH pool and host repository.
            cache: Optional capability cache (creates one if not provided).
        """
        self._ctx = ctx
        self._cache = cache or CapabilityCache()

    @property
    def cache(self) -> CapabilityCache:
        """Get the capability cache."""
        return self._cache

    async def detect_host(self, host: Host, force: bool = False) -> HostCapabilities:
        """
        Detect capabilities for a remote host.

        Args:
            host: Host to detect capabilities for.
            force: Force re-detection even if cached.

        Returns:
            Host capabilities (from cache or freshly detected).
        """
        # Check cache first
        if not force:
            cached = await self._cache.get_host(host.name)
            if cached:
                logger.debug(f"🔍 Using cached capabilities for {host.name}")
                return cached

        logger.info(f"🔍 Detecting capabilities for host {host.name}")

        # Detect SSH connectivity
        ssh = await self._detect_ssh(host)

        # If SSH not available, return minimal capabilities
        if not ssh.available:
            caps = HostCapabilities(
                host_name=host.name,
                ssh=ssh,
                tools=[],
                web_access=False,
            )
            await self._cache.set_host(caps)
            return caps

        # Detect tools via SSH
        tools = await self._detect_remote_tools(host)

        caps = HostCapabilities(
            host_name=host.name,
            ssh=ssh,
            tools=tools,
            web_access=True,  # Assume web access if SSH works
        )

        await self._cache.set_host(caps)
        logger.info(f"✅ Capabilities detected for {host.name}: {len(tools)} tools")
        return caps

    async def detect_local(self, force: bool = False) -> LocalCapabilities:
        """
        Detect capabilities for the local machine.

        Args:
            force: Force re-detection even if cached.

        Returns:
            Local machine capabilities.
        """
        if not force:
            cached = await self._cache.get_local()
            if cached:
                logger.debug("🔍 Using cached local capabilities")
                return cached

        logger.info("🔍 Detecting local capabilities")

        tools = await self._detect_local_tools()

        caps = LocalCapabilities(
            tools=tools,
            web_access=True,
        )

        await self._cache.set_local(caps)
        logger.info(f"✅ Local capabilities detected: {len(tools)} tools")
        return caps

    async def _detect_ssh(self, host: Host) -> SSHCapability:
        """Test SSH connectivity to host."""
        try:
            pool = await self._ctx.get_ssh_pool()
            result = await pool.execute(
                host.name,
                "echo ok",
                timeout=10,
            )
            if result.exit_code == 0 and "ok" in result.stdout:
                return SSHCapability(
                    available=True,
                    read_only=host.ssh_mode.value == "read_only"
                    if hasattr(host.ssh_mode, "value")
                    else host.ssh_mode == "read_only",
                    auth_method="key",  # Simplified - pool handles auth
                )
            return SSHCapability(
                available=False,
                connection_error=result.stderr or "Unknown error",
            )
        except Exception as e:
            logger.debug(f"⚠️ SSH probe failed for {host.name}: {e}")
            return SSHCapability(
                available=False,
                connection_error=str(e),
            )

    async def _detect_remote_tools(self, host: Host) -> list[ToolCapability]:
        """Detect tools available on remote host."""
        tools: list[ToolCapability] = []
        pool = await self._ctx.get_ssh_pool()

        # Parallel tool detection
        tasks = [
            self._detect_remote_tool(pool, host.name, ToolName.ANSIBLE),
            self._detect_remote_tool(pool, host.name, ToolName.TERRAFORM),
            self._detect_remote_tool(pool, host.name, ToolName.KUBECTL),
            self._detect_remote_tool(pool, host.name, ToolName.GIT),
            self._detect_remote_tool(pool, host.name, ToolName.DOCKER),
            self._detect_remote_tool(pool, host.name, ToolName.HELM),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, ToolCapability):
                tools.append(result)
            elif isinstance(result, Exception):
                logger.debug(f"⚠️ Tool detection failed: {result}")

        return tools

    async def _detect_remote_tool(
        self,
        pool: SSHPool,
        host_name: str,
        tool: ToolName,
    ) -> ToolCapability:
        """Detect a specific tool on remote host."""
        commands = {
            ToolName.ANSIBLE: (
                "which ansible && ansible --version | head -1",
                r"ansible.*(\d+\.\d+)",
            ),
            ToolName.TERRAFORM: (
                "which terraform && terraform version | head -1",
                r"v(\d+\.\d+\.\d+)",
            ),
            ToolName.KUBECTL: (
                "which kubectl && kubectl version --client -o json 2>/dev/null | head -1",
                r'"gitVersion":\s*"v(\d+\.\d+\.\d+)"',
            ),
            ToolName.GIT: ("which git && git --version", r"git version (\d+\.\d+\.\d+)"),
            ToolName.DOCKER: (
                "which docker && docker --version",
                r"Docker version (\d+\.\d+\.\d+)",
            ),
            ToolName.HELM: ("which helm && helm version --short", r"v(\d+\.\d+\.\d+)"),
        }

        cmd, version_pattern = commands.get(tool, ("", ""))
        if not cmd:
            return ToolCapability(name=tool, installed=False)

        try:
            import re

            result = await pool.execute(host_name, cmd, timeout=10)
            if result.exit_code != 0:
                return ToolCapability(name=tool, installed=False)

            # Extract version
            match = re.search(version_pattern, result.stdout)
            version = match.group(1) if match else None

            # Check config validity
            config_valid = await self._check_remote_tool_config(pool, host_name, tool)

            return ToolCapability(
                name=tool,
                installed=True,
                version=version,
                config_valid=config_valid,
            )
        except Exception as e:
            logger.debug(f"⚠️ Failed to detect {tool.value} on {host_name}: {e}")
            return ToolCapability(name=tool, installed=False)

    async def _check_remote_tool_config(
        self,
        pool: SSHPool,
        host_name: str,
        tool: ToolName,
    ) -> bool:
        """Check if tool configuration is valid on remote host."""
        checks = {
            ToolName.KUBECTL: "kubectl config current-context 2>/dev/null",
            ToolName.TERRAFORM: "test -f terraform.tf || test -f main.tf",
            ToolName.ANSIBLE: "test -f ansible.cfg || test -f inventory",
            ToolName.GIT: "git rev-parse --git-dir 2>/dev/null",
            ToolName.DOCKER: "docker info > /dev/null 2>&1",
            ToolName.HELM: "helm list > /dev/null 2>&1",
        }

        check_cmd = checks.get(tool)
        if not check_cmd:
            return True  # No config check defined

        try:
            result = await pool.execute(host_name, check_cmd, timeout=5)
            return result.exit_code == 0
        except Exception:
            return False

    async def _detect_local_tools(self) -> list[ToolCapability]:
        """Detect tools available locally."""
        tools: list[ToolCapability] = []

        for tool_name in ToolName:
            cap = await self._detect_local_tool(tool_name)
            tools.append(cap)

        return tools

    async def _detect_local_tool(self, tool: ToolName) -> ToolCapability:
        """Detect a specific tool locally."""
        binary_names = {
            ToolName.ANSIBLE: "ansible",
            ToolName.TERRAFORM: "terraform",
            ToolName.KUBECTL: "kubectl",
            ToolName.GIT: "git",
            ToolName.DOCKER: "docker",
            ToolName.HELM: "helm",
        }

        binary = binary_names.get(tool)
        if not binary:
            return ToolCapability(name=tool, installed=False)

        # Check if binary exists
        path = shutil.which(binary)
        if not path:
            return ToolCapability(name=tool, installed=False)

        # Get version
        version = await self._get_local_tool_version(tool)

        # Check config
        config_valid = await self._check_local_tool_config(tool)

        return ToolCapability(
            name=tool,
            installed=True,
            version=version,
            config_valid=config_valid,
        )

    async def _get_local_tool_version(self, tool: ToolName) -> str | None:
        """Get version of a local tool."""
        version_commands = {
            ToolName.ANSIBLE: ["ansible", "--version"],
            ToolName.TERRAFORM: ["terraform", "version"],
            ToolName.KUBECTL: ["kubectl", "version", "--client", "-o", "json"],
            ToolName.GIT: ["git", "--version"],
            ToolName.DOCKER: ["docker", "--version"],
            ToolName.HELM: ["helm", "version", "--short"],
        }

        version_patterns = {
            ToolName.ANSIBLE: r"ansible.*(\d+\.\d+\.\d+)",
            ToolName.TERRAFORM: r"v(\d+\.\d+\.\d+)",
            ToolName.KUBECTL: r'"gitVersion":\s*"v(\d+\.\d+\.\d+)"',
            ToolName.GIT: r"git version (\d+\.\d+\.\d+)",
            ToolName.DOCKER: r"Docker version (\d+\.\d+\.\d+)",
            ToolName.HELM: r"v(\d+\.\d+\.\d+)",
        }

        cmd = version_commands.get(tool)
        pattern = version_patterns.get(tool)

        if not cmd or not pattern:
            return None

        try:
            result = subprocess.run(  # nosec B603 - cmd is validated
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
            )
            import re

            match = re.search(pattern, result.stdout)
            return match.group(1) if match else None
        except Exception:
            return None

    async def _check_local_tool_config(self, tool: ToolName) -> bool:
        """Check if local tool configuration is valid."""
        checks = {
            ToolName.KUBECTL: ["kubectl", "config", "current-context"],
            ToolName.GIT: ["git", "rev-parse", "--git-dir"],
            ToolName.DOCKER: ["docker", "info"],
        }

        cmd = checks.get(tool)
        if not cmd:
            return True  # No config check

        try:
            result = subprocess.run(  # nosec B603 - cmd is predefined
                cmd,
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    @classmethod
    def reset_instance(cls) -> None:
        """Reset for tests (if used as singleton)."""
        pass  # Not a singleton, but provides interface for test compatibility
