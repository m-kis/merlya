"""
Main on-demand scanner module.
"""
import asyncio
import socket
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from athena_ai.utils.logger import logger
from .config import ScanConfig
from .models import ScanResult
from .rate_limiter import get_shared_rate_limiter
from .ssh_scanner import ssh_scan


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
        self.rate_limiter = get_shared_rate_limiter(self.config)
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
            to_scan = list(hostnames)

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
            loop = asyncio.get_running_loop()
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
            ssh_data = await ssh_scan(hostname, scan_type, self.config)
            data.update(ssh_data)

        return data

    async def _check_connectivity(self, hostname: str, port: int = 22) -> bool:
        """Check if host is reachable on SSH port (supports IPv4 and IPv6)."""
        loop = asyncio.get_running_loop()

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
