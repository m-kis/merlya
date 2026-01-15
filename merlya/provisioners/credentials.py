"""
Merlya Provisioners - Credential resolution.

Multi-source credential resolution for cloud providers.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from merlya.secrets.store import SecretStore


@dataclass
class CredentialSource:
    """Information about where a credential was found."""

    name: str
    source: str  # "keyring", "env", "file", "config"
    is_set: bool = True


@dataclass
class ProviderCredentials:
    """Resolved credentials for a cloud provider."""

    provider: str
    credentials: dict[str, str] = field(default_factory=dict)
    sources: list[CredentialSource] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Check if all required credentials are present."""
        return len(self.missing) == 0 and len(self.credentials) > 0


# Credential requirements per provider
PROVIDER_CREDENTIALS = {
    "aws": {
        "required": [
            ("aws-access-key", "AWS_ACCESS_KEY_ID"),
            ("aws-secret-key", "AWS_SECRET_ACCESS_KEY"),
        ],
        "optional": [
            ("aws-session-token", "AWS_SESSION_TOKEN"),
            ("aws-region", "AWS_DEFAULT_REGION"),
        ],
    },
    "gcp": {
        "required": [
            ("gcp-credentials-json", "GOOGLE_APPLICATION_CREDENTIALS"),
        ],
        "optional": [
            ("gcp-project", "GOOGLE_CLOUD_PROJECT"),
        ],
    },
    "azure": {
        "required": [
            ("azure-client-id", "AZURE_CLIENT_ID"),
            ("azure-client-secret", "AZURE_CLIENT_SECRET"),
            ("azure-tenant-id", "AZURE_TENANT_ID"),
        ],
        "optional": [
            ("azure-subscription-id", "AZURE_SUBSCRIPTION_ID"),
        ],
    },
    "ovh": {
        "required": [
            ("ovh-application-key", "OVH_APPLICATION_KEY"),
            ("ovh-application-secret", "OVH_APPLICATION_SECRET"),
            ("ovh-consumer-key", "OVH_CONSUMER_KEY"),
        ],
        "optional": [
            ("ovh-endpoint", "OVH_ENDPOINT"),
        ],
    },
    "digitalocean": {
        "required": [
            ("digitalocean-token", "DIGITALOCEAN_TOKEN"),
        ],
        "optional": [],
    },
    "proxmox": {
        "required": [
            ("proxmox-host", "PROXMOX_HOST"),
            ("proxmox-token-id", "PROXMOX_TOKEN_ID"),
            ("proxmox-token-secret", "PROXMOX_TOKEN_SECRET"),
        ],
        "optional": [
            ("proxmox-verify-ssl", "PROXMOX_VERIFY_SSL"),
        ],
    },
    "vmware": {
        "required": [
            ("vmware-host", "VMWARE_HOST"),
            ("vmware-user", "VMWARE_USER"),
            ("vmware-password", "VMWARE_PASSWORD"),
        ],
        "optional": [
            ("vmware-datacenter", "VMWARE_DATACENTER"),
        ],
    },
}


class CredentialResolver:
    """
    Resolves credentials from multiple sources.

    Resolution order:
    1. Keyring (SecretStore)
    2. Environment variables
    3. Credential files (e.g., ~/.aws/credentials)

    Thread-safe singleton pattern.
    """

    _instance: CredentialResolver | None = None

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        """
        Initialize the credential resolver.

        Args:
            secret_store: Optional SecretStore instance.
        """
        self._secret_store = secret_store

    @classmethod
    def get_instance(cls, secret_store: SecretStore | None = None) -> CredentialResolver:
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(secret_store)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton for tests."""
        cls._instance = None

    def set_secret_store(self, store: SecretStore) -> None:
        """Set the secret store."""
        self._secret_store = store

    def resolve(self, provider: str) -> ProviderCredentials:
        """
        Resolve all credentials for a provider.

        Args:
            provider: Cloud provider name (aws, gcp, azure, etc.).

        Returns:
            ProviderCredentials with resolved values.
        """
        provider = provider.lower()
        result = ProviderCredentials(provider=provider)

        if provider not in PROVIDER_CREDENTIALS:
            logger.warning(f"Unknown provider: {provider}")
            return result

        config = PROVIDER_CREDENTIALS[provider]

        # Resolve required credentials
        for secret_name, env_var in config["required"]:
            value, source = self._resolve_credential(secret_name, env_var)
            if value:
                result.credentials[env_var] = value
                result.sources.append(CredentialSource(name=env_var, source=source))
            else:
                result.missing.append(env_var)

        # Resolve optional credentials
        for secret_name, env_var in config.get("optional", []):
            value, source = self._resolve_credential(secret_name, env_var)
            if value:
                result.credentials[env_var] = value
                result.sources.append(CredentialSource(name=env_var, source=source))

        if result.is_complete:
            logger.debug(f"Credentials resolved for {provider}")
        else:
            logger.warning(f"Missing credentials for {provider}: {result.missing}")

        return result

    def _resolve_credential(self, secret_name: str, env_var: str) -> tuple[str | None, str]:
        """
        Resolve a single credential from multiple sources.

        Args:
            secret_name: Name in keyring.
            env_var: Environment variable name.

        Returns:
            Tuple of (value, source) or (None, "").
        """
        # 1. Check keyring
        if self._secret_store:
            value = self._secret_store.get(secret_name)
            if value:
                return value, "keyring"

        # 2. Check environment
        value = os.environ.get(env_var)
        if value:
            return value, "env"

        # 3. Check provider-specific files
        value = self._check_credential_files(env_var)
        if value:
            return value, "file"

        return None, ""

    def _check_credential_files(self, env_var: str) -> str | None:
        """Check provider-specific credential files."""
        # AWS credentials file
        if env_var.startswith("AWS_"):
            return self._parse_aws_credentials(env_var)

        # GCP credentials file
        if env_var == "GOOGLE_APPLICATION_CREDENTIALS":
            return self._find_gcp_credentials()

        return None

    def _parse_aws_credentials(self, env_var: str) -> str | None:
        """Parse AWS credentials file."""
        aws_creds_path = Path.home() / ".aws" / "credentials"
        if not aws_creds_path.exists():
            return None

        try:
            import configparser

            config = configparser.ConfigParser()
            config.read(aws_creds_path)

            profile = os.environ.get("AWS_PROFILE", "default")
            if profile not in config:
                return None

            mapping = {
                "AWS_ACCESS_KEY_ID": "aws_access_key_id",
                "AWS_SECRET_ACCESS_KEY": "aws_secret_access_key",
                "AWS_SESSION_TOKEN": "aws_session_token",
            }

            key = mapping.get(env_var)
            if key and key in config[profile]:
                return config[profile][key]

        except Exception as e:
            logger.warning(f"⚠️ Failed to parse AWS credentials file: {e}")

        return None

    def _find_gcp_credentials(self) -> str | None:
        """Find GCP credentials file path."""
        # Check common locations
        locations = [
            Path.home() / ".config" / "gcloud" / "application_default_credentials.json",
            Path("/etc/google/auth/application_default_credentials.json"),
        ]

        for path in locations:
            if path.exists():
                return str(path)

        return None

    def get_env_dict(self, provider: str) -> dict[str, str]:
        """
        Get credentials as environment variable dict.

        Useful for passing to subprocess or SDK initialization.

        Args:
            provider: Cloud provider name.

        Returns:
            Dict of environment variable name -> value.
        """
        creds = self.resolve(provider)
        return creds.credentials

    def is_configured(self, provider: str) -> bool:
        """Check if a provider has all required credentials."""
        return self.resolve(provider).is_complete

    def list_configured_providers(self) -> list[str]:
        """List providers with complete credentials."""
        return [p for p in PROVIDER_CREDENTIALS if self.is_configured(p)]

    def list_missing(self, provider: str) -> list[str]:
        """List missing credentials for a provider."""
        return self.resolve(provider).missing


# Convenience function
def get_credential_resolver() -> CredentialResolver:
    """Get the credential resolver singleton."""
    return CredentialResolver.get_instance()
