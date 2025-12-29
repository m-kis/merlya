"""
Merlya Fingerprint - Semantic Signature Extractor.

Uses pattern matching with optional LLM fallback to extract
semantic signatures from commands.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal

from merlya.fingerprint.models import FingerprintResult, SemanticSignature

# Type alias for risk levels
RiskLevel = Literal["low", "medium", "high", "critical"]

if TYPE_CHECKING:
    from merlya.fingerprint.cache import FingerprintCache


class SemanticSignatureExtractor:
    """
    Extracts semantic signatures from commands.

    Uses pattern-based extraction for common commands with
    optional LLM fallback for complex cases.
    """

    def __init__(
        self,
        cache: FingerprintCache | None = None,
    ):
        """
        Initialize extractor.

        Args:
            cache: Optional cache for approval lookups.
        """
        self._cache = cache

    async def extract(self, command: str) -> FingerprintResult:
        """
        Extract semantic signature from a command.

        Args:
            command: The command to analyze.

        Returns:
            FingerprintResult with signature and approval status.
        """
        # Try pattern-based extraction first
        signature = self._extract_pattern(command)

        # Check cache for prior approval
        cached_approval = None
        if self._cache is not None:
            cached_approval = self._cache.get(signature)

        requires_new_approval = cached_approval is None or not cached_approval.approved

        return FingerprintResult(
            signature=signature,
            cached_approval=cached_approval,
            requires_new_approval=requires_new_approval,
        )

    def _extract_pattern(self, command: str) -> SemanticSignature:
        """
        Extract signature using pattern matching.

        Args:
            command: Command to analyze.

        Returns:
            SemanticSignature from pattern matching.
        """
        command = command.strip()

        # HTTP request patterns (curl, wget, etc.)
        curl_match = self._match_curl(command)
        if curl_match:
            return curl_match

        wget_match = self._match_wget(command)
        if wget_match:
            return wget_match

        # Service management patterns
        service_match = self._match_service(command)
        if service_match:
            return service_match

        # File operation patterns
        file_match = self._match_file_ops(command)
        if file_match:
            return file_match

        # Package management patterns
        package_match = self._match_package(command)
        if package_match:
            return package_match

        # Process management patterns
        process_match = self._match_process(command)
        if process_match:
            return process_match

        # Default fallback
        return self._create_generic_signature(command)

    def _match_curl(self, command: str) -> SemanticSignature | None:
        """Match curl commands."""
        if not command.startswith("curl"):
            return None

        # Extract HTTP verb
        verb = "GET"
        verb_match = re.search(r"-X\s+(\w+)", command)
        if verb_match:
            verb = verb_match.group(1).upper()

        # Extract URL
        url_match = re.search(r"https?://[^\s'\"]+", command)
        url = url_match.group(0) if url_match else "unknown"

        # Extract host from URL
        host_match = re.search(r"https?://([^/:]+)", url)
        host = host_match.group(1) if host_match else "unknown"

        # Assess risk based on verb
        risk = self._assess_http_risk(verb)

        # Normalize template
        template = f"curl -X {{{verb.lower()}}} {{url}}"
        if "-d" in command or "--data" in command:
            template += " -d {data}"

        return SemanticSignature(
            action_type="http_request",
            verb=verb,
            targets=[host],
            risk_level=risk,
            normalized_template=template,
            original_command=command,
        )

    def _match_wget(self, command: str) -> SemanticSignature | None:
        """Match wget commands."""
        if not command.startswith("wget"):
            return None

        # Extract URL
        url_match = re.search(r"https?://[^\s'\"]+", command)
        url = url_match.group(0) if url_match else "unknown"

        # Extract host
        host_match = re.search(r"https?://([^/:]+)", url)
        host = host_match.group(1) if host_match else "unknown"

        return SemanticSignature(
            action_type="http_request",
            verb="GET",
            targets=[host],
            risk_level="low",
            normalized_template="wget {url}",
            original_command=command,
        )

    def _match_service(self, command: str) -> SemanticSignature | None:
        """Match service management commands."""
        patterns = [
            (r"systemctl\s+(start|stop|restart|reload|enable|disable)\s+(\S+)", "systemctl"),
            (r"service\s+(\S+)\s+(start|stop|restart|reload)", "service"),
        ]

        for pattern, cmd_type in patterns:
            match = re.search(pattern, command)
            if match:
                if cmd_type == "systemctl":
                    action, service = match.groups()
                else:
                    service, action = match.groups()

                risk = self._assess_service_risk(action)

                return SemanticSignature(
                    action_type="service_management",
                    verb=action,
                    targets=[service],
                    risk_level=risk,
                    normalized_template=f"systemctl {{{action}}} {{service}}",
                    original_command=command,
                )

        return None

    def _match_file_ops(self, command: str) -> SemanticSignature | None:
        """Match file operation commands."""
        patterns = [
            (r"^rm\s+(-[rf]+\s+)?(.+)$", "delete", "high"),
            (r"^mv\s+(\S+)\s+(\S+)$", "move", "medium"),
            (r"^cp\s+(-[r]+\s+)?(\S+)\s+(\S+)$", "copy", "low"),
            (r"^chmod\s+([0-7]+|[ugoa]+[+-=][rwx]+)\s+(.+)$", "permission_change", "high"),
            (r"^chown\s+(\S+)\s+(.+)$", "ownership_change", "high"),
            (r"^cat\s+.+\s*>\s*(\S+)$", "file_write", "medium"),
            (r"^echo\s+.+\s*>\s*(\S+)$", "file_write", "medium"),
            (r"^tee\s+(\S+)$", "file_write", "medium"),
        ]

        for pattern, action_type, risk in patterns:
            match = re.search(pattern, command)
            if match:
                # Extract target path(s)
                targets = [g for g in match.groups() if g and not g.startswith("-")]

                return SemanticSignature(
                    action_type=f"file_{action_type}",
                    verb=action_type,
                    targets=targets,
                    risk_level=risk,  # type: ignore
                    normalized_template=f"{command.split()[0]} {{path}}",
                    original_command=command,
                )

        return None

    def _match_package(self, command: str) -> SemanticSignature | None:
        """Match package management commands."""
        patterns = [
            (r"^(apt|apt-get)\s+(install|remove|purge)\s+(.+)$", "apt"),
            (r"^(yum|dnf)\s+(install|remove|erase)\s+(.+)$", "yum"),
            (r"^pip\s+install\s+(.+)$", "pip"),
            (r"^npm\s+install\s+(.+)$", "npm"),
        ]

        for pattern, pkg_type in patterns:
            match = re.search(pattern, command)
            if match:
                groups = match.groups()

                if pkg_type in ("apt", "yum"):
                    action = groups[1]
                    packages = groups[2].split()
                else:
                    action = "install"
                    packages = groups[0].split() if groups else []

                risk = "high" if action in ("remove", "purge", "erase") else "medium"

                return SemanticSignature(
                    action_type="package_management",
                    verb=action,
                    targets=packages,
                    risk_level=risk,  # type: ignore
                    normalized_template=f"{pkg_type} {action} {{package}}",
                    original_command=command,
                )

        return None

    def _match_process(self, command: str) -> SemanticSignature | None:
        """Match process management commands."""
        patterns = [
            (r"^kill\s+(-\d+\s+)?(\d+)$", "kill"),
            (r"^pkill\s+(-\d+\s+)?(\S+)$", "pkill"),
            (r"^killall\s+(-\d+\s+)?(\S+)$", "killall"),
        ]

        for pattern, cmd_type in patterns:
            match = re.search(pattern, command)
            if match:
                signal = match.group(1).strip("-").strip() if match.group(1) else "15"
                target = match.group(2)

                # SIGKILL (9) is critical
                risk = "critical" if signal == "9" else "high"

                return SemanticSignature(
                    action_type="process_management",
                    verb="kill",
                    targets=[target],
                    risk_level=risk,  # type: ignore
                    normalized_template=f"{cmd_type} -{{signal}} {{target}}",
                    original_command=command,
                )

        return None

    def _create_generic_signature(self, command: str) -> SemanticSignature:
        """Create a generic signature for unrecognized commands."""
        cmd_parts = command.split()
        cmd_name = cmd_parts[0] if cmd_parts else "unknown"

        # Default risk assessment based on common dangerous commands
        high_risk = ["rm", "dd", "mkfs", "fdisk", "shutdown", "reboot", "halt"]
        medium_risk = ["mv", "cp", "chmod", "chown", "sed", "awk"]

        if cmd_name in high_risk:
            risk = "high"
        elif cmd_name in medium_risk:
            risk = "medium"
        else:
            risk = "low"

        return SemanticSignature(
            action_type="shell_command",
            verb=cmd_name,
            targets=[],
            risk_level=risk,  # type: ignore
            normalized_template=f"{cmd_name} {{args}}",
            original_command=command,
        )

    def _assess_http_risk(self, verb: str) -> RiskLevel:
        """Assess risk level for HTTP operations."""
        if verb in ("DELETE", "PUT", "PATCH"):
            return "high"
        if verb == "POST":
            return "medium"
        return "low"

    def _assess_service_risk(self, action: str) -> RiskLevel:
        """Assess risk level for service operations."""
        if action in ("stop", "disable"):
            return "high"
        if action in ("restart", "reload"):
            return "medium"
        return "low"
