"""
Example of Chain of Thought Multi-Agent System.

This demonstrates how the CoT system would handle:
"make full analysis of mysql service on unifyqarcdb"
"""
from typing import Any, Dict

from merlya.agents.chain_of_thought import ChainOfThought, Step
from merlya.agents.planner import PlannerAgent
from merlya.utils.logger import logger


class CoTOrchestrator:
    """
    Example orchestrator using Chain of Thought.

    This shows how the system decomposes complex tasks into steps
    with minimal context per step.
    """

    def __init__(self, context_manager, executor):
        self.context_manager = context_manager
        self.executor = executor
        self.planner = PlannerAgent(llm_client=None)  # No LLM needed for pattern-based planning
        self.cot = ChainOfThought(show_thinking=True, show_actions=True)

    def process_request_with_cot(self, user_query: str) -> str:
        """
        Process a request using Chain of Thought.

        Args:
            user_query: User's request

        Returns:
            Final response
        """
        logger.info(f"Processing with CoT: {user_query}")

        # Step 1: Create plan
        plan = self.cot.create_plan(
            title=f"Analysis Plan: {user_query}",
            request=user_query,
            planner_fn=lambda req: self.planner.create_plan(req, "")
        )

        # Step 2: Execute plan step by step
        executed_plan = self.cot.execute_plan(
            plan=plan,
            thinking_fn=self._think,
            action_fn=self._act
        )

        # Step 3: Synthesize results
        final_report = self._synthesize(executed_plan)

        return final_report

    def _think(self, step: Step, context: Dict[str, Any]) -> str:
        """
        Generate thinking for a step.

        This is where the LLM would reason about what to do.
        For now, we use rule-based thinking.

        Args:
            step: Current step
            context: Accumulated context from previous steps

        Returns:
            Thinking text
        """
        # Extract key info from context
        context.get("target_host", "unknown")
        context.get("target_service", "unknown")

        # Generate thinking based on step
        if step.id == 1:
            return "I need to verify that the host exists in the inventory and test SSH connectivity before proceeding with any analysis."

        elif step.id == 2:
            return "Now I'll scan the host to identify which MySQL variant is running (mysql/mysqld/mariadb) and check its current status."

        elif step.id == 3:
            return "I'll retrieve the MySQL configuration file (my.cnf) and key server variables to understand the current setup."

        elif step.id == 4:
            return "I'll analyze the error logs and slow query logs to identify any issues or performance problems."

        elif step.id == 5:
            return "I'll check MySQL performance metrics like connections, queries per second, buffer pool usage, etc."

        elif step.id == 6:
            return "I'll list all databases and check their disk usage to identify any storage issues."

        elif step.id == 7:
            return "I'll check system resources (CPU, RAM, disk) to ensure the host has adequate capacity."

        elif step.id == 8:
            return "I'll verify when the last backup ran and whether it was successful."

        elif step.id == 9:
            return "Now I'll synthesize all the collected data to create a comprehensive health report with findings and recommendations."

        return f"Processing step {step.id}: {step.description}"

    def _act(self, step: Step, thinking: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the action for a step.

        This is where actual commands are executed.

        Args:
            step: Current step
            thinking: Reasoning about what to do
            context: Accumulated context

        Returns:
            Result dictionary with success status and output
        """
        try:
            if step.id == 1:
                # Verify host exists and test SSH
                return self._verify_host(context)

            elif step.id == 2:
                # Identify MySQL service
                return self._identify_service(context)

            elif step.id == 3:
                # Get MySQL configuration
                return self._get_config(context)

            elif step.id == 4:
                # Analyze logs
                return self._analyze_logs(context)

            elif step.id == 5:
                # Check performance metrics
                return self._check_metrics(context)

            elif step.id == 6:
                # Analyze data/disk usage
                return self._check_disk(context)

            elif step.id == 7:
                # Check system resources
                return self._check_resources(context)

            elif step.id == 8:
                # Verify backups
                return self._check_backups(context)

            elif step.id == 9:
                # Synthesize (handled separately)
                return {
                    "success": True,
                    "message": "Analysis complete",
                    "output": None
                }

            else:
                return {
                    "success": False,
                    "error": f"Unknown step: {step.id}"
                }

        except Exception as e:
            logger.error(f"Action failed for step {step.id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def _verify_host(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Verify host exists and is accessible."""
        # In reality, this would call autogen_tools.get_infrastructure_context()
        # and autogen_tools.scan_host()

        # Simulated for example
        host = "unifyqarcdb"
        context["target_host"] = host

        return {
            "success": True,
            "message": f"Host '{host}' found in inventory (10.0.5.42)",
            "output": {
                "host": host,
                "ip": "10.0.5.42",
                "accessible": True
            }
        }

    def _identify_service(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Identify MySQL service."""
        context.get("target_host")

        # In reality: execute_command(host, "systemctl status mysql")

        service = "mysql"
        context["target_service"] = service
        context["mysql_version"] = "8.0.35"

        return {
            "success": True,
            "message": "MySQL 8.0.35 detected, service active",
            "output": {
                "service": service,
                "version": "8.0.35",
                "status": "active (running)",
                "uptime": "6 days"
            }
        }

    def _get_config(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get MySQL configuration."""
        # In reality: execute_command(host, "cat /etc/mysql/my.cnf")

        return {
            "success": True,
            "message": "Configuration loaded (105 lines)",
            "output": {
                "max_connections": 500,
                "innodb_buffer_pool_size": "8G",
                "query_cache_size": 0,
                "log_error": "/var/log/mysql/error.log"
            }
        }

    def _analyze_logs(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze MySQL logs."""
        # In reality: execute_command(host, "tail -100 /var/log/mysql/error.log")

        return {
            "success": True,
            "message": "Logs analyzed (last 100 lines)",
            "output": {
                "errors_found": 2,
                "warnings_found": 5,
                "critical_issues": 0,
                "recent_errors": [
                    "[Warning] Aborted connection 12345",
                    "[Warning] Host 'client.example.com' is blocked"
                ]
            }
        }

    def _check_metrics(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Check MySQL performance metrics."""
        # In reality: execute_command(host, "mysql -e 'SHOW GLOBAL STATUS'")

        return {
            "success": True,
            "message": "Performance metrics collected",
            "output": {
                "connections": 145,
                "max_used_connections": 287,
                "threads_running": 12,
                "slow_queries": 145,
                "questions": 1_245_678
            }
        }

    def _check_disk(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Check disk usage."""
        # In reality: execute_command(host, "du -sh /var/lib/mysql/*")

        return {
            "success": True,
            "message": "Disk usage analyzed",
            "output": {
                "data_directory_size": "156GB",
                "partition_size": "200GB",
                "usage_percent": 78,
                "largest_db": "production (89GB)"
            }
        }

    def _check_resources(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Check system resources."""
        # In reality: execute_command(host, "top -bn1")

        return {
            "success": True,
            "message": "System resources checked",
            "output": {
                "cpu_usage": "23%",
                "memory_usage": "6.2GB / 16GB (38%)",
                "disk_io": "Normal",
                "load_average": "2.1, 2.3, 2.5"
            }
        }

    def _check_backups(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Verify backup status."""
        # In reality: execute_command(host, "find /backup -name '*mysql*' -mtime -1")

        return {
            "success": True,
            "message": "Backup status verified",
            "output": {
                "last_backup": "2025-11-24 02:00:00",
                "backup_status": "SUCCESS",
                "backup_size": "142GB",
                "next_backup": "2025-11-25 02:00:00"
            }
        }

    def _synthesize(self, plan) -> str:
        """
        Synthesize all results into a final report.

        Args:
            plan: Executed plan with all results

        Returns:
            Final report
        """
        # Collect all results
        results = {}
        for step in plan.steps:
            if step.status.value == "completed" and step.result:
                results[step.id] = step.result.get("output", {})

        # Generate report
        report = []
        report.append("\n" + "=" * 80)
        report.append("📊 MySQL Analysis Report - unifyqarcdb")
        report.append("=" * 80 + "\n")

        # Health score (simplified)
        health_score = 78
        report.append(f"✅ HEALTH SCORE: {health_score}/100 (Good)\n")

        # Service status
        if 2 in results:
            service_info = results[2]
            report.append("🔍 SERVICE STATUS:")
            report.append(f"  ✅ MySQL {service_info.get('version')} - {service_info.get('status')}")
            report.append(f"  ✅ Uptime: {service_info.get('uptime')}\n")

        # Configuration
        if 3 in results:
            config = results[3]
            report.append("⚙️  CONFIGURATION:")
            report.append(f"  ✅ Max connections: {config.get('max_connections')}")
            report.append(f"  ✅ InnoDB buffer pool: {config.get('innodb_buffer_pool_size')}\n")

        # Performance
        if 5 in results:
            metrics = results[5]
            report.append("⚡ PERFORMANCE:")
            report.append(f"  ✅ Active connections: {metrics.get('connections')}/{metrics.get('max_used_connections')}")
            report.append(f"  ⚠️  Slow queries: {metrics.get('slow_queries')} (investigate)\n")

        # Disk usage
        if 6 in results:
            disk = results[6]
            report.append("💾 DISK USAGE:")
            report.append(f"  ⚠️  Data directory: {disk.get('usage_percent')}% full ({disk.get('data_directory_size')}/{disk.get('partition_size')})")
            report.append(f"  ℹ️  Largest DB: {disk.get('largest_db')}\n")

        # Backups
        if 8 in results:
            backup = results[8]
            report.append("💼 BACKUPS:")
            report.append(f"  ✅ Last backup: {backup.get('last_backup')} ({backup.get('backup_status')})")
            report.append(f"  ✅ Size: {backup.get('backup_size')}\n")

        # Recommendations
        report.append("💡 RECOMMENDATIONS:")
        report.append("  1. Investigate slow queries (145 detected)")
        report.append("  2. Plan disk expansion (78% full, projected full in ~90 days)")
        report.append("  3. Review aborted connections in logs")
        report.append("  4. Consider partitioning large tables\n")

        report.append("=" * 80)

        return "\n".join(report)


# Example usage demonstration
if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("CHAIN OF THOUGHT MULTI-AGENT DEMONSTRATION")
    print("=" * 80 + "\n")

    print("Request: 'make full analysis of mysql service on unifyqarcdb'\n")
    print("This system will:")
    print("  1. Decompose the task into 9 manageable steps")
    print("  2. Execute each step with visible thinking process")
    print("  3. Show real-time feedback")
    print("  4. Handle errors gracefully")
    print("  5. Synthesize comprehensive report")
    print("\n" + "=" * 80 + "\n")

    # Simulate
    from merlya.context.manager import ContextManager
    from merlya.executors.action_executor import ActionExecutor

    context_mgr = ContextManager(env="dev")
    executor = ActionExecutor()

    orchestrator = CoTOrchestrator(context_mgr, executor)

    # This would be called with the actual request
    # result = orchestrator.process_request_with_cot(
    #     "make full analysis of mysql service on unifyqarcdb"
    # )
    # print(result)

    print("✅ System ready. See chain_of_thought.py and planner.py for implementation.")
