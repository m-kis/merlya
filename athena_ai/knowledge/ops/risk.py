from typing import List, Tuple


class RiskAssessor:
    """Assess risk of operations."""

    def assess_command_risk(self, commands: List[str]) -> Tuple[str, bool]:
        """
        Assess the risk level of a list of commands.

        Returns:
            (risk_level, auto_executable) tuple
        """
        if not commands:
            return "low", True

        # High risk patterns
        high_risk_patterns = [
            "rm -rf", "rm -r", "dd if=", "mkfs", "fdisk",
            ":(){:|:&};:", "chmod -R 777", "> /dev/sd",
            "DROP TABLE", "DROP DATABASE", "TRUNCATE",
            "shutdown", "reboot", "halt", "init 0",
            "kill -9", "pkill -9", "killall",
        ]

        # Medium risk patterns
        medium_risk_patterns = [
            "systemctl stop", "systemctl restart", "service stop",
            "docker rm", "docker stop", "kubectl delete",
            "rm ", "mv ", "cp ", "chmod", "chown",
            "apt remove", "yum remove", "pip uninstall",
            "UPDATE ", "DELETE FROM",
        ]

        # Safe patterns (read-only, diagnostic)
        safe_patterns = [
            "systemctl status", "service status", "ps ", "top",
            "df ", "du ", "ls ", "cat ", "grep ", "tail ",
            "docker ps", "docker logs", "kubectl get",
            "SELECT ", "SHOW ", "DESCRIBE ",
            "ping ", "curl ", "wget ", "nc ",
        ]

        risk_level = "low"
        auto_executable = True

        for cmd in commands:
            cmd_lower = cmd.lower()

            # Check high risk
            for pattern in high_risk_patterns:
                if pattern.lower() in cmd_lower:
                    return "high", False

            # Check medium risk
            for pattern in medium_risk_patterns:
                if pattern.lower() in cmd_lower:
                    risk_level = "medium"
                    auto_executable = False

            # Check if it's a known safe command
            is_safe = any(pattern.lower() in cmd_lower for pattern in safe_patterns)
            if not is_safe and risk_level == "low":
                # Unknown command - treat as medium risk
                risk_level = "medium"

        return risk_level, auto_executable
