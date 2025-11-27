import threading

from .config import ScanConfig
from .models import ScanResult
from .scanner import OnDemandScanner

# Singleton instance with thread-safe initialization
_scanner = None
_scanner_lock = threading.Lock()


def get_on_demand_scanner() -> OnDemandScanner:
    """
    Get the on-demand scanner singleton.

    IMPORTANT: Always use this function instead of instantiating OnDemandScanner
    directly. Multiple scanner instances share a global RateLimiter, but creating
    unnecessary instances wastes resources and may cause confusion.

    Thread-safe via double-checked locking pattern.
    """
    global _scanner
    if _scanner is None:
        with _scanner_lock:
            if _scanner is None:
                _scanner = OnDemandScanner()
    return _scanner

__all__ = ["OnDemandScanner", "ScanConfig", "ScanResult", "get_on_demand_scanner"]
