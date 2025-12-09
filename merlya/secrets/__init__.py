"""
Merlya Secrets - Secure secret management.

Uses keyring for secure storage with in-memory fallback.
"""

from merlya.secrets.loader import load_api_keys_from_keyring
from merlya.secrets.store import (
    SecretStore,
    get_secret,
    get_secret_store,
    has_secret,
    list_secrets,
    remove_secret,
    set_secret,
)

__all__ = [
    "SecretStore",
    "get_secret",
    "get_secret_store",
    "has_secret",
    "list_secrets",
    "load_api_keys_from_keyring",
    "remove_secret",
    "set_secret",
]
