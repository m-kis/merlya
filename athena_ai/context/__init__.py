"""
Context Module for Athena.

Provides:
- Host discovery and scanning
- Infrastructure context management
- Host registry with strict validation
- Inventory source management
- Interactive inventory setup wizard
- Local machine scanning with intelligent caching
- On-demand remote host scanning
- Intelligent cache management
"""

from .discovery import Discovery
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
from .manager import ContextManager, get_context_manager
from .smart_cache import SmartCache

# New inventory system components
from .local_scanner import LocalScanner, get_local_scanner
from .on_demand_scanner import OnDemandScanner, ScanConfig, ScanResult, get_on_demand_scanner
from .cache_manager import CacheManager, CacheConfig, get_cache_manager

__all__ = [
    # Discovery
    "Discovery",
    # Context Management
    "ContextManager",
    "get_context_manager",
    # Host Registry (CRITICAL for security)
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
    # New inventory system
    "LocalScanner",
    "get_local_scanner",
    "OnDemandScanner",
    "ScanConfig",
    "ScanResult",
    "get_on_demand_scanner",
    "CacheManager",
    "CacheConfig",
    "get_cache_manager",
]
