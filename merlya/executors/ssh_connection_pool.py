"""
SSH Connection Pool for managing persistent connections.
Handles 2FA by reusing authenticated connections.
Includes circuit breaker to prevent repeated failed connection attempts.

Key design decisions:
- Connections are keyed by CANONICAL HOSTNAME, not IP
- Circuit breaker tracks failures by canonical hostname
- This ensures connection reuse works correctly even when IP/hostname are used interchangeably
"""
import threading
import time
from typing import Dict, Optional

import paramiko

from merlya.utils.logger import log_prefix, logger


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open for a host."""
    pass


class SSHConnectionPool:
    """
    Pool of persistent SSH connections.

    Features:
    - Reuses connections to avoid 2FA re-prompts
    - Auto-closes stale connections
    - Thread-safe
    - Circuit breaker to prevent repeated failed connection attempts
    - Uses canonical hostname for consistent pooling (IP and hostname map to same connection)
    """

    def __init__(self, max_idle_time: int = 3600, circuit_breaker_threshold: int = 3, circuit_breaker_timeout: int = 300):
        """
        Initialize connection pool.

        Args:
            max_idle_time: Maximum idle time in seconds before closing connection (default: 1 hour)
            circuit_breaker_threshold: Number of failures before opening circuit (default: 3)
            circuit_breaker_timeout: Time in seconds before retrying a failed host (default: 5 minutes)
        """
        self.connections: Dict[str, Dict] = {}
        self.max_idle_time = max_idle_time
        self.lock = threading.Lock()

        # Circuit breaker state: {canonical_host: {'timestamp': float, 'count': int, 'error': str}}
        # Uses canonical hostname to prevent bypass via IP/hostname switching
        self.failed_hosts: Dict[str, Dict] = {}
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self.circuit_breaker_timeout = circuit_breaker_timeout

    def _get_canonical_hostname(self, host: str) -> str:
        """
        Get canonical hostname for pooling consistency.

        If host is an IP, try to find the corresponding hostname from inventory.
        This ensures that connections to the same host via different identifiers
        are pooled together.

        Args:
            host: Hostname or IP address

        Returns:
            Canonical hostname for this host
        """
        try:
            from merlya.context.host_resolution import get_canonical_hostname
            return get_canonical_hostname(host)
        except ImportError:
            return host

    def _connection_key(self, host: str, user: str) -> str:
        """
        Generate unique key for a connection.

        Uses canonical hostname to ensure consistent pooling.
        """
        canonical = self._get_canonical_hostname(host)
        return f"{user}@{canonical}"

    def _check_circuit_breaker(self, host: str):
        """
        Check if circuit breaker is open for this host.

        Uses canonical hostname to prevent bypass via IP/hostname switching.

        Raises:
            CircuitBreakerOpen: If the circuit breaker is open for this host
        """
        canonical = self._get_canonical_hostname(host)

        if canonical not in self.failed_hosts:
            return  # No failures recorded, OK to proceed

        failure_info = self.failed_hosts[canonical]
        count = failure_info['count']
        timestamp = failure_info['timestamp']
        error = failure_info.get('error', '')

        # Permanent failures (DNS errors, host not found)
        dns_errors = [
            'nodename nor servname provided',
            'Name or service not known',
            'Temporary failure in name resolution'
        ]

        if any(dns_error in error for dns_error in dns_errors) or count >= 10:
            raise CircuitBreakerOpen(
                f"Host '{canonical}' is permanently unreachable: {error}"
            )

        # Temporary circuit breaker (connection refused, timeout, etc.)
        if count >= self.circuit_breaker_threshold:
            elapsed = time.time() - timestamp
            if elapsed < self.circuit_breaker_timeout:
                remaining = int(self.circuit_breaker_timeout - elapsed)
                raise CircuitBreakerOpen(
                    f"Host '{canonical}' circuit breaker is OPEN "
                    f"(failed {count} times, retry in {remaining}s)"
                )
            else:
                # Timeout expired - reset and allow retry
                logger.info(f"{log_prefix('🔄')} Circuit breaker timeout expired for {canonical}, resetting")
                del self.failed_hosts[canonical]

    def _record_failure(self, host: str, error: Exception):
        """
        Record connection failure for circuit breaker.

        Uses canonical hostname to prevent bypass via IP/hostname switching.

        Args:
            host: Hostname that failed
            error: Exception that occurred
        """
        canonical = self._get_canonical_hostname(host)
        error_str = str(error)

        if canonical in self.failed_hosts:
            failure_info = self.failed_hosts[canonical]
            failure_info['count'] += 1
            failure_info['timestamp'] = time.time()
            failure_info['error'] = error_str
        else:
            self.failed_hosts[canonical] = {
                'timestamp': time.time(),
                'count': 1,
                'error': error_str
            }

        count = self.failed_hosts[canonical]['count']
        logger.warning(
            f"{log_prefix('⚠️')} SSH failure recorded for {canonical}: {count} failure(s) "
            f"(circuit breaker threshold: {self.circuit_breaker_threshold})"
        )

    def get_connection(self, host: str, user: str, **connect_kwargs) -> Optional[paramiko.SSHClient]:
        """
        Get an existing connection or create a new one.

        Args:
            host: Hostname or IP
            user: SSH username
            **connect_kwargs: Additional arguments for paramiko.SSHClient.connect()

        Returns:
            Active SSHClient or None if connection failed
        """
        # Check circuit breaker FIRST (before acquiring lock)
        self._check_circuit_breaker(host)

        key = self._connection_key(host, user)

        with self.lock:
            # Check if we have an existing connection
            if key in self.connections:
                conn_info = self.connections[key]
                client = conn_info['client']
                last_used = conn_info['last_used']

                # Check if connection is still alive and not too old
                if time.time() - last_used < self.max_idle_time:
                    try:
                        # Test if connection is still active
                        transport = client.get_transport()
                        if transport and transport.is_active():
                            logger.debug(f"{log_prefix('🔄')} Reusing existing SSH connection to {key}")
                            conn_info['last_used'] = time.time()
                            return client
                        else:
                            logger.debug(f"{log_prefix('💀')} Connection to {key} is dead, removing from pool")
                            self._close_connection(key)
                    except Exception as e:
                        logger.debug(f"{log_prefix('⚠️')} Error checking connection to {key}: {e}")
                        self._close_connection(key)
                else:
                    logger.debug(f"{log_prefix('⏱️')} Connection to {key} is too old, closing")
                    self._close_connection(key)

            # Create new connection
            logger.debug(f"{log_prefix('🌐')} Creating new SSH connection to {key}")
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                # Add host and username to kwargs
                connect_kwargs['hostname'] = host
                connect_kwargs['username'] = user

                # Connect
                client.connect(**connect_kwargs)

                # Store in pool
                self.connections[key] = {
                    'client': client,
                    'last_used': time.time(),
                    'created': time.time()
                }

                logger.info(f"{log_prefix('✓')} Established SSH connection to {key} (will be reused for {self.max_idle_time}s)")

                # Clear any previous failures for this host (successful connection)
                # Use canonical hostname to ensure we clear the correct entry
                canonical = self._get_canonical_hostname(host)
                if canonical in self.failed_hosts:
                    logger.debug(f"{log_prefix('✅')} Clearing circuit breaker state for {canonical} (successful connection)")
                    del self.failed_hosts[canonical]

                return client

            except Exception as e:
                logger.error(f"{log_prefix('❌')} Failed to connect to {key}: {e}")

                # Record failure for circuit breaker
                self._record_failure(host, e)

                return None

    def _close_connection(self, key: str):
        """Close and remove a connection from pool."""
        if key in self.connections:
            try:
                self.connections[key]['client'].close()
            except Exception:
                pass  # Ignore errors when closing stale connections
            del self.connections[key]

    def close_all(self):
        """Close all connections in the pool."""
        with self.lock:
            for key in list(self.connections.keys()):
                self._close_connection(key)
            logger.debug(f"{log_prefix('🔒')} Closed all SSH connections")

    def cleanup_stale(self):
        """Remove connections that haven't been used recently."""
        with self.lock:
            now = time.time()
            stale_keys = []

            for key, conn_info in self.connections.items():
                if now - conn_info['last_used'] > self.max_idle_time:
                    stale_keys.append(key)

            for key in stale_keys:
                logger.debug(f"{log_prefix('🧹')} Cleaning up stale connection to {key}")
                self._close_connection(key)

    def reset_circuit_breaker(self, host: Optional[str] = None):
        """
        Reset circuit breaker for a specific host or all hosts.

        Args:
            host: Hostname to reset (uses canonical name). If None, resets all.
        """
        with self.lock:
            if host is None:
                count = len(self.failed_hosts)
                self.failed_hosts.clear()
                logger.info(f"{log_prefix('🔄')} Circuit breaker reset for all {count} hosts")
            else:
                canonical = self._get_canonical_hostname(host)
                if canonical in self.failed_hosts:
                    del self.failed_hosts[canonical]
                    logger.info(f"{log_prefix('🔄')} Circuit breaker reset for {canonical}")
                # Also try the original host name in case it was stored before canonical fix
                if host in self.failed_hosts and host != canonical:
                    del self.failed_hosts[host]
                    logger.info(f"{log_prefix('🔄')} Circuit breaker reset for {host} (legacy entry)")


# Global connection pool (singleton with thread-safe double-checked locking)
_connection_pool = None
_pool_lock = threading.Lock()


def get_connection_pool() -> SSHConnectionPool:
    """Get the global SSH connection pool (thread-safe singleton)."""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            # Double-check after acquiring lock
            if _connection_pool is None:
                _connection_pool = SSHConnectionPool(max_idle_time=3600)  # 1 hour
    return _connection_pool


def reset_connection_pool() -> None:
    """Reset the connection pool (for testing)."""
    global _connection_pool
    with _pool_lock:
        if _connection_pool is not None:
            _connection_pool.close_all()
            _connection_pool = None
