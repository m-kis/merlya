"""
Context Module for Merlya.

Provides:
- Infrastructure context management (ContextManager)
- Local machine scanning (LocalScanner) - comprehensive, with SQLite caching
- Remote host scanning (OnDemandScanner) - JIT single host scanning
- Host registry with strict validation
- Inventory source management
- Interactive inventory setup wizard
- Intelligent cache management

Scanning Architecture:
    /scan            → LocalScanner (12h TTL, SQLite) - local machine only
    /scan <hostname> → OnDemandScanner (JIT) - specific remote host

Scanning Philosophy (JIT - Just In Time):
    - Local machine: Comprehensive scan, cached for 12h
    - Remote hosts: Scanned on-demand when first connecting
    - No bulk scanning: Individual hosts scanned as needed

Deprecated:
    Discovery class is deprecated. Use LocalScanner and OnDemandScanner.
"""

from .cache_manager import CacheConfig, CacheManager, get_cache_manager
from .discovery import Discovery  # Deprecated
from .host_registry import (
    Host,
    HostRegistry,
    HostValidationResult,
    InventorySource,
    get_host_registry,
    reset_host_registry,
    set_inventory_setup_callback,
)
from .inventory_setup import (
    InventoryConfig,
    InventorySetupWizard,
    InventorySourceConfig,
    ensure_inventory_configured,
    get_inventory_wizard,
)
from .inventory_sources import DataAvailability, InventorySourceManager
from .local_scanner import LocalScanner, get_local_scanner
from .manager import ContextManager, get_context_manager
from .on_demand_scanner import OnDemandScanner, ScanConfig, ScanResult, get_on_demand_scanner
from .smart_cache import SmartCache
from .utils import parse_inventory

__all__ = [
    # Context Management (Primary API)
    "ContextManager",
    "get_context_manager",
    # Scanning (Primary API)
    "LocalScanner",
    "get_local_scanner",
    "OnDemandScanner",
    "ScanConfig",
    "ScanResult",
    "get_on_demand_scanner",
    # Host Registry (Security-critical)
    "HostRegistry",
    "Host",
    "HostValidationResult",
    "InventorySource",
    "get_host_registry",
    "set_inventory_setup_callback",
    "reset_host_registry",
    # Inventory Setup
    "InventorySetupWizard",
    "InventoryConfig",
    "InventorySourceConfig",
    "get_inventory_wizard",
    "ensure_inventory_configured",
    # Inventory Sources
    "InventorySourceManager",
    "DataAvailability",
    # Cache
    "SmartCache",
    "CacheManager",
    "CacheConfig",
    "get_cache_manager",
    # Utilities
    "parse_inventory",
    # Deprecated (kept for backwards compatibility)
    "Discovery",
]
