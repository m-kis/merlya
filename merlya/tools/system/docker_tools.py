"""
Merlya Tools - System Docker tools module.

Provides Docker container monitoring tools.
Security: All user inputs are sanitized with shlex.quote() to prevent command injection.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from merlya.tools.core import ToolResult, ssh_execute

if TYPE_CHECKING:
    from merlya.core.context import SharedContext


async def check_docker(
    ctx: SharedContext,
    host: str,
) -> ToolResult:
    """
    Check Docker status and containers.

    Args:
        ctx: Shared context.
        host: Host name.

    Returns:
        ToolResult with Docker info.
    """
    # Check if Docker is available and get container info
    cmd = """
    if ! command -v docker >/dev/null 2>&1; then
        echo "DOCKER:not-installed"
        exit 0
    fi

    # Check if Docker daemon is running
    if ! docker info >/dev/null 2>&1; then
        echo "DOCKER:not-running"
        exit 0
    fi

    echo "DOCKER:running"
    echo "CONTAINERS:"
    docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null | head -20
    echo "IMAGES:"
    docker images --format '{{.Repository}}:{{.Tag}}|{{.Size}}' 2>/dev/null | head -10
    """

    # Sanitize host parameter to prevent command injection
    safe_host = shlex.quote(host)
    result = await ssh_execute(ctx, safe_host, cmd.strip(), timeout=20)

    # If SSH execution failed, return failure with error details
    if not result.success:
        return ToolResult(
            success=False,
            data={
                "host": host,
                "error": result.error,
                "ssh_stderr": result.data.get("stderr") if result.data else None,
                "ssh_exit_code": result.data.get("exit_code") if result.data else None,
            },
            error=result.error or "SSH execution failed",
        )

    docker_status = "unknown"
    containers: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    section = None

    if result.data and result.data.get("stdout"):
        for line in result.data["stdout"].strip().split("\n"):
            if line.startswith("DOCKER:"):
                docker_status = line.split(":", 1)[1]
            elif line == "CONTAINERS:":
                section = "containers"
            elif line == "IMAGES:":
                section = "images"
            elif section == "containers" and "|" in line:
                parts = line.split("|")
                if len(parts) >= 3:
                    containers.append(
                        {
                            "name": parts[0],
                            "status": parts[1],
                            "image": parts[2],
                        }
                    )
            elif section == "images" and "|" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    images.append(
                        {
                            "name": parts[0],
                            "size": parts[1],
                        }
                    )

    # Count running vs stopped containers
    running = sum(1 for c in containers if "Up" in c.get("status", ""))
    stopped = len(containers) - running

    return ToolResult(
        success=True,
        data={
            "status": docker_status,
            "containers": containers,
            "images": images,
            "running_count": running,
            "stopped_count": stopped,
            "total_containers": len(containers),
            "ssh_exit_code": result.data.get("exit_code") if result.data else 0,
        },
    )
