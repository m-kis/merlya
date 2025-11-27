"""
Main scanner module.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from athena_ai.utils.logger import logger

from .models import LocalContext
from .scanners.files import scan_etc_files
from .scanners.network import scan_network
from .scanners.os_info import scan_os
from .scanners.resources import scan_resources
from .scanners.services import scan_processes, scan_services


class LocalScanner:
    """
    Scanner for the local machine.

    Stored in BDD, re-scanned only if:
    - No scan exists
    - Scan is older than TTL (default: 12h)
    """

    DEFAULT_TTL_HOURS = 12

    def __init__(self, repo: Optional[Any] = None):
        """Initialize scanner with optional repository."""
        self._repo = repo

    @property
    def repo(self):
        """Lazy load repository to avoid circular imports."""
        if self._repo is None:
            from athena_ai.memory.persistence.inventory_repository import get_inventory_repository
            self._repo = get_inventory_repository()
        return self._repo

    def get_or_scan(self, force: bool = False, ttl_hours: Optional[int] = None) -> LocalContext:
        """
        Get local context from cache or scan if necessary.

        Logic:
        1. If force=True → always scan
        2. If no existing scan → scan
        3. If scan exists and < TTL → return cached
        4. If scan exists and >= TTL → rescan

        Args:
            force: Force a new scan even if cache is valid
            ttl_hours: Custom TTL (default: 12h)

        Returns:
            LocalContext with local machine information
        """
        ttl = ttl_hours if ttl_hours is not None else self.DEFAULT_TTL_HOURS

        if not force:
            # Check for existing scan
            existing = self.repo.get_local_context()

            if existing:
                # Get scanned_at from _metadata (new structure) or root level (legacy)
                metadata = existing.get("_metadata", {})
                scanned_at_str = metadata.get("scanned_at") or existing.get("scanned_at")
                if scanned_at_str:
                    try:
                        scanned_at = datetime.fromisoformat(scanned_at_str)
                        # Normalize to UTC for consistent age calculation
                        if scanned_at.tzinfo is None:
                            scanned_at = scanned_at.replace(tzinfo=timezone.utc)
                        else:
                            scanned_at = scanned_at.astimezone(timezone.utc)
                        age_hours = (datetime.now(timezone.utc) - scanned_at).total_seconds() / 3600

                        if age_hours < ttl:
                            logger.debug(f"Using cached local context (age: {age_hours:.1f}h)")
                            return LocalContext.from_dict(existing)

                        logger.info(f"Local context expired ({age_hours:.1f}h > {ttl}h), rescanning...")
                    except (ValueError, TypeError):
                        logger.warning("Invalid scanned_at timestamp, rescanning...")

        # Perform scan
        logger.info("Scanning local machine...")
        context = self.scan_all()

        # Save to database
        self.repo.save_local_context(context.to_dict())
        logger.info(f"Local context saved (scanned at: {context.scanned_at})")

        return context

    def scan_all(self) -> LocalContext:
        """Perform a complete scan of the local machine."""
        return LocalContext(
            os_info=scan_os(),
            network=scan_network(),
            services=scan_services(),
            processes=scan_processes(),
            etc_files=scan_etc_files(),
            resources=scan_resources(),
            scanned_at=datetime.now(timezone.utc),
        )


# Convenience function
def get_local_scanner(repo: Optional[Any] = None) -> LocalScanner:
    """Get a local scanner instance."""
    return LocalScanner(repo)
