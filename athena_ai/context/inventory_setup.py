"""
Inventory Setup Wizard - Interactive inventory source configuration.

This module handles:
1. First-run detection (no inventory configured)
2. Interactive source selection
3. Configuration persistence
4. Source validation
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Reuse the InventorySource enum from host_registry (DRY principle)
from athena_ai.context.host_registry import InventorySource
from athena_ai.utils.logger import logger


@dataclass
class InventorySourceConfig:
    """Configuration for an inventory source."""
    source_type: InventorySource
    enabled: bool = True
    path: Optional[str] = None  # For file-based sources
    url: Optional[str] = None   # For API-based sources
    credentials_key: Optional[str] = None  # Key in credential manager
    refresh_interval_minutes: int = 15
    priority: int = 0  # Lower = higher priority for conflict resolution

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d['source_type'] = self.source_type.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InventorySourceConfig':
        """Create from dictionary."""
        data['source_type'] = InventorySource(data['source_type'])
        return cls(**data)


@dataclass
class InventoryConfig:
    """Complete inventory configuration."""
    sources: List[InventorySourceConfig]
    primary_source: Optional[str] = None  # source_type value of primary
    auto_refresh: bool = True
    cache_ttl_minutes: int = 15
    ask_on_empty: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'sources': [s.to_dict() for s in self.sources],
            'primary_source': self.primary_source,
            'auto_refresh': self.auto_refresh,
            'cache_ttl_minutes': self.cache_ttl_minutes,
            'ask_on_empty': self.ask_on_empty,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InventoryConfig':
        """Create from dictionary."""
        sources = [InventorySourceConfig.from_dict(s) for s in data.get('sources', [])]
        return cls(
            sources=sources,
            primary_source=data.get('primary_source'),
            auto_refresh=data.get('auto_refresh', True),
            cache_ttl_minutes=data.get('cache_ttl_minutes', 15),
            ask_on_empty=data.get('ask_on_empty', True),
        )


class InventorySetupWizard:
    """
    Interactive wizard for inventory configuration.

    Called when:
    1. First run (no config exists)
    2. No hosts found after loading
    3. User explicitly requests reconfiguration
    """

    CONFIG_FILE = Path.home() / ".athena" / "inventory_config.json"

    def __init__(self, console_callback: Optional[Callable[[str], None]] = None):
        """
        Initialize wizard.

        Args:
            console_callback: Function to display messages (for integration with REPL)
        """
        self.console = console_callback or print
        self._config: Optional[InventoryConfig] = None

    @property
    def config(self) -> Optional[InventoryConfig]:
        """Get current configuration."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    def needs_setup(self) -> bool:
        """Check if setup is needed."""
        if not self.CONFIG_FILE.exists():
            return True

        config = self.load_config()
        if config is None or not config.sources:
            return True

        return False

    def load_config(self) -> Optional[InventoryConfig]:
        """Load configuration from file."""
        if not self.CONFIG_FILE.exists():
            return None

        try:
            with open(self.CONFIG_FILE, 'r') as f:
                data = json.load(f)
            return InventoryConfig.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load inventory config: {e}")
            return None

    def save_config(self, config: InventoryConfig) -> bool:
        """Save configuration to file."""
        try:
            self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(config.to_dict(), f, indent=2)
            self._config = config
            logger.info(f"Inventory config saved to {self.CONFIG_FILE}")
            return True
        except Exception as e:
            logger.error(f"Failed to save inventory config: {e}")
            return False

    def detect_available_sources(self) -> List[Dict[str, Any]]:
        """Detect which inventory sources are available on this system."""
        available = []

        # 1. /etc/hosts
        if Path("/etc/hosts").exists():
            # Count non-localhost entries
            count = self._count_etc_hosts_entries()
            available.append({
                'type': InventorySource.ETC_HOSTS,
                'name': '/etc/hosts',
                'path': '/etc/hosts',
                'detected': True,
                'host_count': count,
                'description': f"System hosts file ({count} entries)"
            })

        # 2. SSH Config
        ssh_config = Path.home() / ".ssh" / "config"
        if ssh_config.exists():
            count = self._count_ssh_hosts()
            available.append({
                'type': InventorySource.SSH_CONFIG,
                'name': 'SSH Config',
                'path': str(ssh_config),
                'detected': True,
                'host_count': count,
                'description': f"SSH configuration ({count} hosts)"
            })

        # 3. Ansible inventory (common locations)
        ansible_paths = [
            Path.home() / "inventory",
            Path.home() / "ansible" / "inventory",
            Path.home() / "ansible" / "hosts",
            Path("/etc/ansible/hosts"),
            Path("./inventory"),
            Path("./hosts"),
        ]

        for path in ansible_paths:
            if path.exists():
                count = self._count_ansible_hosts(path)
                if count > 0:
                    available.append({
                        'type': InventorySource.ANSIBLE_FILE,
                        'name': f'Ansible ({path.name})',
                        'path': str(path),
                        'detected': True,
                        'host_count': count,
                        'description': f"Ansible inventory ({count} hosts)"
                    })

        # 4. AWS (check for credentials)
        if self._check_aws_available():
            available.append({
                'type': InventorySource.AWS_EC2,
                'name': 'AWS EC2',
                'path': None,
                'detected': True,
                'host_count': '?',
                'description': "AWS EC2 instances (requires boto3)"
            })

        # 5. GCP (check for credentials)
        if self._check_gcp_available():
            available.append({
                'type': InventorySource.GCP_COMPUTE,
                'name': 'GCP Compute',
                'path': None,
                'detected': True,
                'host_count': '?',
                'description': "GCP Compute instances"
            })

        return available

    def _count_etc_hosts_entries(self) -> int:
        """Count entries in /etc/hosts (excluding localhost)."""
        try:
            count = 0
            with open("/etc/hosts") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        ip = parts[0]
                        if ip not in ["127.0.0.1", "::1", "255.255.255.255", "0.0.0.0"]:
                            if not ip.startswith("fe80::"):
                                count += 1
            return count
        except:
            return 0

    def _count_ssh_hosts(self) -> int:
        """Count hosts in SSH config."""
        try:
            count = 0
            ssh_config = Path.home() / ".ssh" / "config"
            with open(ssh_config) as f:
                for line in f:
                    if line.lower().strip().startswith("host "):
                        host = line.split()[1]
                        if host != "*":
                            count += 1
            return count
        except:
            return 0

    def _count_ansible_hosts(self, path: Path) -> int:
        """Count hosts in Ansible inventory."""
        try:
            count = 0
            in_vars = False
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("["):
                        in_vars = ":vars" in line or ":children" in line
                        continue
                    if not in_vars and line and "=" not in line.split()[0]:
                        count += 1
            return count
        except:
            return 0

    def _check_aws_available(self) -> bool:
        """Check if AWS credentials are configured."""
        import os
        return bool(
            os.getenv("AWS_ACCESS_KEY_ID") or
            (Path.home() / ".aws" / "credentials").exists()
        )

    def _check_gcp_available(self) -> bool:
        """Check if GCP credentials are configured."""
        import os
        return bool(
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or
            (Path.home() / ".config" / "gcloud" / "application_default_credentials.json").exists()
        )

    def create_default_config(self) -> InventoryConfig:
        """Create default configuration based on detected sources."""
        available = self.detect_available_sources()
        sources = []

        for source in available:
            if source['detected']:
                sources.append(InventorySourceConfig(
                    source_type=source['type'],
                    enabled=True,
                    path=source.get('path'),
                    priority=len(sources),
                ))

        # Determine primary source
        primary = None
        if sources:
            # Prefer Ansible > SSH > etc_hosts
            for stype in [InventorySource.ANSIBLE_FILE,
                         InventorySource.SSH_CONFIG,
                         InventorySource.ETC_HOSTS]:
                for s in sources:
                    if s.source_type == stype:
                        primary = stype.value
                        break
                if primary:
                    break

        return InventoryConfig(
            sources=sources,
            primary_source=primary,
            auto_refresh=True,
            cache_ttl_minutes=15,
            ask_on_empty=True,
        )

    def run_interactive_setup(self, input_callback: Callable[[str], str]) -> Optional[InventoryConfig]:
        """
        Run interactive setup wizard.

        Args:
            input_callback: Function to get user input (prompt -> response)

        Returns:
            Configured InventoryConfig or None if cancelled
        """
        self.console("\n" + "="*60)
        self.console("🔧 ATHENA INVENTORY SETUP")
        self.console("="*60)
        self.console("\nAthena needs to know where to find your server inventory.")
        self.console("I'll scan for available sources...\n")

        # Detect sources
        available = self.detect_available_sources()

        if not available:
            self.console("❌ No inventory sources detected!")
            self.console("\nOptions:")
            self.console("  1. Create a hosts file at ~/inventory")
            self.console("  2. Configure SSH hosts in ~/.ssh/config")
            self.console("  3. Setup Ansible inventory")
            return None

        # Show detected sources
        self.console("📋 Detected inventory sources:\n")
        for i, source in enumerate(available, 1):
            status = "✓" if source['detected'] else "○"
            source.get('host_count', '?')
            self.console(f"  {i}. [{status}] {source['name']}: {source['description']}")

        self.console("\n")

        # Ask which sources to enable
        response = input_callback(
            "Enable which sources? (comma-separated numbers, or 'all'): "
        ).strip().lower()

        if response == 'all':
            selected_indices = list(range(len(available)))
        else:
            try:
                selected_indices = [int(x.strip()) - 1 for x in response.split(",")]
            except:
                self.console("Invalid input, using all sources")
                selected_indices = list(range(len(available)))

        # Build config
        sources = []
        for i in selected_indices:
            if 0 <= i < len(available):
                source = available[i]
                sources.append(InventorySourceConfig(
                    source_type=source['type'],
                    enabled=True,
                    path=source.get('path'),
                    priority=len(sources),
                ))

        if not sources:
            self.console("❌ No sources selected")
            return None

        # Ask for primary source
        primary = sources[0].source_type.value
        if len(sources) > 1:
            self.console(f"\nPrimary source for conflict resolution: {sources[0].source_type.value}")

        # Ask for custom file
        custom = input_callback(
            "\nAdd custom inventory file path? (Enter to skip): "
        ).strip()

        if custom and Path(custom).exists():
            sources.append(InventorySourceConfig(
                source_type=InventorySource.CUSTOM_FILE,
                enabled=True,
                path=custom,
                priority=len(sources),
            ))

        config = InventoryConfig(
            sources=sources,
            primary_source=primary,
            auto_refresh=True,
            cache_ttl_minutes=15,
            ask_on_empty=True,
        )

        # Save
        if self.save_config(config):
            self.console("\n✅ Inventory configuration saved!")
            self.console(f"   Config file: {self.CONFIG_FILE}")
            total = sum(s.get('host_count', 0) for s in available if isinstance(s.get('host_count'), int))
            self.console(f"   Sources: {len(sources)}, ~{total} hosts")

        return config


# Singleton
_wizard: Optional[InventorySetupWizard] = None


def get_inventory_wizard() -> InventorySetupWizard:
    """Get the global inventory wizard instance."""
    global _wizard
    if _wizard is None:
        _wizard = InventorySetupWizard()
    return _wizard


def ensure_inventory_configured(
    console_callback: Callable[[str], None] = print,
    input_callback: Callable[[str], str] = input,
) -> Optional[InventoryConfig]:
    """
    Ensure inventory is configured, running setup if needed.

    Args:
        console_callback: Function to display messages
        input_callback: Function to get user input

    Returns:
        InventoryConfig or None if setup was cancelled
    """
    wizard = get_inventory_wizard()
    wizard.console = console_callback

    if wizard.needs_setup():
        return wizard.run_interactive_setup(input_callback)

    return wizard.config
