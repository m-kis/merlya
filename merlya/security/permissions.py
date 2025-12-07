"""
Privilege elevation manager.

Detects sudo/doas/su capabilities and prepares elevated commands when needed.
Inspired by legacy implementation but simplified for the current Merlya stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class ElevationResult:
    """Result of preparing an elevated command."""

    command: str
    input_data: str | None
    method: str | None
    note: str | None = None
    needs_password: bool = False
    base_command: str | None = None


class PermissionManager:
    """Manage privilege elevation for SSH commands."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._cache: dict[str, dict[str, Any]] = {}

    async def detect_capabilities(self, host: str) -> dict[str, Any]:
        """Detect elevation capabilities on a host (cached)."""
        if host in self._cache:
            logger.debug(f"🔍 Using cached permission capabilities for {host}")
            return self._cache[host]

        capabilities: dict[str, Any] = {
            "user": "unknown",
            "is_root": False,
            "groups": [],
            "has_sudo": False,
            "sudo_nopasswd": False,
            "has_su": False,
            "has_doas": False,
            "has_privileged_group": False,
            "privileged_groups": [],
            "elevation_method": None,
        }

        async def _run(cmd: str) -> tuple[bool, str]:
            try:
                result = await self._execute(host, cmd)
                return result.exit_code == 0, result.stdout.strip()
            except Exception as exc:  # noqa: PERF203
                logger.debug(f"Permission probe failed on {host}: {cmd} ({exc})")
                return False, ""

        ok, user = await _run("whoami")
        if ok:
            capabilities["user"] = user
            capabilities["is_root"] = user == "root"

        ok, groups = await _run("groups")
        if ok and groups:
            capabilities["groups"] = groups.split()

        privileged = {"wheel", "admin", "sudo", "root"}
        group_set = set(capabilities["groups"])
        capabilities["has_privileged_group"] = bool(group_set & privileged)
        capabilities["privileged_groups"] = list(group_set & privileged)

        ok, sudo_path = await _run("which sudo")
        if ok and sudo_path:
            capabilities["has_sudo"] = True
            ok, _ = await _run("sudo -n true")
            if ok:
                capabilities["sudo_nopasswd"] = True
                capabilities["elevation_method"] = "sudo"
            else:
                # sudo present but needs password
                capabilities["elevation_method"] = "sudo_with_password"

        ok, doas_path = await _run("which doas")
        if ok and doas_path and not capabilities["elevation_method"]:
            capabilities["has_doas"] = True
            capabilities["elevation_method"] = "doas"

        ok, su_path = await _run("which su")
        if ok and su_path:
            capabilities["has_su"] = True
            # Prefer su over sudo_with_password to avoid prompting before trying su
            if not capabilities["elevation_method"] or capabilities["elevation_method"] == "sudo_with_password":
                capabilities["elevation_method"] = "su"

        if capabilities["is_root"]:
            capabilities["elevation_method"] = "none"

        self._cache[host] = capabilities
        logger.info(
            "🔒 Permissions for {host}: user={user}, sudo={sudo}, method={method}",
            host=host,
            user=capabilities["user"],
            sudo="yes" if capabilities["has_sudo"] else "no",
            method=capabilities["elevation_method"] or "none",
        )
        return capabilities

    def requires_elevation(self, command: str) -> bool:
        """Heuristically determine if a command likely needs elevation."""
        root_cmds = [
            "systemctl",
            "service",
            "apt",
            "yum",
            "dnf",
            "pacman",
            "useradd",
            "userdel",
            "groupadd",
            "visudo",
            "iptables",
            "firewall-cmd",
            "ufw",
            "mount",
            "umount",
            "fdisk",
            "parted",
            "reboot",
            "shutdown",
            "halt",
            "poweroff",
        ]
        root_paths = ["/etc/", "/var/log/", "/root/", "/sys/", "/proc/sys/", "/usr/sbin/", "/sbin/"]
        protected_reads = [
            "/etc/shadow",
            "/etc/gshadow",
            "/etc/sudoers",
            "/var/log/auth.log",
            "/var/log/secure",
        ]

        cmd_lower = command.lower()
        for root_cmd in root_cmds:
            if cmd_lower.startswith(root_cmd) or f" {root_cmd} " in cmd_lower:
                return True

        for path in root_paths:
            if path in command and any(op in command for op in [">", ">>", "tee", "mv", "cp", "rm", "mkdir", "touch", "chmod", "chown"]):
                return True

        for p in protected_reads:
            if p in command and any(cmd_lower.startswith(f"{r} ") or f" {r} " in cmd_lower for r in ["cat", "tail", "head", "grep", "awk", "sed"]):
                return True

        return False

    async def prepare_command(
        self,
        host: str,
        command: str,
    ) -> ElevationResult:
        """
        Prepare an elevated command if needed (asks user confirmation).
        """
        caps = await self.detect_capabilities(host)
        if caps.get("is_root") or caps.get("elevation_method") == "none":
            return ElevationResult(
                command=command,
                input_data=None,
                method=None,
                note="already_root",
                base_command=command,
            )

        method = caps.get("elevation_method")
        if not method:
            return ElevationResult(
                command=command,
                input_data=None,
                method=None,
                note="no_elevation_available",
            )

        confirm = await self.ctx.ui.prompt_confirm(
            f"🔒 Command may require elevation on {host}. Use {method}?",
            default=False,
        )
        if not confirm:
            return ElevationResult(command=command, input_data=None, method=None, note="user_declined", base_command=command)

        password: str | None = None
        needs_password = method in ("sudo_with_password", "su")

        # First attempt will be passwordless (sudo -n or su without input). Caller can retry with password if needed.
        elevated_command, input_data = self._elevate_command(command, caps, method, password)
        return ElevationResult(
            command=elevated_command,
            input_data=input_data,
            method=method,
            note="password_optional" if needs_password else None,
            needs_password=needs_password,
            base_command=command,
        )

    def _elevate_command(
        self,
        command: str,
        capabilities: dict[str, Any],
        method: str,
        password: str | None = None,
    ) -> tuple[str, str | None]:
        """Prefix command with the chosen elevation method."""
        if capabilities.get("is_root"):
            return command, None

        stripped = command.strip()
        if stripped.startswith(("sudo ", "doas ", "su ", "su-")):
            return command, None

        if method == "sudo":
            return f"sudo -n {command}", None
        if method == "sudo_with_password":
            if password:
                return f"sudo -S -p '' {command}", f"{password}\n"
            return f"sudo -n {command}", None
        if method == "doas":
            return f"doas {command}", None
        if method == "su":
            escaped = command.replace("'", "'\"'\"'")
            return f"su -c '{escaped}'", f"{password}\n" if password else None

        logger.warning(f"⚠️ Unknown elevation method {method}, running without elevation")
        return command, None

    async def _execute(self, host: str, command: str):
        """Execute a probe command using the shared SSH pool."""
        ssh_pool = await self.ctx.get_ssh_pool()
        return await ssh_pool.execute(host=host, command=command, timeout=10, connect_timeout=10)
