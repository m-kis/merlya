"""
On-Demand Host Scanner with parallel execution, retry, and rate limiting.

Features:
- Parallel scanning of multiple hosts
- Configurable rate limiting
- Retry with exponential backoff
- Progress reporting
- Scan caching with TTL
"""

import asyncio
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from athena_ai.utils.logger import logger


@dataclass
class ScanConfig:
    """Configuration for on-demand scanning."""

    # Parallelism
    max_workers: int = 10
    batch_size: int = 5

    # Rate limiting
    requests_per_second: float = 5.0
    burst_size: int = 10

    # Retry
    max_retries: int = 3
    retry_base_delay: float = 1.0  # seconds
    retry_max_delay: float = 30.0  # seconds

    # Timeouts
    connect_timeout: float = 10.0  # seconds
    command_timeout: float = 60.0  # seconds

    # SSH host key policy: "reject", "warning", or "auto_add"
    # "auto_add" should only be used in non-production/testing environments
    # Can be overridden by ATHENA_SSH_AUTO_ADD_HOSTS=1 env var
    ssh_host_key_policy: str = "warning"

    # Cache TTL (seconds)
    cache_ttl: Dict[str, int] = field(default_factory=lambda: {
        "basic": 300,       # 5 min - hostname, IP, connectivity
        "system": 1800,     # 30 min - OS, CPU, memory
        "services": 900,    # 15 min - running services
        "packages": 3600,   # 1 hour - installed packages
        "processes": 60,    # 1 min - process list
        "full": 600,        # 10 min - full scan
    })


@dataclass
class ScanResult:
    """Result of a host scan."""

    hostname: str
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0
    retries: int = 0
    scanned_at: str = ""

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(timezone.utc).isoformat()


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: float, burst: int):
        """
        Initialize rate limiter.

        Args:
            rate: Requests per second
            burst: Maximum burst size
        """
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return

            # Need to wait for token - compute wait time and release lock before sleeping
            wait_time = (1 - self.tokens) / self.rate

        # Sleep outside the lock to allow other callers to proceed
        await asyncio.sleep(wait_time)

        # Reacquire lock and recompute tokens based on current time
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            # Consume one token (may go slightly negative if contention, but that's fine)
            self.tokens -= 1


class OnDemandScanner:
    """
    On-demand host scanner with parallel execution and retry logic.

    Features:
    - Parallel scanning of multiple hosts
    - Rate limiting to prevent overwhelming targets
    - Exponential backoff retry
    - Scan result caching
    - Progress callbacks
    """

    def __init__(self, config: Optional[ScanConfig] = None):
        """
        Initialize scanner.

        Args:
            config: Scanner configuration (uses defaults if not provided)

        Note:
            Uses a shared module-level RateLimiter to enforce global rate limits.
            Multiple OnDemandScanner instances will share the same token bucket,
            preventing rate limit bypass through multiple instantiation.
        """
        self.config = config or ScanConfig()
        # Use shared rate limiter to enforce global limits across all instances
        self.rate_limiter = _get_shared_rate_limiter(self.config)
        self._executor = None
        self._repo = None

    @property
    def repo(self):
        """Lazy load repository."""
        if self._repo is None:
            from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
            self._repo = get_inventory_repository()
        return self._repo

    async def scan_hosts(
        self,
        hostnames: List[str],
        scan_type: str = "basic",
        force: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[ScanResult]:
        """
        Scan multiple hosts in parallel.

        Args:
            hostnames: List of hostnames to scan
            scan_type: Type of scan (basic, system, services, full)
            force: Force scan even if cached
            progress_callback: Callback(current, total, hostname)

        Returns:
            List of ScanResult objects
        """
        results = []
        total = len(hostnames)

        # Check cache first (unless force)
        to_scan = []
        if not force:
            for hostname in hostnames:
                cached = self._get_cached(hostname, scan_type)
                if cached:
                    results.append(ScanResult(
                        hostname=hostname,
                        success=True,
                        data=cached,
                        scanned_at=cached.get("scanned_at", "")
                    ))
                else:
                    to_scan.append(hostname)
        else:
            to_scan = hostnames

        # Report cached results
        if progress_callback:
            progress_callback(len(results), total, "using cache")

        if not to_scan:
            return results

        # Scan in batches
        batch_size = self.config.batch_size
        for i in range(0, len(to_scan), batch_size):
            batch = to_scan[i:i + batch_size]
            batch_results = await self._scan_batch(batch, scan_type)

            for result in batch_results:
                results.append(result)

                # Cache successful results
                if result.success:
                    self._cache_result(result, scan_type)

                if progress_callback:
                    progress_callback(len(results), total, result.hostname)

        return results

    async def scan_host(
        self,
        hostname: str,
        scan_type: str = "basic",
        force: bool = False,
    ) -> ScanResult:
        """
        Scan a single host.

        Args:
            hostname: Hostname to scan
            scan_type: Type of scan
            force: Force scan even if cached

        Returns:
            ScanResult object
        """
        results = await self.scan_hosts([hostname], scan_type, force)
        return results[0] if results else ScanResult(
            hostname=hostname,
            success=False,
            error="No result returned"
        )

    async def _scan_batch(
        self,
        hostnames: List[str],
        scan_type: str,
    ) -> List[ScanResult]:
        """Scan a batch of hosts concurrently."""
        tasks = [
            self._scan_with_retry(hostname, scan_type)
            for hostname in hostnames
        ]
        # Use return_exceptions=True to preserve successful results on partial failure
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to failed ScanResults
        processed = []
        for hostname, result in zip(hostnames, results):
            if isinstance(result, Exception):
                processed.append(ScanResult(
                    hostname=hostname,
                    success=False,
                    error=str(result),
                ))
            else:
                processed.append(result)

        return processed

    async def _scan_with_retry(
        self,
        hostname: str,
        scan_type: str,
    ) -> ScanResult:
        """Scan a host with retry logic."""
        attempt = 0
        last_error = None

        while attempt <= self.config.max_retries:
            try:
                # Rate limit
                await self.rate_limiter.acquire()

                # Perform scan
                start = time.monotonic()
                data = await self._perform_scan(hostname, scan_type)
                duration_ms = int((time.monotonic() - start) * 1000)

                return ScanResult(
                    hostname=hostname,
                    success=True,
                    data=data,
                    duration_ms=duration_ms,
                    retries=attempt,  # Number of retries (0 = first attempt succeeded)
                )

            except Exception as e:
                last_error = str(e)
                attempt += 1

                if attempt <= self.config.max_retries:
                    # Exponential backoff
                    delay = min(
                        self.config.retry_base_delay * (2 ** (attempt - 1)),
                        self.config.retry_max_delay
                    )
                    logger.debug(f"Retry {attempt} for {hostname} after {delay}s: {e}")
                    await asyncio.sleep(delay)

        # All retries exhausted - attempt is max_retries + 1 here, so use attempt - 1
        # to get the actual number of retries performed
        return ScanResult(
            hostname=hostname,
            success=False,
            error=last_error,
            retries=attempt - 1,
        )

    async def _perform_scan(
        self,
        hostname: str,
        scan_type: str,
    ) -> Dict[str, Any]:
        """
        Perform the actual scan of a host.

        Args:
            hostname: Hostname to scan
            scan_type: Type of scan

        Returns:
            Scan data dictionary
        """
        data = {
            "hostname": hostname,
            "scan_type": scan_type,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

        # Resolve hostname to IP (non-blocking, supports IPv4 and IPv6)
        try:
            loop = asyncio.get_event_loop()
            # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
            # sockaddr is (ip, port) for IPv4 or (ip, port, flow, scope) for IPv6
            addrinfo = await loop.run_in_executor(
                None,
                lambda: socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
            )
            if addrinfo:
                # Extract IP from first result's sockaddr (index 4), IP is always index 0
                data["ip"] = addrinfo[0][4][0]
                # Store all resolved addresses for completeness
                all_ips = list({info[4][0] for info in addrinfo})
                if len(all_ips) > 1:
                    data["all_ips"] = all_ips
                data["dns_resolved"] = True
            else:
                data["dns_resolved"] = False
        except socket.gaierror:
            data["dns_resolved"] = False

        # Check connectivity
        data["reachable"] = await self._check_connectivity(hostname)

        if not data["reachable"]:
            return data

        # SSH-based scans
        if scan_type in ["system", "services", "full"]:
            ssh_data = await self._ssh_scan(hostname, scan_type)
            data.update(ssh_data)

        return data

    async def _check_connectivity(self, hostname: str, port: int = 22) -> bool:
        """Check if host is reachable on SSH port (supports IPv4 and IPv6)."""
        loop = asyncio.get_event_loop()

        def check():
            try:
                # Use getaddrinfo to support both IPv4 and IPv6
                addrinfo = socket.getaddrinfo(
                    hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM
                )
                # Try each address until one connects
                for family, socktype, proto, _, sockaddr in addrinfo:
                    try:
                        with socket.socket(family, socktype, proto) as sock:
                            sock.settimeout(self.config.connect_timeout)
                            result = sock.connect_ex(sockaddr)
                            if result == 0:
                                return True
                    except Exception:
                        continue
                return False
            except Exception:
                return False

        return await loop.run_in_executor(None, check)

    async def _ssh_scan(
        self,
        hostname: str,
        scan_type: str,
    ) -> Dict[str, Any]:
        """
        Perform SSH-based scan.

        Args:
            hostname: Hostname to scan
            scan_type: Type of scan

        Returns:
            Scan data from SSH
        """
        data = {}
        client = None

        try:
            import paramiko

            # Get SSH credentials from context
            from athena_ai.security.credentials import CredentialManager
            creds = CredentialManager()
            user = creds.get_user_for_host(hostname)
            key_path = creds.get_key_for_host(hostname) or creds.get_default_key()

            # Connect
            client = paramiko.SSHClient()

            # Determine host key policy from config or environment
            # Environment variable overrides config for testing/non-production
            env_auto_add = os.environ.get("ATHENA_SSH_AUTO_ADD_HOSTS", "").lower() in ("1", "true", "yes")
            policy_name = "auto_add" if env_auto_add else self.config.ssh_host_key_policy

            # Load system known_hosts for security
            known_hosts_loaded = False
            try:
                client.load_system_host_keys()
                known_hosts_loaded = True
            except FileNotFoundError:
                # known_hosts file doesn't exist - common on fresh systems
                logger.warning(
                    "System known_hosts file not found. "
                    "Set ATHENA_SSH_AUTO_ADD_HOSTS=1 to allow connections without host verification."
                )
            except PermissionError as e:
                # Can't read known_hosts - security concern
                logger.warning(
                    f"Permission denied reading known_hosts: {e}. "
                    "Set ATHENA_SSH_AUTO_ADD_HOSTS=1 to allow connections without host verification."
                )
            except paramiko.ssh_exception.SSHException as e:
                # Parsing error in known_hosts file - this is a real problem
                logger.error(
                    f"Failed to parse known_hosts file: {e}. "
                    "The file may be corrupted. Using RejectPolicy for safety."
                )
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                raise  # Re-raise so caller can handle

            # Set host key policy based on configuration
            # Security: When known_hosts couldn't be loaded, default to RejectPolicy
            # unless explicitly configured to allow unknown hosts
            if policy_name == "auto_add":
                if env_auto_add:
                    logger.warning(
                        "SSH AutoAddPolicy enabled via ATHENA_SSH_AUTO_ADD_HOSTS env var. "
                        "This should only be used in non-production environments."
                    )
                else:
                    logger.warning(
                        "SSH AutoAddPolicy enabled via config. "
                        "This is insecure and should only be used for testing."
                    )
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            elif policy_name == "reject" or not known_hosts_loaded:
                # Use RejectPolicy if explicitly configured OR if known_hosts unavailable
                client.set_missing_host_key_policy(paramiko.RejectPolicy())
                if not known_hosts_loaded and policy_name != "reject":
                    logger.debug(
                        "SSH host key policy: RejectPolicy (no known_hosts available)"
                    )
                else:
                    logger.debug("SSH host key policy: RejectPolicy (strictest)")
            else:
                # Default: WarningPolicy - logs warning but connects
                # Only used when known_hosts is available for verification
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
                logger.debug("SSH host key policy: WarningPolicy (default)")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: client.connect(
                    hostname,
                    username=user,
                    key_filename=key_path,
                    timeout=self.config.connect_timeout,
                    allow_agent=creds.is_agent_available(),
                )
            )

            data["ssh_connected"] = True
            data["ssh_user"] = user

            # Run commands based on scan type
            if scan_type in ["system", "full"]:
                data.update(await self._get_system_info(client))

            if scan_type in ["services", "full"]:
                data.update(await self._get_services_info(client))

            if scan_type == "full":
                data.update(await self._get_full_info(client))

        except ImportError:
            data["ssh_connected"] = False
            data["error"] = "paramiko not installed"
        except Exception as e:
            data["ssh_connected"] = False
            data["error"] = str(e)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        return data

    async def _get_system_info(self, client) -> Dict[str, Any]:
        """Get system information via SSH."""
        data = {}
        loop = asyncio.get_event_loop()

        commands = {
            "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
            "kernel": "uname -r",
            "uptime": "uptime -p 2>/dev/null || uptime",
            "cpu_count": "nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null",
            "memory_mb": "free -m 2>/dev/null | awk '/^Mem:/{print $2}' || sysctl -n hw.memsize 2>/dev/null | awk '{print $0/1048576}'",
            "hostname_full": "hostname -f 2>/dev/null || hostname",
        }

        for key, cmd in commands.items():
            try:
                _, stdout, _ = await loop.run_in_executor(
                    None,
                    lambda c=cmd: client.exec_command(c, timeout=self.config.command_timeout)
                )
                result = stdout.read().decode().strip()
                if result:
                    data[key] = result
            except Exception as e:
                logger.debug(f"Failed to get {key}: {e}")

        return data

    async def _get_services_info(self, client) -> Dict[str, Any]:
        """Get services information via SSH."""
        data = {}
        loop = asyncio.get_event_loop()

        # Try systemd first
        try:
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: client.exec_command(
                    "systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | head -20",
                    timeout=self.config.command_timeout
                )
            )
            result = stdout.read().decode().strip()
            if result:
                services = []
                for line in result.split('\n'):
                    parts = line.split()
                    if parts:
                        service_name = parts[0].replace('.service', '')
                        services.append(service_name)
                data["services"] = services
        except Exception as e:
            logger.debug(f"Failed to get services: {e}")

        # Check common ports
        data["open_ports"] = await self._check_common_ports(client)

        return data

    async def _check_common_ports(self, client) -> List[int]:
        """Check common service ports."""
        loop = asyncio.get_event_loop()
        common_ports = [22, 80, 443, 3306, 5432, 6379, 27017, 8080, 9000]
        open_ports = []

        try:
            ports_str = ' '.join(str(p) for p in common_ports)
            cmd = f"for p in {ports_str}; do (echo >/dev/tcp/127.0.0.1/$p) 2>/dev/null && echo $p; done"
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: client.exec_command(f"bash -c '{cmd}'", timeout=10)
            )
            result = stdout.read().decode().strip()
            if result:
                open_ports = [int(p) for p in result.split('\n') if p.strip()]
        except Exception:
            pass

        return open_ports

    async def _get_full_info(self, client) -> Dict[str, Any]:
        """Get full system information via SSH."""
        data = {}
        loop = asyncio.get_event_loop()

        # Disk usage
        try:
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: client.exec_command(
                    "df -h / 2>/dev/null | tail -1 | awk '{print $5}'",
                    timeout=self.config.command_timeout
                )
            )
            result = stdout.read().decode().strip()
            if result:
                data["disk_usage_root"] = result
        except Exception:
            pass

        # Load average
        try:
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: client.exec_command(
                    "cat /proc/loadavg 2>/dev/null | cut -d' ' -f1-3",
                    timeout=self.config.command_timeout
                )
            )
            result = stdout.read().decode().strip()
            if result:
                data["load_avg"] = result
        except Exception:
            pass

        # Process count
        try:
            _, stdout, _ = await loop.run_in_executor(
                None,
                lambda: client.exec_command(
                    "ps aux 2>/dev/null | wc -l",
                    timeout=self.config.command_timeout
                )
            )
            result = stdout.read().decode().strip()
            if result:
                data["process_count"] = int(result)
        except Exception:
            pass

        return data

    def _get_cached(self, hostname: str, scan_type: str) -> Optional[Dict]:
        """Get cached scan result if valid."""
        try:
            ttl = self.config.cache_ttl.get(scan_type, 300)
            cached = self.repo.get_scan_cache(hostname, scan_type)

            if cached:
                cached_at = datetime.fromisoformat(cached["cached_at"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - cached_at).total_seconds()

                if age < ttl:
                    return cached.get("data", {})

        except Exception as e:
            logger.debug(f"Cache lookup failed for {hostname}: {e}")

        return None

    def _cache_result(self, result: ScanResult, scan_type: str):
        """Cache a successful scan result."""
        try:
            ttl = self.config.cache_ttl.get(scan_type, 300)
            self.repo.set_scan_cache(
                hostname=result.hostname,
                scan_type=scan_type,
                data=result.data,
                ttl_seconds=ttl
            )
        except Exception as e:
            logger.debug(f"Failed to cache result for {result.hostname}: {e}")


# Module-level shared RateLimiter to enforce global rate limits across all instances.
# This ensures that even if multiple OnDemandScanner instances are created,
# they share the same token bucket for rate limiting.
_shared_rate_limiter: Optional[RateLimiter] = None


def _get_shared_rate_limiter(config: ScanConfig) -> RateLimiter:
    """Get or create the shared rate limiter."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:
        _shared_rate_limiter = RateLimiter(config.requests_per_second, config.burst_size)
    return _shared_rate_limiter


# Singleton instance (GIL protects against data races in check-then-create)
_scanner: Optional[OnDemandScanner] = None


def get_on_demand_scanner() -> OnDemandScanner:
    """
    Get the on-demand scanner singleton.

    IMPORTANT: Always use this function instead of instantiating OnDemandScanner
    directly. Multiple scanner instances share a global RateLimiter, but creating
    unnecessary instances wastes resources and may cause confusion. The GIL
    protects against data races in the singleton check.
    """
    global _scanner
    if _scanner is None:
        _scanner = OnDemandScanner()
    return _scanner
