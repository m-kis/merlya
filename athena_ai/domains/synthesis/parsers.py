"""
Metrics Parser - DDD Domain Service.

Responsible for parsing command outputs into structured metrics:
- Uptime and load average
- Disk usage
- Service status (Correction 11: improved parsing)
- Process information (Correction 11: improved parsing)
"""
import re
from typing import Dict, Any
from athena_ai.utils.logger import logger


class MetricsParser:
    """
    Domain Service for parsing command outputs into structured metrics.

    Implements intelligent parsing with fallbacks and validation.
    """

    def parse_analysis_results(self, steps) -> Dict[str, Any]:
        """
        Parse analysis results from step outputs to extract metrics.

        Args:
            steps: List of successful steps

        Returns:
            Dictionary of parsed metrics
        """
        metrics = {}

        for step in steps:
            if not step.result or not step.result.get("output"):
                continue

            output = step.result["output"]

            # Parse infrastructure context
            if "host_count" in output:
                metrics["host_count"] = output["host_count"]

            # Parse analysis results
            if "analysis_results" in output:
                for analysis in output["analysis_results"]:
                    command = analysis.get("command", "")
                    result = analysis.get("result", "")

                    # Parse uptime command
                    if "uptime" in command:
                        self.parse_uptime(result, metrics)

                    # Parse disk usage command
                    elif "df" in command:
                        self.parse_disk_usage(result, metrics)

                    # Parse service status
                    elif "systemctl status" in command or "service" in command:
                        self.parse_service_status(result, metrics, command)

                    # Parse process info
                    elif "ps aux" in command or "ps -ef" in command:
                        self.parse_process_info(result, metrics, command)

        return metrics

    def parse_uptime(self, result: str, metrics: Dict[str, Any]):
        """
        Parse uptime command output.

        Example: "18:54:46 up 221 days, 8:51, 0 user, load average: 0.05, 0.05, 0.03"
        """
        # Extract days
        days_match = re.search(r'up\s+(\d+)\s+day', result)
        if days_match:
            metrics["uptime_days"] = int(days_match.group(1))

        # Extract load average
        load_match = re.search(r'load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', result)
        if load_match:
            metrics["load_avg"] = {
                "1min": float(load_match.group(1)),
                "5min": float(load_match.group(2)),
                "15min": float(load_match.group(3))
            }

    def parse_disk_usage(self, result: str, metrics: Dict[str, Any]):
        """
        Parse df -h command output.

        Example: "/dev/sda1 99G 8.5G 86G 9% /"
        """
        lines = result.split('\n')

        disk_info = []
        root_filesystem = None

        for line in lines:
            # Look for percentage pattern
            percent_match = re.search(r'(\d+)%', line)
            if percent_match:
                usage_percent = int(percent_match.group(1))

                # Extract size info
                parts = line.split()
                if len(parts) >= 5:
                    filesystem = parts[0]
                    size = parts[1] if len(parts) > 1 else "?"
                    used = parts[2] if len(parts) > 2 else "?"
                    avail = parts[3] if len(parts) > 3 else "?"
                    mount = parts[5] if len(parts) > 5 else parts[-1]

                    disk_entry = {
                        "filesystem": filesystem,
                        "usage_percent": usage_percent,
                        "size": size,
                        "used": used,
                        "available": avail,
                        "mount": mount
                    }

                    # Prioritize root filesystem
                    if mount == "/" or filesystem.startswith("/dev/sd") or filesystem.startswith("/dev/vd"):
                        if root_filesystem is None or mount == "/":
                            root_filesystem = disk_entry

                    disk_info.append(disk_entry)

        # Put root filesystem first if found
        if root_filesystem and disk_info:
            # Remove root from list and prepend it
            disk_info = [d for d in disk_info if d != root_filesystem]
            disk_info.insert(0, root_filesystem)

        if disk_info:
            metrics["disk_usage"] = disk_info

    def parse_service_status(self, result: str, metrics: Dict[str, Any], command: str):
        """
        Parse systemctl status output.

        Correction 11: Improved parsing for complex patterns like *backup*.
        """
        # Extract service name from command
        service_name = None

        # Known services
        if "mysql" in command:
            service_name = "mysql"
        elif "nginx" in command:
            service_name = "nginx"
        elif "postgres" in command:
            service_name = "postgres"

        if not service_name:
            # Try to extract from "systemctl status NAME" or "systemctl status *NAME*"
            # Handles: systemctl status backup, systemctl status *backup*
            match = re.search(r'systemctl\s+(?:status|list-units)[\s\|]+[*]?([a-zA-Z0-9_-]+)[*]?', command)
            if match:
                service_name = match.group(1).strip('*')

        # If still not found, skip this metric (don't use placeholder)
        if not service_name or service_name == "service":
            return

        # Check if service is active
        is_active = "active (running)" in result.lower() or "active" in result.lower()
        is_failed = "failed" in result.lower() or "inactive" in result.lower()

        metrics["service_status"] = {
            "name": service_name,
            "active": is_active,
            "failed": is_failed,
            "raw_status": result[:200]  # Keep first 200 chars
        }

    def parse_process_info(self, result: str, metrics: Dict[str, Any], command: str):
        """
        Parse ps aux output.

        Correction 11: Improved parsing for regex patterns like '[b]ackup'.
        """
        # Extract process name from command
        process_name = None

        # Try to extract from various grep patterns:
        # - grep backup
        # - grep -i backup
        # - grep -i '[b]ackup' (regex pattern - extract 'backup')
        # - grep -E 'backup|save'

        # First, try to match bracket patterns like '[b]ackup' -> extract 'backup'
        bracket_match = re.search(r'grep\s+(?:-\w+\s+)?[\'\"]\[(\w)\](\w+)[\'\"]', command)
        if bracket_match:
            # Combine the bracket char with the rest: [b]ackup -> backup
            process_name = bracket_match.group(1) + bracket_match.group(2)

        if not process_name:
            # Try standard patterns: grep -i backup
            simple_match = re.search(r'grep\s+(?:-\w+\s+)?[\'"]?(\w+)[\'"]?', command)
            if simple_match:
                candidate = simple_match.group(1)
                # Skip common flags/commands
                if candidate not in ['aux', 'grep', 'ps', 'i', 'E', 'v']:
                    process_name = candidate

        # If still not found, skip this metric (don't use placeholder)
        if not process_name or process_name == "process" or len(process_name) < 2:
            return

        # Check if process is running
        is_running = "SUCCESS" in result and len(result.strip()) > 50

        metrics["process_info"] = {
            "name": process_name,
            "running": is_running,
            "details": result[:200]
        }
