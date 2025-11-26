"""
Investigation Service - DDD Domain Service (Correction 10).

Implements 3-tier architecture for service/concept investigation:
1. Direct Services (mysql, nginx, postgres) → simple systemctl commands
2. Concepts (backup, monitoring, logs, security) → LLM-generated investigation
3. Generic (no service detected) → basic system checks
"""
from typing import List
from athena_ai.utils.logger import logger


class InvestigationService:
    """
    Domain Service for determining how to investigate a service or concept.

    Implements intelligent distinction between direct services and abstract concepts.
    """

    # Known direct systemd services
    DIRECT_SERVICES = {
        "mysql", "mariadb", "postgres", "postgresql", "mongodb", "mongod",
        "nginx", "apache", "apache2", "httpd",
        "redis", "memcached", "elasticsearch",
        "docker", "containerd",
        "ssh", "sshd", "cron", "rsyslog", "systemd-journald"
    }

    def __init__(self, llm_router):
        """
        Initialize Investigation Service.

        Args:
            llm_router: LLM router for generating investigation commands
        """
        self.llm_router = llm_router

    def is_direct_service(self, service_name: str) -> bool:
        """
        Check if this is a direct systemd service (vs a concept requiring investigation).

        Args:
            service_name: Service or concept name

        Returns:
            True if direct systemd service, False if concept
        """
        if not service_name:
            return False

        service_lower = service_name.lower()
        return service_lower in self.DIRECT_SERVICES

    def generate_investigation_commands(
        self,
        concept: str,
        target_host: str,
        original_query: str
    ) -> List[str]:
        """
        Use LLM to generate intelligent investigation commands for a concept.

        This is the core of Correction 10 - instead of treating "backup" as a literal
        service name, we generate 5-7 intelligent commands to investigate the concept.

        Args:
            concept: The concept to investigate (backup, monitoring, logs, etc.)
            target_host: Target hostname
            original_query: Original user query for context

        Returns:
            List of shell commands to execute (max 7)
        """
        prompt = f"""Given the concept "{concept}" on a Linux server, generate 5-7 shell commands to investigate it thoroughly AND READ relevant files found.

Original question: "{original_query}"

IMPORTANT: Be proactive and autonomous. If you find scripts/config files, READ them automatically using cat/head/tail.

The investigation should:
1. Find and LIST relevant files/services
2. READ the content of found files (use cat, head -50, etc.)
3. Check processes, services, cron jobs
4. Analyze logs for recent activity
5. Check disk usage if relevant

For "backups" example:
- find /opt /usr/local/bin -name "*backup*.sh" -type f 2>/dev/null | head -3 | xargs -I {{}} bash -c 'echo "=== {{}} ===" && head -50 {{}}'
- grep -i backup /var/log/syslog /var/log/cron* 2>/dev/null | tail -20
- crontab -l 2>/dev/null; ls -l /etc/cron.d/*backup* /etc/cron.daily/*backup* 2>/dev/null
- systemctl list-units --all | grep -i backup
- ls -lht /backup /var/backups 2>/dev/null | head -10
- df -h /backup /var/backups 2>/dev/null

For file content request like "que contient ce script /path/to/file":
- cat /path/to/file
- file /path/to/file && head -100 /path/to/file

Generate similar AUTONOMOUS and DEEP investigation commands for "{concept}".
Be proactive: if you find a file, READ it. Don't just list it.
Return ONLY the commands, one per line, no explanations.
"""

        try:
            response = self.llm_router.generate(
                prompt=prompt,
                system_prompt="You are an expert Linux system administrator. Generate precise shell commands for investigation.",
                task="reasoning"
            )

            # Parse commands from response
            commands = []
            for line in response.strip().split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    # Remove common prefixes (bullets, numbers, backticks)
                    line = line.lstrip('`-*0123456789. ')
                    line = line.rstrip('`')
                    if line:
                        commands.append(line)

            logger.info(f"LLM generated {len(commands)} investigation commands for concept '{concept}'")
            return commands[:7]  # Limit to 7 commands max

        except Exception as e:
            logger.error(f"Failed to generate investigation commands via LLM: {e}")
            # Fallback to generic commands
            return [
                f"systemctl list-units --all | grep -i {concept}",
                f"ps aux | grep -i {concept}",
                f"find /etc -name '*{concept}*' -type f 2>/dev/null",
                f"crontab -l | grep -i {concept}",
            ]

    def get_investigation_strategy(self, service_name: str) -> str:
        """
        Determine which investigation strategy to use.

        Returns:
            "direct" for direct services, "concept" for concepts, "generic" for none
        """
        if not service_name:
            return "generic"

        if self.is_direct_service(service_name):
            return "direct"

        return "concept"

    def get_direct_service_commands(self, service_name: str) -> List[str]:
        """
        Get simple commands for checking a direct systemd service.

        Args:
            service_name: Service name (mysql, nginx, etc.)

        Returns:
            List of commands to check the service
        """
        return [
            f"systemctl status {service_name}",
            f"ps aux | grep {service_name} | grep -v grep"
        ]

    def get_generic_commands(self) -> List[str]:
        """
        Get generic system check commands when no specific service is detected.

        Returns:
            List of generic system check commands
        """
        return [
            "uptime",
            "df -h"
        ]
