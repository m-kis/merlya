"""
Tests for scan deduplication functionality.
"""
import asyncio

import pytest

from merlya.context.on_demand_scanner import OnDemandScanner, ScanConfig


class TestScanDeduplication:
    """Tests for preventing duplicate concurrent scans."""

    @pytest.fixture
    def scanner(self):
        """Create scanner with custom connectivity checker."""
        config = ScanConfig(
            max_retries=0,
            connect_timeout=1.0,
        )
        # Connectivity checker that always returns True for testing
        scanner = OnDemandScanner(
            config=config,
            connectivity_checker=lambda h, p: True
        )
        return scanner

    @pytest.mark.asyncio
    async def test_host_lock_created(self, scanner):
        """Test that host locks are created for each hostname."""
        lock1 = await scanner._get_host_lock("host1")
        lock2 = await scanner._get_host_lock("host2")

        assert lock1 is not lock2
        assert isinstance(lock1, asyncio.Lock)
        assert isinstance(lock2, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_same_host_lock_reused(self, scanner):
        """Test that same hostname gets same lock."""
        lock1 = await scanner._get_host_lock("host1")
        lock2 = await scanner._get_host_lock("host1")

        assert lock1 is lock2

    @pytest.mark.asyncio
    async def test_lock_cleanup_works(self, scanner):
        """Test that old locks are cleaned up."""
        import time

        # Lower threshold for testing - cleanup triggers when len > threshold
        scanner._lock_cleanup_threshold = 2

        # Create locks for 3 hosts (exceeds threshold of 2)
        await scanner._get_host_lock("host1")
        await scanner._get_host_lock("host2")
        await scanner._get_host_lock("host3")

        # Make host1 and host2 look old (> 1 hour)
        scanner._host_locks["host1"] = (scanner._host_locks["host1"][0], time.monotonic() - 7200)
        scanner._host_locks["host2"] = (scanner._host_locks["host2"][0], time.monotonic() - 7200)

        # Now we have 3 locks which is > 2 (threshold), add host4 to trigger cleanup
        await scanner._get_host_lock("host4")

        # host1 and host2 should be cleaned up (old and unlocked)
        assert "host1" not in scanner._host_locks
        assert "host2" not in scanner._host_locks
        # host3 and host4 should remain (recent)
        assert "host3" in scanner._host_locks
        assert "host4" in scanner._host_locks

    @pytest.mark.asyncio
    async def test_concurrent_scans_serialized(self, scanner):
        """Test that concurrent scans of same host are serialized."""
        scan_order = []
        scan_count = 0

        # Patch _perform_scan to track order
        original_perform = scanner._perform_scan

        async def tracked_perform(hostname, scan_type):
            nonlocal scan_count
            scan_count += 1
            current = scan_count
            scan_order.append(f"start_{current}")
            await asyncio.sleep(0.1)  # Simulate work
            result = await original_perform(hostname, scan_type)
            scan_order.append(f"end_{current}")
            return result

        scanner._perform_scan = tracked_perform

        # Start multiple concurrent scans for same host
        # Note: This tests the lock mechanism but scans may still happen
        # multiple times if cache doesn't return hit. The key is they
        # shouldn't overlap (start_2 shouldn't happen before end_1)
        tasks = [
            scanner.scan_host("testhost", force=True),
            scanner.scan_host("testhost", force=True),
        ]

        await asyncio.gather(*tasks)

        # Verify scans were serialized (not interleaved)
        # With serialization: start_1, end_1, start_2, end_2
        # Without: could be start_1, start_2, end_1, end_2
        assert len(scan_order) == 4
        # First scan should complete before second starts
        assert scan_order.index("end_1") < scan_order.index("start_2")
