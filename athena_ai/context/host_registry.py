"""
Host Registry - Single Source of Truth for Valid Hosts.

This module provides a STRICT host registry that:
1. Only allows operations on hosts that exist in REAL inventory sources
2. NEVER accepts hallucinated/invented hostnames
3. Provides fuzzy matching and suggestions for invalid hostnames
4. Loads from multiple real sources (Ansible, SSH config, /etc/hosts, cloud APIs)

CRITICAL: This is a security-critical module. Never execute commands on unvalidated hosts.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from athena_ai.utils.logger import logger


class InventorySource(Enum):
    """Types of inventory sources."""
    # File-based sources
    ETC_HOSTS = "etc_hosts"
    SSH_CONFIG = "ssh_config"
    ANSIBLE_INVENTORY = "ansible_inventory"
    ANSIBLE_FILE = "ansible_file"  # Alias for inventory_setup compatibility
    CUSTOM_FILE = "custom_file"
    # Cloud sources
    CLOUD_AWS = "cloud_aws"
    CLOUD_GCP = "cloud_gcp"
    CLOUD_AZURE = "cloud_azure"
    AWS_EC2 = "aws_ec2"  # Alias
    GCP_COMPUTE = "gcp_compute"  # Alias
    # API sources
    NETBOX = "netbox"
    CMDB = "cmdb"
    # Manual
    MANUAL = "manual"


@dataclass
class Host:
    """A validated host entry."""
    hostname: str
    ip_address: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    source: InventorySource = InventorySource.MANUAL
    environment: Optional[str] = None  # prod, staging, dev
    groups: List[str] = field(default_factory=list)  # Ansible groups
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_seen: Optional[datetime] = None
    accessible: Optional[bool] = None

    def matches(self, query: str) -> bool:
        """Check if this host matches a query (case-insensitive)."""
        query_lower = query.lower()
        if self.hostname.lower() == query_lower:
            return True
        if any(alias.lower() == query_lower for alias in self.aliases):
            return True
        if self.ip_address and self.ip_address == query:
            return True
        return False

    def similarity(self, query: str) -> float:
        """Calculate similarity score with a query."""
        query_lower = query.lower()

        # Exact match
        if self.matches(query):
            return 1.0

        # Calculate best similarity across hostname and aliases
        scores = [SequenceMatcher(None, query_lower, self.hostname.lower()).ratio()]
        for alias in self.aliases:
            scores.append(SequenceMatcher(None, query_lower, alias.lower()).ratio())

        return max(scores)


@dataclass
class HostValidationResult:
    """Result of validating a hostname."""
    is_valid: bool
    host: Optional[Host] = None
    original_query: str = ""
    suggestions: List[Tuple[str, float]] = field(default_factory=list)  # (hostname, score)
    error_message: str = ""

    def get_suggestion_text(self) -> str:
        """Get human-readable suggestion text."""
        if self.is_valid:
            return f"✓ Host '{self.host.hostname}' is valid"

        if not self.suggestions:
            return f"✗ Host '{self.original_query}' not found. No similar hosts in inventory."

        lines = [f"✗ Host '{self.original_query}' not found in inventory."]
        lines.append("Did you mean one of these?")
        for hostname, score in self.suggestions[:5]:
            lines.append(f"  • {hostname} ({score:.0%} match)")
        return "\n".join(lines)


class HostRegistry:
    """
    Single source of truth for valid hosts.

    CRITICAL: Only hosts registered here are valid targets for operations.
    This prevents LLM hallucination attacks where fake hostnames are executed.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the host registry.

        Args:
            config: Configuration with inventory sources
        """
        self.config = config or {}
        self._hosts: Dict[str, Host] = {}  # hostname -> Host
        self._aliases: Dict[str, str] = {}  # alias -> canonical hostname
        self._loaded_sources: Set[InventorySource] = set()
        self._last_refresh: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=self.config.get("cache_ttl_minutes", 15))

    @property
    def hosts(self) -> Dict[str, Host]:
        """Get all registered hosts."""
        return self._hosts.copy()

    @property
    def hostnames(self) -> List[str]:
        """Get list of all valid hostnames."""
        return list(self._hosts.keys())

    def is_empty(self) -> bool:
        """Check if registry has no hosts."""
        return len(self._hosts) == 0

    def load_all_sources(self, force_refresh: bool = False) -> int:
        """
        Load hosts from all configured sources.

        Args:
            force_refresh: Force reload even if cache is valid

        Returns:
            Number of hosts loaded
        """
        # Check cache validity
        if not force_refresh and self._last_refresh:
            if datetime.now() - self._last_refresh < self._cache_ttl:
                logger.debug("Host registry cache still valid, skipping reload")
                return len(self._hosts)

        initial_count = len(self._hosts)

        # Load from each source
        self._load_etc_hosts()
        self._load_ssh_config()
        self._load_ansible_inventory()

        # Optional: Cloud sources
        if self.config.get("enable_aws"):
            self._load_aws_hosts()
        if self.config.get("enable_gcp"):
            self._load_gcp_hosts()

        self._last_refresh = datetime.now()
        len(self._hosts) - initial_count

        logger.info(f"Host registry loaded: {len(self._hosts)} total hosts from {len(self._loaded_sources)} sources")
        return len(self._hosts)

    def _load_etc_hosts(self) -> None:
        """Load hosts from /etc/hosts."""
        hosts_file = self.config.get("etc_hosts_path", "/etc/hosts")

        if not Path(hosts_file).exists():
            logger.debug(f"Hosts file not found: {hosts_file}")
            return

        try:
            with open(hosts_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    parts = line.split()
                    if len(parts) < 2:
                        continue

                    ip = parts[0]

                    # Skip special IPs
                    if ip in ["127.0.0.1", "::1", "255.255.255.255", "0.0.0.0"]:
                        continue
                    if ip.startswith("fe80::") or ip.startswith("ff02::"):
                        continue

                    # First name is canonical, rest are aliases
                    canonical = parts[1]
                    aliases = parts[2:] if len(parts) > 2 else []

                    # Skip special hostnames
                    if canonical in ["localhost", "broadcasthost", "ip6-localhost"]:
                        continue

                    self._register_host(Host(
                        hostname=canonical,
                        ip_address=ip,
                        aliases=aliases,
                        source=InventorySource.ETC_HOSTS,
                    ))

            self._loaded_sources.add(InventorySource.ETC_HOSTS)
            logger.debug(f"Loaded hosts from {hosts_file}")

        except Exception as e:
            logger.warning(f"Failed to load {hosts_file}: {e}")

    def _load_ssh_config(self) -> None:
        """Load hosts from SSH config (~/.ssh/config)."""
        ssh_config = Path.home() / ".ssh" / "config"

        if not ssh_config.exists():
            logger.debug("SSH config not found")
            return

        try:
            current_host = None
            current_hostname = None

            with open(ssh_config, "r") as f:
                for line in f:
                    line = line.strip()

                    if line.lower().startswith("host "):
                        # Save previous host
                        if current_host and current_host != "*":
                            self._register_host(Host(
                                hostname=current_host,
                                ip_address=current_hostname,
                                source=InventorySource.SSH_CONFIG,
                            ))

                        # Start new host
                        current_host = line.split()[1]
                        current_hostname = None

                    elif line.lower().startswith("hostname "):
                        current_hostname = line.split()[1]

            # Save last host
            if current_host and current_host != "*":
                self._register_host(Host(
                    hostname=current_host,
                    ip_address=current_hostname,
                    source=InventorySource.SSH_CONFIG,
                ))

            self._loaded_sources.add(InventorySource.SSH_CONFIG)
            logger.debug("Loaded hosts from SSH config")

        except Exception as e:
            logger.warning(f"Failed to load SSH config: {e}")

    def _load_ansible_inventory(self) -> None:
        """Load hosts from Ansible inventory."""
        # Try common Ansible inventory locations
        inventory_paths = [
            Path.home() / "inventory",
            Path.home() / "ansible" / "inventory",
            Path.home() / "ansible" / "hosts",
            Path("/etc/ansible/hosts"),
            Path("./inventory"),
            Path("./hosts"),
        ]

        # Add configured paths
        if self.config.get("ansible_inventory_paths"):
            for p in self.config["ansible_inventory_paths"]:
                inventory_paths.append(Path(p))

        for inv_path in inventory_paths:
            if inv_path.exists():
                self._parse_ansible_inventory(inv_path)

    def _parse_ansible_inventory(self, path: Path) -> None:
        """Parse an Ansible inventory file (INI format)."""
        try:
            current_group = "ungrouped"

            with open(path, "r") as f:
                for line in f:
                    line = line.strip()

                    if not line or line.startswith("#") or line.startswith(";"):
                        continue

                    # Group header
                    if line.startswith("[") and line.endswith("]"):
                        group_name = line[1:-1]
                        # Skip special groups
                        if ":vars" in group_name or ":children" in group_name:
                            current_group = None
                        else:
                            current_group = group_name
                        continue

                    if current_group is None:
                        continue

                    # Parse host line
                    # Format: hostname ansible_host=IP other_vars...
                    parts = line.split()
                    if not parts:
                        continue

                    hostname = parts[0]
                    ip_address = None
                    metadata = {}

                    for part in parts[1:]:
                        if "=" in part:
                            key, value = part.split("=", 1)
                            if key == "ansible_host":
                                ip_address = value
                            else:
                                metadata[key] = value

                    # Detect environment from group name
                    env = None
                    group_lower = current_group.lower()
                    if "prod" in group_lower:
                        env = "production"
                    elif "stag" in group_lower:
                        env = "staging"
                    elif "dev" in group_lower:
                        env = "development"

                    self._register_host(Host(
                        hostname=hostname,
                        ip_address=ip_address,
                        source=InventorySource.ANSIBLE_INVENTORY,
                        environment=env,
                        groups=[current_group],
                        metadata=metadata,
                    ))

            self._loaded_sources.add(InventorySource.ANSIBLE_INVENTORY)
            logger.debug(f"Loaded Ansible inventory from {path}")

        except Exception as e:
            logger.warning(f"Failed to parse Ansible inventory {path}: {e}")

    def _load_aws_hosts(self) -> None:
        """Load hosts from AWS EC2 (requires boto3)."""
        try:
            import boto3

            ec2 = boto3.client('ec2')
            response = ec2.describe_instances(
                Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]
            )

            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    # Get Name tag
                    name = None
                    for tag in instance.get('Tags', []):
                        if tag['Key'] == 'Name':
                            name = tag['Value']
                            break

                    if not name:
                        name = instance['InstanceId']

                    # Get environment from tags
                    env = None
                    for tag in instance.get('Tags', []):
                        if tag['Key'].lower() in ['environment', 'env']:
                            env = tag['Value']
                            break

                    self._register_host(Host(
                        hostname=name,
                        ip_address=instance.get('PrivateIpAddress'),
                        source=InventorySource.CLOUD_AWS,
                        environment=env,
                        metadata={
                            'instance_id': instance['InstanceId'],
                            'instance_type': instance['InstanceType'],
                            'availability_zone': instance['Placement']['AvailabilityZone'],
                        }
                    ))

            self._loaded_sources.add(InventorySource.CLOUD_AWS)
            logger.info("Loaded hosts from AWS EC2")

        except ImportError:
            logger.debug("boto3 not installed, skipping AWS")
        except Exception as e:
            logger.warning(f"Failed to load AWS hosts: {e}")

    def _load_gcp_hosts(self) -> None:
        """Load hosts from GCP Compute Engine."""
        try:
            from google.cloud import compute_v1

            client = compute_v1.InstancesClient()
            project = self.config.get("gcp_project")

            if not project:
                logger.debug("GCP project not configured")
                return

            # List all zones and instances
            for zone in compute_v1.ZonesClient().list(project=project):
                for instance in client.list(project=project, zone=zone.name):
                    if instance.status != "RUNNING":
                        continue

                    ip = None
                    for interface in instance.network_interfaces:
                        if interface.network_i_p:
                            ip = interface.network_i_p
                            break

                    self._register_host(Host(
                        hostname=instance.name,
                        ip_address=ip,
                        source=InventorySource.CLOUD_GCP,
                        metadata={
                            'zone': zone.name,
                            'machine_type': instance.machine_type,
                        }
                    ))

            self._loaded_sources.add(InventorySource.CLOUD_GCP)
            logger.info("Loaded hosts from GCP")

        except ImportError:
            logger.debug("google-cloud-compute not installed, skipping GCP")
        except Exception as e:
            logger.warning(f"Failed to load GCP hosts: {e}")

    def _register_host(self, host: Host) -> None:
        """Register a host in the registry."""
        hostname_lower = host.hostname.lower()

        # Merge if already exists
        if hostname_lower in self._hosts:
            existing = self._hosts[hostname_lower]
            # Merge aliases
            existing.aliases = list(set(existing.aliases + host.aliases))
            # Update IP if not set
            if not existing.ip_address and host.ip_address:
                existing.ip_address = host.ip_address
            # Merge groups
            existing.groups = list(set(existing.groups + host.groups))
            # Merge metadata
            existing.metadata.update(host.metadata)
        else:
            self._hosts[hostname_lower] = host

        # Register aliases
        for alias in host.aliases:
            self._aliases[alias.lower()] = hostname_lower

    def register_manual_host(
        self,
        hostname: str,
        ip_address: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> Host:
        """
        Manually register a host (e.g., from user confirmation).

        Args:
            hostname: Hostname to register
            ip_address: Optional IP address
            environment: Optional environment (prod, staging, dev)

        Returns:
            Registered Host object
        """
        host = Host(
            hostname=hostname,
            ip_address=ip_address,
            source=InventorySource.MANUAL,
            environment=environment,
            last_seen=datetime.now(),
        )
        self._register_host(host)
        logger.info(f"Manually registered host: {hostname}")
        return host

    def validate(self, hostname: str) -> HostValidationResult:
        """
        Validate if a hostname exists in the registry.

        This is the CRITICAL security function that prevents hallucination attacks.

        Args:
            hostname: Hostname to validate

        Returns:
            HostValidationResult with validity status and suggestions
        """
        if not hostname:
            return HostValidationResult(
                is_valid=False,
                original_query=hostname or "",
                error_message="Empty hostname provided",
            )

        # Ensure registry is loaded
        if self.is_empty():
            self.load_all_sources()

        hostname_lower = hostname.lower()

        # Direct match
        if hostname_lower in self._hosts:
            return HostValidationResult(
                is_valid=True,
                host=self._hosts[hostname_lower],
                original_query=hostname,
            )

        # Alias match
        if hostname_lower in self._aliases:
            canonical = self._aliases[hostname_lower]
            return HostValidationResult(
                is_valid=True,
                host=self._hosts[canonical],
                original_query=hostname,
            )

        # Not found - find suggestions
        suggestions = self._find_similar(hostname)

        return HostValidationResult(
            is_valid=False,
            original_query=hostname,
            suggestions=suggestions,
            error_message=f"Host '{hostname}' not found in inventory",
        )

    def _find_similar(self, query: str, max_results: int = 5) -> List[Tuple[str, float]]:
        """Find similar hostnames using fuzzy matching."""
        matches = []

        for _hostname, host in self._hosts.items():
            score = host.similarity(query)
            if score > 0.4:  # Minimum similarity threshold
                matches.append((host.hostname, score))

        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:max_results]

    def get(self, hostname: str) -> Optional[Host]:
        """
        Get a host by name (returns None if not found).

        Use validate() for security-critical operations.
        """
        result = self.validate(hostname)
        return result.host if result.is_valid else None

    def require(self, hostname: str) -> Host:
        """
        Get a host by name (raises if not found).

        Use this for strict validation in security-critical paths.

        Raises:
            ValueError: If host not found
        """
        result = self.validate(hostname)
        if not result.is_valid:
            raise ValueError(result.get_suggestion_text())
        return result.host

    def filter(
        self,
        environment: Optional[str] = None,
        group: Optional[str] = None,
        source: Optional[InventorySource] = None,
        pattern: Optional[str] = None,
    ) -> List[Host]:
        """
        Filter hosts by criteria.

        Args:
            environment: Filter by environment (prod, staging, dev)
            group: Filter by Ansible group
            source: Filter by inventory source
            pattern: Filter by hostname pattern (regex)

        Returns:
            List of matching hosts
        """
        results = []
        pattern_re = re.compile(pattern, re.IGNORECASE) if pattern else None

        for host in self._hosts.values():
            # Environment filter
            if environment and host.environment != environment:
                continue

            # Group filter
            if group and group not in host.groups:
                continue

            # Source filter
            if source and host.source != source:
                continue

            # Pattern filter
            if pattern_re and not pattern_re.search(host.hostname):
                continue

            results.append(host)

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics."""
        env_counts = {}
        source_counts = {}

        for host in self._hosts.values():
            env = host.environment or "unknown"
            env_counts[env] = env_counts.get(env, 0) + 1

            source = host.source.value
            source_counts[source] = source_counts.get(source, 0) + 1

        return {
            "total_hosts": len(self._hosts),
            "total_aliases": len(self._aliases),
            "loaded_sources": [s.value for s in self._loaded_sources],
            "by_environment": env_counts,
            "by_source": source_counts,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
        }


# Singleton instance
_registry: Optional[HostRegistry] = None
_setup_callback: Optional[Callable] = None


def set_inventory_setup_callback(callback: Callable) -> None:
    """
    Set callback for inventory setup when no hosts found.

    The callback should be a function that handles the setup wizard
    and returns True if setup was successful.
    """
    global _setup_callback
    _setup_callback = callback


def get_host_registry(config: Optional[Dict[str, Any]] = None) -> HostRegistry:
    """Get the global HostRegistry instance."""
    global _registry

    if _registry is None:
        _registry = HostRegistry(config)
        _registry.load_all_sources()

        # If no hosts found and we have a setup callback, invoke it
        if _registry.is_empty() and _setup_callback:
            logger.info("No hosts found in inventory, triggering setup...")
            if _setup_callback():
                # Reload after setup
                _registry.load_all_sources(force_refresh=True)

    return _registry


def reset_host_registry() -> None:
    """Reset the global registry (for testing or reconfiguration)."""
    global _registry
    _registry = None
