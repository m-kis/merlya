"""
Context Module for Athena.

Provides:
- Host discovery and scanning
- Infrastructure context management
- Host registry with strict validation
- Inventory source management
- Interactive inventory setup wizard
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
]
