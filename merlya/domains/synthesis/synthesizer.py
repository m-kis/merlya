"""
Result Synthesizer - DDD Domain Service.

Orchestrates the synthesis of execution results into final user-facing output.
Uses MetricsParser and MetricsAnalyzer to generate comprehensive reports.
"""
from .analyzers import MetricsAnalyzer
from .parsers import MetricsParser


class ResultSynthesizer:
    """
    Domain Service for synthesizing execution results into final output.

    Coordinates parsing, analysis, and report generation.
    """

    def __init__(self):
        """Initialize the synthesizer with parser and analyzer."""
        self.parser = MetricsParser()
        self.analyzer = MetricsAnalyzer()

    def synthesize_results(self, plan, original_query: str) -> str:
        """
        Synthesize all step results into final response with intelligent analysis.

        This method automatically parses command outputs, extracts metrics,
        analyzes values, and generates actionable recommendations.

        Args:
            plan: Executed plan
            original_query: Original user query

        Returns:
            Final synthesized response with intelligent analysis
        """
        # Collect all successful results
        successful_steps = [
            step for step in plan.steps
            if step.status.value == "completed" and step.result
        ]

        # Check if all steps failed
        if not successful_steps:
            return self.synthesize_failure(plan, original_query)

        # Extract target hostname from results
        target_host = None
        for step in successful_steps:
            if step.result and step.result.get("output"):
                output = step.result["output"]
                if isinstance(output, dict) and "target" in output:
                    target_host = output["target"]
                    break

        # Build report header (Markdown format)
        report_lines = []
        report_lines.append("")
        if target_host:
            report_lines.append(f"# 📊 Analyse: **{target_host.upper()}**")
        else:
            report_lines.append(f"# 📊 Analyse: **{original_query[:40].upper()}**")
        report_lines.append("")

        # Collect and parse all analysis results
        metrics = self.parser.parse_analysis_results(successful_steps)

        # Extract raw command results for detailed presentation
        raw_results = []
        for step in successful_steps:
            if step.result and step.result.get("output"):
                output = step.result["output"]
                if isinstance(output, dict) and "analysis_results" in output:
                    raw_results = output["analysis_results"]
                    break

        # Generate findings section with Markdown title
        report_lines.append("## 📈 Résultats")
        report_lines.append("")

        if metrics:
            # System metrics
            if "uptime_days" in metrics or "load_avg" in metrics:
                uptime_status = self.analyzer.analyze_uptime(metrics)
                report_lines.append(uptime_status)

            if "disk_usage" in metrics:
                disk_status = self.analyzer.analyze_disk(metrics)
                report_lines.append(disk_status)

            # Service status
            if "service_status" in metrics:
                service_status = self.analyzer.analyze_service(metrics)
                report_lines.append(service_status)

            # Process info
            if "process_info" in metrics:
                process_status = self.analyzer.analyze_process(metrics)
                report_lines.append(process_status)

            # Infrastructure summary
            if "host_count" in metrics:
                report_lines.append(f"📋 Infrastructure: {metrics['host_count']} hosts available")

        # Always show detailed findings from commands
        if raw_results:
            findings = self._extract_key_findings(raw_results, original_query)
            if findings:
                report_lines.append("")
                report_lines.append("### 🔍 Détails")
                report_lines.append("")
                for finding in findings:
                    report_lines.append(f"- {finding}")

        if not metrics and not raw_results:
            # No data at all
            report_lines.append("ℹ️  Analysis completed successfully")
            for step in successful_steps[:3]:
                msg = step.result.get('message', 'Done')[:50]
                report_lines.append(f"  • {msg}")

        # Recommendations (Markdown format)
        recommendations = self.analyzer.generate_recommendations(metrics)
        if recommendations:
            report_lines.append("")
            report_lines.append("## 💡 Recommandations")
            report_lines.append("")
            for rec in recommendations:
                report_lines.append(f"- {rec}")

        report_lines.append("")
        return "\n".join(report_lines)

    def _extract_key_findings(self, raw_results: list, query: str) -> list:
        """
        Extract key findings from raw command results.

        Args:
            raw_results: List of command execution results
            query: Original user query for context

        Returns:
            List of key findings as strings
        """
        findings = []
        query_lower = query.lower()

        for result_item in raw_results:
            command = result_item.get("command", "")
            result = result_item.get("result", "")

            # Skip failed commands
            if "FAILED" in result or not result:
                continue

            # Extract output content
            output = ""
            if "Output:" in result:
                output = result.split("Output:", 1)[1].strip()

            # Query-specific extraction
            if "backup" in query_lower:
                # Look for backup scripts
                if "/backup" in output or "backup" in output.lower():
                    lines = output.split("\n")
                    for line in lines:
                        if "backup" in line.lower() and line.strip():
                            # Clean up the line
                            if ("CRON" in line or "cron" in line) and "CMD" in line:
                                # Extract script path from cron log
                                # Format: CRON[pid]: (user) CMD (script)
                                if "/" in line:
                                    # Find the last ( before )
                                    parts = line.split("CMD")
                                    if len(parts) > 1:
                                        cmd_part = parts[1].strip()
                                        # Remove surrounding parentheses
                                        if cmd_part.startswith("(") and cmd_part.endswith(")"):
                                            script = cmd_part[1:-1]
                                            if "/" in script:
                                                findings.append(f"✅ Script backup: `{script}`")
                            elif line.startswith("-") or line.startswith("total"):
                                # File listing
                                findings.append(f"Fichier: {line.strip()}")
                            elif "backup" in line and "/" in line and len(line) < 200:
                                findings.append(f"Référence: {line.strip()}")

            # Generic extraction for service checks
            if "systemctl" in command and "active" in output:
                findings.append(f"Service actif détecté dans: `{command}`")

            # Process detection
            if "ps aux" in command and output and "grep" not in output.split("\n")[-1]:
                proc_lines = [line for line in output.split("\n") if line.strip() and "grep" not in line]
                if len(proc_lines) > 0:
                    findings.append(f"Processus trouvé: {len(proc_lines)} instance(s)")

            # Cron jobs
            if "crontab" in command and output:
                findings.append(f"Cron job configuré: {output[:100]}")

        # Remove duplicates while preserving order
        seen = set()
        unique_findings = []
        for f in findings:
            if f not in seen:
                seen.add(f)
                unique_findings.append(f)

        return unique_findings[:10]  # Limit to 10 findings

    def synthesize_failure(self, plan, original_query: str) -> str:
        """
        Synthesize failure message when all steps failed.

        Provides intelligent diagnosis and suggestions based on error patterns.

        Args:
            plan: Executed plan
            original_query: Original user query

        Returns:
            Failure message with diagnosis and suggestions
        """
        # Collect all error messages
        errors = []
        for step in plan.steps:
            if step.status.value == "failed" and step.result:
                error = step.result.get("error", "Unknown error")
                errors.append(error)

        # Build failure report
        report_lines = []
        report_lines.append("")
        report_lines.append("# ❌ Analyse Failed")
        report_lines.append("")
        report_lines.append(f"Query: *{original_query}*")
        report_lines.append("")

        # Intelligent error diagnosis
        error_text = " ".join(errors).lower()

        if "circuit breaker" in error_text or "permanently unreachable" in error_text:
            report_lines.append("## 🚫 Circuit Breaker Triggered")
            report_lines.append("")
            report_lines.append("The target host has failed multiple connection attempts.")
            report_lines.append("")
            report_lines.append("**Possible causes:**")
            report_lines.append("- Host is down or unreachable")
            report_lines.append("- DNS resolution failure")
            report_lines.append("- Network connectivity issues")
            report_lines.append("- Firewall blocking SSH")

        elif "clarification" in error_text:
            report_lines.append("## ❓ Clarification Needed")
            report_lines.append("")
            report_lines.append("Could not determine target host from your query.")
            report_lines.append("")
            report_lines.append("**Try:**")
            report_lines.append("- Specify the hostname explicitly")
            report_lines.append("- Use 'merlya list' to see available hosts")

        elif "authentication" in error_text or "permission" in error_text:
            report_lines.append("## 🔐 Authentication Issue")
            report_lines.append("")
            report_lines.append("Failed to authenticate to target host.")
            report_lines.append("")
            report_lines.append("**Check:**")
            report_lines.append("- SSH keys are properly configured")
            report_lines.append("- User has appropriate permissions")

        else:
            report_lines.append("## ⚠️  Execution Error")
            report_lines.append("")
            for i, error in enumerate(errors[:3], 1):
                report_lines.append(f"{i}. {error[:100]}")

        report_lines.append("")
        return "\n".join(report_lines)
