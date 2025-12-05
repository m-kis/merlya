"""
Merlya Setup - First-run configuration wizard.

Handles LLM provider setup, inventory scanning, and host import.
"""

from merlya.setup.wizard import (
    LLMConfig,
    SetupResult,
    check_first_run,
    detect_inventory_sources,
    import_from_ssh_config,
    run_llm_setup,
    run_setup_wizard,
)

__all__ = [
    "LLMConfig",
    "SetupResult",
    "check_first_run",
    "detect_inventory_sources",
    "import_from_ssh_config",
    "run_llm_setup",
    "run_setup_wizard",
]
