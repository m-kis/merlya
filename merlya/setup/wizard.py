"""
Merlya Setup - First-run configuration wizard.

Handles LLM provider setup, inventory scanning, and host import.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.ui.console import ConsoleUI


@dataclass
class LLMConfig:
    """LLM configuration result."""

    provider: str
    model: str
    api_key_env: str | None = None


@dataclass
class SetupResult:
    """Result of setup wizard."""

    llm_config: LLMConfig | None = None
    hosts_imported: int = 0
    completed: bool = False


PROVIDERS = {
    "1": ("openrouter", "OPENROUTER_API_KEY", "anthropic/claude-3.5-sonnet"),
    "2": ("anthropic", "ANTHROPIC_API_KEY", "claude-3-5-sonnet-latest"),
    "3": ("openai", "OPENAI_API_KEY", "gpt-4o"),
    "4": ("ollama", None, "llama3.2"),
}


async def run_llm_setup(ui: ConsoleUI) -> LLMConfig | None:
    """
    Run LLM provider setup wizard.

    Args:
        ui: Console UI.

    Returns:
        LLMConfig or None if cancelled.
    """
    ui.panel(
        """
Configuration du Provider LLM

Providers disponibles:
  1. OpenRouter (recommande - multi-modeles)
  2. Anthropic (Claude direct)
  3. OpenAI (GPT models)
  4. Ollama (modeles locaux)
        """,
        title="Setup",
        style="info",
    )

    choice = await ui.prompt_choice(
        "Selectionnez un provider",
        choices=["1", "2", "3", "4"],
        default="1",
    )

    if choice not in PROVIDERS:
        choice = "1"

    provider, env_key, default_model = PROVIDERS[choice]

    # Check for existing API key
    if env_key:
        existing_key = os.environ.get(env_key)
        if existing_key:
            ui.success(f"API key trouvee dans l'environnement ({env_key})")
        else:
            api_key = await ui.prompt_secret(f"Entrez votre {env_key}")
            if api_key:
                # Set in environment for this session
                os.environ[env_key] = api_key
                ui.success("API key configuree")
            else:
                ui.warning("Pas d'API key fournie")
                return None

    # Model selection
    model = await ui.prompt(
        "Modele par defaut",
        default=default_model,
    )

    return LLMConfig(
        provider=provider,
        model=model,
        api_key_env=env_key,
    )


async def detect_inventory_sources(ui: ConsoleUI) -> list[tuple[str, Path, int]]:
    """
    Detect available inventory sources.

    Args:
        ui: Console UI.

    Returns:
        List of (name, path, host_count) tuples.
    """
    sources: list[tuple[str, Path, int]] = []

    ui.info("Recherche des sources d'inventaire...")

    # /etc/hosts
    etc_hosts = Path("/etc/hosts")
    if etc_hosts.exists():
        count = _count_etc_hosts(etc_hosts)
        if count > 0:
            sources.append(("/etc/hosts", etc_hosts, count))

    # SSH config
    ssh_config = Path.home() / ".ssh" / "config"
    if ssh_config.exists():
        count = _count_ssh_hosts(ssh_config)
        if count > 0:
            sources.append(("SSH Config", ssh_config, count))

    # Known hosts
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.exists():
        count = _count_known_hosts(known_hosts)
        if count > 0:
            sources.append(("Known Hosts", known_hosts, count))

    # Ansible inventory
    ansible_paths = [
        Path.home() / "inventory",
        Path.home() / "ansible" / "hosts",
        Path("/etc/ansible/hosts"),
        Path.cwd() / "inventory",
    ]
    for path in ansible_paths:
        if path.exists() and path.is_file():
            count = _count_ansible_hosts(path)
            if count > 0:
                sources.append((f"Ansible ({path.name})", path, count))

    return sources


def _count_etc_hosts(path: Path) -> int:
    """Count hosts in /etc/hosts."""
    count = 0
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split()
                if len(parts) >= 2 and not parts[1].startswith("localhost"):
                    count += 1
    except Exception:
        pass
    return count


def _count_ssh_hosts(path: Path) -> int:
    """Count hosts in SSH config."""
    count = 0
    try:
        for line in path.read_text().splitlines():
            if line.strip().lower().startswith("host "):
                hosts = line.split()[1:]
                for h in hosts:
                    if h != "*" and not h.startswith("!"):
                        count += 1
    except Exception:
        pass
    return count


def _count_known_hosts(path: Path) -> int:
    """Count hosts in known_hosts."""
    try:
        return len(path.read_text().splitlines())
    except Exception:
        return 0


def _count_ansible_hosts(path: Path) -> int:
    """Count hosts in Ansible inventory."""
    count = 0
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("["):
                count += 1
    except Exception:
        pass
    return count


async def import_from_ssh_config(
    path: Path,
    _ctx: SharedContext | None = None,
) -> list[dict[str, str]]:
    """
    Parse SSH config and extract hosts.

    Args:
        path: Path to SSH config.
        ctx: Optional context for saving.

    Returns:
        List of parsed host dicts.
    """
    hosts: list[dict[str, str]] = []
    current_host: dict[str, str] = {}

    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if line.lower().startswith("host "):
                if current_host and "name" in current_host:
                    hosts.append(current_host)
                current_host = {"name": line.split()[1]}
            elif "=" in line or " " in line:
                key, _, value = line.partition("=")
                if not value:
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        key, value = parts

                key = key.strip().lower()
                value = value.strip()

                if key == "hostname":
                    current_host["hostname"] = value
                elif key == "port":
                    current_host["port"] = value
                elif key == "user":
                    current_host["username"] = value
                elif key == "identityfile":
                    current_host["private_key"] = value
                elif key == "proxyjump":
                    current_host["jump_host"] = value

        if current_host and "name" in current_host:
            hosts.append(current_host)

    except Exception as e:
        logger.error(f"Failed to parse SSH config: {e}")

    return hosts


async def run_setup_wizard(ui: ConsoleUI) -> SetupResult:
    """
    Run the complete setup wizard.

    Args:
        ui: Console UI.

    Returns:
        SetupResult with configuration.
    """
    result = SetupResult()

    ui.panel(
        """
Bienvenue dans Merlya!

Cet assistant va vous guider pour configurer:
  1. Le provider LLM
  2. L'import des hosts existants
        """,
        title="Merlya Setup",
        style="info",
    )

    # Step 1: LLM Setup
    ui.newline()
    ui.info("**Etape 1: Configuration LLM**")

    llm_config = await run_llm_setup(ui)
    if llm_config:
        result.llm_config = llm_config
        ui.success(f"Provider: {llm_config.provider}, Model: {llm_config.model}")
    else:
        ui.warning("Configuration LLM ignoree")

    # Step 2: Inventory detection
    ui.newline()
    ui.info("**Etape 2: Detection des inventaires**")

    sources = await detect_inventory_sources(ui)

    if sources:
        ui.newline()
        ui.info("Sources detectees:")
        for name, _path, count in sources:
            ui.info(f"  {name}: {count} host(s)")

        do_import = await ui.prompt_confirm(
            "Voulez-vous importer ces hosts?",
            default=True,
        )

        if do_import:
            # Import from SSH config if found
            for name, path, _count in sources:
                if "SSH Config" in name:
                    hosts = await import_from_ssh_config(path)
                    result.hosts_imported += len(hosts)
                    ui.success(f"Importe {len(hosts)} host(s) depuis {name}")
    else:
        ui.info("Aucune source d'inventaire detectee")

    # Done
    ui.newline()
    result.completed = True

    ui.panel(
        f"""
Setup termine!

- Provider LLM: {result.llm_config.provider if result.llm_config else "non configure"}
- Hosts importes: {result.hosts_imported}

Utilisez /help pour voir les commandes disponibles.
        """,
        title="Setup Complete",
        style="success",
    )

    return result


async def check_first_run() -> bool:
    """
    Check if this is a first run.

    Returns:
        True if first run (no config exists).
    """
    config_path = Path.home() / ".merlya" / "config.yaml"
    return not config_path.exists()


if TYPE_CHECKING:
    from merlya.core.context import SharedContext
