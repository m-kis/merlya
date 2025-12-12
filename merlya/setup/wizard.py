"""
Merlya Setup - First-run configuration wizard.

Handles LLM provider setup, inventory scanning, and host import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from merlya.core.context import SharedContext
    from merlya.setup.models import HostData
    from merlya.ui.console import ConsoleUI


@dataclass
class LLMConfig:
    """LLM configuration result."""

    provider: str
    model: str
    api_key_env: str | None = None
    fallback_model: str | None = None


@dataclass
class SetupResult:
    """Result of setup wizard."""

    llm_config: LLMConfig | None = None
    hosts_imported: int = 0
    hosts_skipped: int = 0
    sources_imported: list[str] = field(default_factory=list)
    completed: bool = False


@dataclass
class InventorySource:
    """Detected inventory source."""

    name: str
    path: Path
    source_type: str
    host_count: int


# Provider config: (provider_name, env_key, default_model, fallback_model)
PROVIDERS = {
    "1": (
        "openrouter",
        "OPENROUTER_API_KEY",
        "amazon/nova-2-lite-v1:free",
        "openrouter:google/gemini-2.0-flash-lite-001",
    ),
    "2": (
        "anthropic",
        "ANTHROPIC_API_KEY",
        "claude-3-5-sonnet-latest",
        "anthropic:claude-3-haiku-20240307",
    ),
    "3": ("openai", "OPENAI_API_KEY", "gpt-4o", "openai:gpt-4o-mini"),
    "4": ("mistral", "MISTRAL_API_KEY", "mistral-large-latest", "mistral:mistral-small-latest"),
    "5": ("groq", "GROQ_API_KEY", "llama-3.3-70b-versatile", "groq:llama-3.1-8b-instant"),
    "6": ("ollama", None, "llama3.2", "ollama:llama3.2"),
}


async def run_llm_setup(ui: ConsoleUI, ctx: SharedContext | None = None) -> LLMConfig | None:
    """
    Run LLM provider setup wizard.

    Args:
        ui: Console UI.
        ctx: Optional shared context for i18n.

    Returns:
        LLMConfig or None if cancelled.
    """

    # Helper for translations - use translation_key to avoid conflict with {key} placeholder
    def t(translation_key: str, **kwargs: Any) -> str:
        if ctx:
            return ctx.i18n.t(translation_key, **kwargs)
        return translation_key

    ui.panel(
        t("setup.llm_config.providers"),
        title=t("setup.llm_config.title"),
        style="info",
    )

    choice = await ui.prompt_choice(
        t("setup.llm_config.select_provider"),
        choices=["1", "2", "3", "4", "5", "6"],
        default="1",
    )

    if choice not in PROVIDERS:
        choice = "1"

    provider, env_key, default_model, fallback_model = PROVIDERS[choice]

    if env_key:
        from merlya.secrets import get_secret, set_secret

        env_value = os.environ.get(env_key)
        keyring_value = get_secret(env_key)

        if env_value:
            ui.success(t("setup.llm_config.api_key_found", api_key=f"{env_key} - env"))
        elif keyring_value:
            ui.success(t("setup.llm_config.api_key_found", api_key=f"{env_key} - keyring"))
            os.environ[env_key] = keyring_value
        else:
            api_key = await ui.prompt_secret(t("setup.llm_config.enter_api_key", api_key=env_key))
            if api_key:
                set_secret(env_key, api_key)
                os.environ[env_key] = api_key
                ui.success(t("setup.llm_config.api_key_saved"))
            else:
                ui.warning(t("setup.llm_config.api_key_missing"))
                return None

    model = await ui.prompt(t("setup.llm_config.select_model"), default=default_model)

    fallback = fallback_model
    if fallback_model:
        fallback_input = await ui.prompt(
            t("setup.llm_config.select_fallback"), default=fallback_model
        )
        fallback_input = (fallback_input or "").strip()
        if fallback_input:
            fallback = fallback_input
        if fallback and ":" not in fallback:
            # Normalize to provider-prefixed syntax when the user omits it
            fallback = f"{provider}:{fallback}"

    return LLMConfig(provider=provider, model=model, api_key_env=env_key, fallback_model=fallback)


async def detect_inventory_sources(_ui: ConsoleUI) -> list[InventorySource]:
    """Detect available inventory sources."""
    from merlya.setup.parsers.ansible import count_ansible_hosts
    from merlya.setup.parsers.etc_hosts import count_etc_hosts
    from merlya.setup.parsers.known_hosts import count_known_hosts
    from merlya.setup.parsers.ssh_config import count_ssh_hosts

    sources: list[InventorySource] = []

    # /etc/hosts
    etc_hosts = Path("/etc/hosts")
    if etc_hosts.exists():
        count = count_etc_hosts(etc_hosts)
        if count > 0:
            sources.append(
                InventorySource(
                    name="/etc/hosts", path=etc_hosts, source_type="etc_hosts", host_count=count
                )
            )

    # SSH config
    ssh_config = Path.home() / ".ssh" / "config"
    if ssh_config.exists():
        count = count_ssh_hosts(ssh_config)
        if count > 0:
            sources.append(
                InventorySource(
                    name="SSH Config", path=ssh_config, source_type="ssh_config", host_count=count
                )
            )

    # Known hosts
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.exists():
        count = count_known_hosts(known_hosts)
        if count > 0:
            sources.append(
                InventorySource(
                    name="Known Hosts",
                    path=known_hosts,
                    source_type="known_hosts",
                    host_count=count,
                )
            )

    # Ansible inventory
    for path in [Path.home() / "inventory", Path("/etc/ansible/hosts"), Path.cwd() / "inventory"]:
        if path.exists() and path.is_file():
            count = count_ansible_hosts(path)
            if count > 0:
                sources.append(
                    InventorySource(
                        name=f"Ansible ({path.name})",
                        path=path,
                        source_type="ansible",
                        host_count=count,
                    )
                )

    return sources


async def parse_inventory_source(source: InventorySource) -> list[HostData]:
    """Parse an inventory source based on its type."""
    from merlya.setup.parsers import (
        parse_ansible_inventory,
        parse_etc_hosts,
        parse_known_hosts,
        parse_ssh_config,
    )

    parsers = {
        "etc_hosts": parse_etc_hosts,
        "ssh_config": parse_ssh_config,
        "known_hosts": parse_known_hosts,
        "ansible": parse_ansible_inventory,
    }

    parser = parsers.get(source.source_type)
    if parser:
        return await parser(source.path)

    logger.warning(f"⚠️ Unknown source type: {source.source_type}")
    return []


async def merge_host_data(hosts: list[HostData]) -> list[HostData]:
    """Merge host data from multiple sources."""
    merged: dict[str, HostData] = {}
    priority = {"ssh-config": 4, "ansible": 3, "known-hosts": 2, "etc-hosts": 1}

    for host in hosts:
        name = host.name.lower()
        tag_priority = max((priority.get(t.split(":")[0], 0) for t in host.tags), default=0)

        if name not in merged:
            merged[name] = host
        else:
            existing = merged[name]
            existing_priority = max(
                (priority.get(t.split(":")[0], 0) for t in existing.tags), default=0
            )

            if tag_priority > existing_priority:
                _merge_fields(host, existing)
                host.tags = list(set(host.tags + existing.tags))
                merged[name] = host
            else:
                _merge_fields(existing, host)
                existing.tags = list(set(existing.tags + host.tags))

    return list(merged.values())


def _merge_fields(target: HostData, source: HostData) -> None:
    """Merge missing fields from source into target."""
    if not target.hostname and source.hostname:
        target.hostname = source.hostname
    if not target.username and source.username:
        target.username = source.username
    if not target.private_key and source.private_key:
        target.private_key = source.private_key
    if not target.jump_host and source.jump_host:
        target.jump_host = source.jump_host


async def deduplicate_hosts(
    hosts: list[HostData], existing_names: set[str]
) -> tuple[list[HostData], int]:
    """Deduplicate hosts by name."""
    seen: dict[str, HostData] = {}
    duplicates = 0

    for host in hosts:
        name = host.name.lower()
        if name in existing_names:
            duplicates += 1
            continue

        if name not in seen:
            seen[name] = host
        else:
            existing = seen[name]
            existing_score = sum(
                [
                    bool(existing.hostname),
                    bool(existing.username),
                    bool(existing.private_key),
                    bool(existing.jump_host),
                ]
            )
            new_score = sum(
                [
                    bool(host.hostname),
                    bool(host.username),
                    bool(host.private_key),
                    bool(host.jump_host),
                ]
            )
            if new_score > existing_score:
                seen[name] = host
            duplicates += 1

    return list(seen.values()), duplicates


async def run_setup_wizard(ui: ConsoleUI, ctx: SharedContext | None = None) -> SetupResult:
    """Run the complete setup wizard."""
    result = SetupResult()

    def t(translation_key: str, **kwargs: Any) -> str:
        if ctx:
            return ctx.i18n.t(translation_key, **kwargs)
        return translation_key

    # Language selection
    ui.panel(
        "Welcome to Merlya! / Bienvenue dans Merlya!\n\n"
        "Select your language / Choisissez votre langue:\n"
        "  1. English\n  2. Français",
        title="Merlya Setup",
        style="info",
    )

    lang_choice = await ui.prompt_choice("Language / Langue", choices=["1", "2"], default="2")
    lang = "en" if lang_choice == "1" else "fr"
    if ctx:
        ctx.i18n.set_language(lang)

    ui.panel(t("setup.welcome"), title=t("setup.title"), style="info")

    # LLM Setup
    ui.newline()
    ui.info(t("setup.step_llm"))
    llm_config = await run_llm_setup(ui, ctx)
    if llm_config:
        result.llm_config = llm_config
        ui.success(f"Provider: {llm_config.provider}, Model: {llm_config.model}")
    else:
        ui.warning(t("setup.llm_config.skipped"))

    # Inventory import
    ui.newline()
    ui.info(t("setup.step_inventory"))
    ui.info(t("setup.inventory.searching"))

    sources = await detect_inventory_sources(ui)

    if sources:
        ui.newline()
        ui.info(t("setup.inventory.detected_sources"))
        total_hosts = sum(s.host_count for s in sources)
        for source in sources:
            ui.info(t("setup.inventory.source_item", name=source.name, count=source.host_count))

        do_import = await ui.prompt_confirm(
            t("setup.inventory.import_prompt") + f" ({total_hosts} host(s))", default=True
        )

        if do_import and ctx:
            result = await _import_hosts_from_sources(ui, ctx, sources, result, t)
    else:
        ui.info(t("setup.inventory.no_sources"))

    ui.newline()
    result.completed = True

    provider_name = result.llm_config.provider if result.llm_config else "N/A"
    ui.panel(
        t("setup.complete.summary", provider=provider_name, hosts=result.hosts_imported),
        title=t("setup.complete.title"),
        style="success",
    )

    return result


async def _import_hosts_from_sources(
    ui: ConsoleUI,
    ctx: SharedContext,
    sources: list[InventorySource],
    result: SetupResult,
    t: Callable[..., str],
) -> SetupResult:
    """Import hosts from detected sources."""
    from merlya.persistence.models import Host

    ui.newline()
    all_hosts: list[HostData] = []

    for source in sources:
        ui.info(t("setup.inventory.importing", count=source.host_count, name=source.name))
        parsed = await parse_inventory_source(source)
        all_hosts.extend(parsed)
        result.sources_imported.append(source.name)

    merged_hosts = await merge_host_data(all_hosts)
    existing_hosts = await ctx.hosts.list()
    existing_names = {h.name.lower() for h in existing_hosts}
    unique_hosts, duplicates = await deduplicate_hosts(merged_hosts, existing_names)
    result.hosts_skipped = duplicates

    for host_data in unique_hosts:
        try:
            host = Host(
                name=host_data.name,
                hostname=host_data.hostname or host_data.name,
                port=host_data.port,
                username=host_data.username,
                private_key=host_data.private_key,
                jump_host=host_data.jump_host,
                tags=host_data.tags,
            )
            await ctx.hosts.create(host)
            result.hosts_imported += 1
        except Exception as e:
            logger.debug(f"⚠️ Failed to import host {host_data.name}: {e}")
            result.hosts_skipped += 1

    ui.newline()
    ui.success(t("commands.hosts.import_complete", count=result.hosts_imported))
    if result.hosts_skipped > 0:
        ui.info(t("commands.hosts.import_errors", count=result.hosts_skipped))

    return result


async def check_first_run() -> bool:
    """Check if this is a first run."""
    config_path = Path.home() / ".merlya" / "config.yaml"
    return not config_path.exists()


# =============================================================================
# IMPORT/EXPORT UTILITIES
# =============================================================================


def import_from_ssh_config(path: Path) -> list[dict[str, Any]]:
    """Import hosts from SSH config file (sync version for commands)."""
    from merlya.setup.parsers.ssh_config import import_from_ssh_config as _import

    return _import(path)
