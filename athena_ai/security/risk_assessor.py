from typing import Dict


class RiskAssessor:
    RISK_LEVELS = {
        'low': [
            'systemctl status', 'ps', 'df', 'cat', 'ls', 'grep', 'uname', 'hostname', 'uptime', 'free'
        ],
        'moderate': [
            'systemctl reload', 'chmod', 'chown', 'touch', 'mkdir'
        ],
        'critical': [
            'systemctl restart', 'systemctl stop', 'rm', 'iptables', 'shutdown', 'reboot', 'dd', 'mkfs'
        ]
    }

    def assess(self, command: str) -> Dict[str, str]:
        """Assess the risk level of a command."""
        command.split()[0]

        # Check for exact matches or starts with
        for level, patterns in self.RISK_LEVELS.items():
            for pattern in patterns:
                if command.startswith(pattern):
                    return {"level": level, "reason": f"Matches pattern: {pattern}"}

        # Default to moderate if unknown
        return {"level": "moderate", "reason": "Unknown command pattern"}

    def requires_confirmation(self, risk_level: str) -> bool:
        return risk_level in ["moderate", "critical"]
