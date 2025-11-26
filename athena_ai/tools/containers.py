"""
Container operation tools.
"""
from typing import Annotated

from athena_ai.tools.base import get_tool_context, validate_host
from athena_ai.utils.logger import logger


def docker_exec(
    container: Annotated[str, "Container name or ID"],
    command: Annotated[str, "Command to execute"],
    host: Annotated[str, "Docker host (use 'local' for local)"] = "local"
) -> str:
    """
    Execute command in a Docker container.

    Args:
        container: Container name or ID
        command: Command to run
        host: Docker host (default: local)

    Returns:
        Command output
    """
    ctx = get_tool_context()
    logger.info(f"Tool: docker_exec {container} on {host}")

    if host != "local":
        is_valid, msg = validate_host(host)
        if not is_valid:
            return f"❌ BLOCKED: {msg}\n\n💡 Use list_hosts()"

    cmd = f"docker exec {container} sh -c '{command}'"
    result = ctx.executor.execute(host, cmd, confirm=True)

    if result['success']:
        return f"✅ docker exec {container}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"


def kubectl_exec(
    namespace: Annotated[str, "Kubernetes namespace"],
    pod: Annotated[str, "Pod name"],
    command: Annotated[str, "Command to execute"],
    container: Annotated[str, "Container name (if multiple)"] = ""
) -> str:
    """
    Execute command in a Kubernetes pod.

    Args:
        namespace: Namespace
        pod: Pod name
        command: Command
        container: Container name (optional)

    Returns:
        Command output
    """
    ctx = get_tool_context()
    logger.info(f"Tool: kubectl_exec {namespace}/{pod}")

    container_flag = f"-c {container}" if container else ""
    cmd = f"kubectl exec -n {namespace} {pod} {container_flag} -- sh -c '{command}'"

    result = ctx.executor.execute("local", cmd, confirm=True)

    if result['success']:
        return f"✅ kubectl exec {namespace}/{pod}:\n```\n{result['stdout']}\n```"

    return f"❌ Failed: {result.get('stderr', 'Unknown error')}"
