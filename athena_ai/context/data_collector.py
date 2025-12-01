"""
Data Collector - Collecte intelligente de données sur les serveurs.

Fonctionnalités:
- SSH collection (processus, métriques, services)
- Cache avec TTL
- Fallback strategies
- Multi-source support (SSH, API monitoring)
"""
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from athena_ai.utils.logger import logger


class DataCollector:
    """
    Intelligent data collector for infrastructure servers.

    Capabilities:
    - SSH-based collection (processes, metrics, services)
    - API monitoring sources (Prometheus, Datadog - future)
    - Smart caching with TTL
    - Parallel collection
    """

    def __init__(
        self,
        ssh_config: Optional[Dict[str, Any]] = None,
        monitoring_sources: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Initialize data collector.

        Args:
            ssh_config: SSH configuration
                {
                    'enabled': bool,
                    'default_user': str,
                    'key_path': str
                }
            monitoring_sources: List of monitoring sources
                [
                    {'name': 'prometheus', 'type': 'api', 'url': '...'},
                    ...
                ]
        """
        self.ssh_config = ssh_config or {'enabled': False}
        self.monitoring_sources = monitoring_sources or []
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = 300  # 5 minutes default

    async def collect_server_data(
        self,
        hostname: str,
        ip: str,
        data_types: List[str],
        use_cache: bool = True,
        ssh_user: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Collect comprehensive data for a specific server.

        Args:
            hostname: Server hostname
            ip: Server IP address
            data_types: Types of data to collect
                ['processes', 'metrics', 'services', 'os', 'all']
            use_cache: Use cached data if available
            ssh_user: SSH user (override default)

        Returns:
            {
                'hostname': str,
                'ip': str,
                'processes': [...],  # if requested
                'metrics': {...},    # if requested
                'services': [...],   # if requested
                'os': {...},         # if requested
                'collected_at': str,
                'collection_method': 'ssh' | 'cache'
            }
        """
        cache_key = f"{hostname}:{ip}"

        # Check cache first
        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            cache_age = time.time() - cached.get('_timestamp', 0)

            if cache_age < self._cache_ttl:
                logger.debug(f"Using cached data for {hostname} (age: {cache_age:.0f}s)")
                return {**cached, 'collection_method': 'cache'}

        # Determine what to collect
        if 'all' in data_types:
            data_types = ['processes', 'metrics', 'services', 'os']

        # Collect fresh data
        result = {
            'hostname': hostname,
            'ip': ip,
            'collected_at': datetime.now().isoformat(),
            'collection_method': 'ssh',
            '_timestamp': time.time()
        }

        # Try SSH collection first
        if self.ssh_config.get('enabled'):
            try:
                ssh_data = await self._collect_via_ssh(
                    ip=ip,
                    data_types=data_types,
                    user=ssh_user or self.ssh_config.get('default_user', 'root')
                )
                result.update(ssh_data)

                # Cache the result
                self._cache[cache_key] = result
                logger.info(f"Data collected for {hostname} via SSH")

                return result

            except Exception as e:
                logger.error(f"SSH collection failed for {hostname}: {e}")

        # Fallback: Try monitoring sources
        for source in self.monitoring_sources:
            try:
                if source['type'] == 'prometheus':
                    monitoring_data = await self._collect_from_prometheus(
                        hostname=hostname,
                        source=source
                    )
                    result.update(monitoring_data)
                    result['collection_method'] = 'prometheus'
                    return result
            except Exception as e:
                logger.warning(f"Monitoring source {source['name']} failed: {e}")

        # No collection method succeeded
        result['error'] = "No collection method available"
        return result

    async def _collect_via_ssh(
        self,
        ip: str,
        data_types: List[str],
        user: str
    ) -> Dict[str, Any]:
        """
        Collect data via SSH connection.

        Args:
            ip: Server IP
            data_types: What to collect
            user: SSH user

        Returns:
            Dict with collected data
        """
        from athena_ai.executors.action_executor import ActionExecutor

        executor = ActionExecutor()
        result = {}

        # Commands to run based on data types
        commands = {}

        if 'processes' in data_types:
            commands['processes'] = "ps aux --sort=-%cpu | head -20"

        if 'metrics' in data_types:
            # Collect CPU, RAM, Disk in one go
            commands['metrics'] = """
echo "=== CPU ===" && top -bn1 | head -5
echo "=== MEMORY ===" && free -m
echo "=== DISK ===" && df -h
echo "=== LOAD ===" && uptime
"""

        if 'services' in data_types:
            commands['services'] = "systemctl list-units --type=service --state=running --no-pager"

        if 'os' in data_types:
            commands['os'] = "uname -a && cat /etc/os-release 2>/dev/null || cat /etc/redhat-release 2>/dev/null"

        # Execute commands (sequentially for simplicity, could be parallelized)
        for data_type, command in commands.items():
            try:
                exec_result = executor.execute(
                    target=f"{user}@{ip}",
                    command=command,
                    confirm=False
                )

                if exec_result.get('status') == 'success':
                    output = exec_result.get('output', '')
                    result[data_type] = self._parse_output(data_type, output)
                else:
                    logger.warning(f"Command failed for {data_type}: {exec_result.get('error')}")

            except Exception as e:
                logger.error(f"Failed to collect {data_type} via SSH: {e}")

        return result

    def _parse_output(self, data_type: str, output: str) -> Any:
        """
        Parse command output into structured data.

        Args:
            data_type: Type of data (processes, metrics, etc.)
            output: Raw command output

        Returns:
            Structured data
        """
        if data_type == 'processes':
            # Parse ps aux output
            processes = []
            lines = output.strip().split('\n')

            for line in lines[1:]:  # Skip header
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    processes.append({
                        'user': parts[0],
                        'pid': parts[1],
                        'cpu': parts[2],
                        'mem': parts[3],
                        'vsz': parts[4],
                        'rss': parts[5],
                        'tty': parts[6],
                        'stat': parts[7],
                        'start': parts[8],
                        'time': parts[9],
                        'command': parts[10]
                    })

            return processes

        if data_type == 'metrics':
            # Parse metrics output
            metrics: Dict[str, Any] = {}

            # Extract CPU
            if 'Cpu(s):' in output:
                cpu_line = [line for line in output.split('\n') if 'Cpu(s):' in line][0]
                # Parse: %Cpu(s):  2.3 us,  1.1 sy,  0.0 ni, 96.5 id, ...
                parts = cpu_line.split(',')
                for part in parts:
                    if 'id' in part:  # idle
                        idle = float(part.strip().split()[0])
                        metrics['cpu_usage'] = 100 - idle
                        break

            # Extract Memory
            if 'Mem:' in output:
                mem_line = [line for line in output.split('\n') if 'Mem:' in line and 'total' in line][0]
                parts = mem_line.split()
                if len(parts) >= 4:
                    metrics['mem_total'] = parts[1]
                    metrics['mem_used'] = parts[2]
                    metrics['mem_free'] = parts[3]

            # Extract Disk
            disk_lines = [line for line in output.split('\n') if '/' in line and '%' in line]
            if disk_lines:
                # Parse first disk line (usually root filesystem)
                parts = disk_lines[0].split()
                if len(parts) >= 5:
                    metrics['disk_usage'] = parts[4].replace('%', '')
                    metrics['disk_total'] = parts[1]
                    metrics['disk_used'] = parts[2]
                    metrics['disk_free'] = parts[3]

            # Extract Load Average
            if 'load average:' in output:
                load_line = [line for line in output.split('\n') if 'load average:' in line][0]
                load_part = load_line.split('load average:')[1].strip()
                loads = [item.strip() for item in load_part.split(',')[:3]]
                metrics['load_1min'] = loads[0] if len(loads) > 0 else None
                metrics['load_5min'] = loads[1] if len(loads) > 1 else None
                metrics['load_15min'] = loads[2] if len(loads) > 2 else None

            return metrics

        if data_type == 'services':
            # Parse systemctl output
            services = []
            lines = output.strip().split('\n')

            for line in lines[1:]:  # Skip header
                if '.service' in line:
                    parts = line.split(None, 4)
                    if len(parts) >= 4:
                        services.append({
                            'name': parts[0],
                            'load': parts[1],
                            'active': parts[2],
                            'sub': parts[3],
                            'description': parts[4] if len(parts) > 4 else ''
                        })

            return services

        if data_type == 'os':
            # Parse OS information
            os_info = {'raw': output}

            if 'NAME=' in output:
                for line in output.split('\n'):
                    if line.startswith('NAME='):
                        os_info['name'] = line.split('=')[1].strip('"')
                    elif line.startswith('VERSION='):
                        os_info['version'] = line.split('=')[1].strip('"')

            if 'Linux' in output:
                # Parse uname output
                uname_line = [line for line in output.split('\n') if 'Linux' in line][0]
                parts = uname_line.split()
                if len(parts) >= 3:
                    os_info['kernel'] = parts[2]

            return os_info

        # Default: return raw output
        return output

    async def _collect_from_prometheus(
        self,
        hostname: str,
        source: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Collect metrics from Prometheus.

        Args:
            hostname: Hostname to query
            source: Prometheus source config

        Returns:
            Dict with metrics
        """
        # TODO: Implement Prometheus API integration
        # For now, return empty
        logger.warning("Prometheus collection not yet implemented")
        return {}

    def clear_cache(self, hostname: Optional[str] = None):
        """Clear cache for specific host or all hosts."""
        if hostname:
            # Clear specific host
            keys_to_remove = [k for k in self._cache if k.startswith(f"{hostname}:")]
            for key in keys_to_remove:
                del self._cache[key]
            logger.debug(f"Cleared cache for {hostname}")
        else:
            # Clear all
            self._cache.clear()
            logger.debug("Cleared all cache")
