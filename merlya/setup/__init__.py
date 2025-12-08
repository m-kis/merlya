"""
Merlya Setup - First-run configuration wizard.

Handles LLM provider setup, inventory scanning, and host import.
"""

from merlya.setup.models import HostData
from merlya.setup.parsers import (
    import_from_ssh_config,
    parse_ansible_inventory,
    parse_etc_hosts,
    parse_known_hosts,
    parse_ssh_config,
)
from merlya.setup.wizard import (
    InventorySource,
    LLMConfig,
    SetupResult,
    check_first_run,
    deduplicate_hosts,
    detect_inventory_sources,
    merge_host_data,
    parse_inventory_source,
    run_llm_setup,
    run_setup_wizard,
)

__all__ = [
    # Data classes
    "HostData",
    "InventorySource",
    "LLMConfig",
    "SetupResult",
    # Core functions
    "check_first_run",
    # Utilities
    "deduplicate_hosts",
    "detect_inventory_sources",
    # Parsing functions
    "import_from_ssh_config",
    "merge_host_data",
    "parse_ansible_inventory",
    "parse_etc_hosts",
    "parse_inventory_source",
    "parse_known_hosts",
    "parse_ssh_config",
    "run_llm_setup",
    "run_setup_wizard",
]
