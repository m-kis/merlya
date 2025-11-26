"""
Metrics Analyzer - DDD Domain Service.

Responsible for:
- Analyzing parsed metrics
- Generating human-readable status lines
- Generating actionable recommendations
"""
from typing import Dict, Any, List


class MetricsAnalyzer:
    """
    Domain Service for analyzing metrics and generating insights.

    Converts raw metrics into user-friendly status and recommendations.
    """

    def analyze_uptime(self, metrics: Dict[str, Any]) -> str:
        """
        Generate uptime analysis line.

        Args:
            metrics: Parsed metrics dictionary

        Returns:
            Formatted uptime status string
        """
        parts = []

        if "uptime_days" in metrics:
            days = metrics["uptime_days"]
            if days > 365:
                status = "✅"
                comment = "excellent"
            elif days > 30:
                status = "✅"
                comment = "good"
            elif days > 7:
                status = "✅"
                comment = "stable"
            else:
                status = "⚠️ "
                comment = "recent reboot"
            parts.append(f"{status} Uptime: {days} days ({comment})")

        if "load_avg" in metrics:
            load = metrics["load_avg"]["1min"]
            if load < 1.0:
                status = "✅"
                comment = "very low"
            elif load < 2.0:
                status = "✅"
                comment = "normal"
            elif load < 4.0:
                status = "⚠️ "
                comment = "moderate"
            else:
                status = "❌"
                comment = "high"
            parts.append(f"{status} Load: {load:.2f} ({comment})")

        return " | ".join(parts)

    def analyze_disk(self, metrics: Dict[str, Any]) -> str:
        """
        Generate disk analysis line.

        Args:
            metrics: Parsed metrics dictionary

        Returns:
            Formatted disk status string
        """
        disk_info = metrics.get("disk_usage", [])
        if not disk_info:
            return ""

        # Analyze root filesystem or first one
        primary_disk = disk_info[0]
        usage = primary_disk["usage_percent"]
        avail = primary_disk.get("available", "?")

        if usage < 50:
            status = "✅"
            comment = "plenty of space"
        elif usage < 75:
            status = "✅"
            comment = "adequate"
        elif usage < 90:
            status = "⚠️ "
            comment = "monitor closely"
        else:
            status = "❌"
            comment = "critical"

        return f"{status} Disk: {usage}% used ({avail} free) - {comment}"

    def analyze_service(self, metrics: Dict[str, Any]) -> str:
        """
        Generate service status line.

        Args:
            metrics: Parsed metrics dictionary

        Returns:
            Formatted service status string
        """
        service = metrics.get("service_status", {})
        name = service.get("name", "service")

        if service.get("active"):
            status = "✅"
            comment = "running"
        elif service.get("failed"):
            status = "❌"
            comment = "failed"
        else:
            status = "⚠️ "
            comment = "unknown"

        return f"{status} Service {name}: {comment}"

    def analyze_process(self, metrics: Dict[str, Any]) -> str:
        """
        Generate process status line.

        Args:
            metrics: Parsed metrics dictionary

        Returns:
            Formatted process status string
        """
        process = metrics.get("process_info", {})
        name = process.get("name", "process")

        if process.get("running"):
            status = "✅"
            comment = "active"
        else:
            status = "❌"
            comment = "not found"

        return f"{status} Process {name}: {comment}"

    def generate_recommendations(self, metrics: Dict[str, Any]) -> List[str]:
        """
        Generate actionable recommendations based on metrics.

        Args:
            metrics: Parsed metrics dictionary

        Returns:
            List of recommendation strings
        """
        recommendations = []

        # Check disk usage
        if "disk_usage" in metrics:
            for disk in metrics["disk_usage"]:
                usage = disk["usage_percent"]
                if usage >= 90:
                    recommendations.append(f"URGENT: Clean up disk space on {disk['mount']} (current: {usage}%)")
                elif usage >= 75:
                    recommendations.append(f"Consider cleaning disk space on {disk['mount']} (current: {usage}%)")

        # Check load average
        if "load_avg" in metrics:
            load = metrics["load_avg"]["1min"]
            if load > 4.0:
                recommendations.append("High load detected - investigate running processes")
            elif load > 2.0:
                recommendations.append("Moderate load - monitor system performance")

        # Check service status
        if "service_status" in metrics:
            service = metrics["service_status"]
            if service.get("failed"):
                recommendations.append(f"Service {service['name']} is down - restart required")
            elif not service.get("active"):
                recommendations.append(f"Verify {service['name']} service status")

        # Check process
        if "process_info" in metrics:
            process = metrics["process_info"]
            if not process.get("running"):
                recommendations.append(f"Process {process['name']} not running - investigate")

        # All good case
        if not recommendations:
            if "uptime_days" in metrics or "disk_usage" in metrics:
                recommendations.append("System is healthy - no action needed")

        return recommendations
