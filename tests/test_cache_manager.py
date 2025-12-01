"""
Tests for CacheManager functionality.
"""
import time
import unittest

from merlya.context.cache_manager import CacheConfig, CacheManager


class TestCacheManager(unittest.TestCase):
    def setUp(self):
        # Use a fresh instance for each test
        self.config = CacheConfig(
            ttl_config={"test": 1},  # 1 second TTL for tests
            cleanup_interval=1,
            max_entries=5
        )
        self.manager = CacheManager(self.config)

    def test_basic_set_get(self):
        """Test basic set and get operations."""
        self.manager.set("key1", "value1", "test")
        value = self.manager.get("key1", "test")
        self.assertEqual(value, "value1")

    def test_ttl_expiration(self):
        """Test TTL expiration."""
        self.manager.set("key2", "value2", "test", ttl=1)
        time.sleep(1.1)
        value = self.manager.get("key2", "test")
        self.assertIsNone(value)

    def test_eviction(self):
        """Test LRU eviction."""
        # Fill cache
        for i in range(5):
            self.manager.set(f"k{i}", f"v{i}", "test")

        # Access k0 to make it recently used
        self.manager.get("k0", "test")

        # Add one more to trigger eviction
        self.manager.set("k5", "v5", "test")

        # k1 should be evicted (oldest accessed)
        # k0 should still be there
        self.assertIsNone(self.manager.get("k1", "test"))
        self.assertIsNotNone(self.manager.get("k0", "test"))
        self.assertIsNotNone(self.manager.get("k5", "test"))

    def test_stats(self):
        """Test statistics tracking."""
        self.manager.set("s1", "v1", "test")
        self.manager.get("s1", "test")  # Hit
        self.manager.get("s2", "test")  # Miss

        stats = self.manager.get_stats()["stats"]
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_get_or_set(self):
        """Test get_or_set atomic operation."""
        called = 0

        def factory():
            nonlocal called
            called += 1
            return "computed"

        # First call computes
        val1 = self.manager.get_or_set("gs1", factory, "test")
        self.assertEqual(val1, "computed")
        self.assertEqual(called, 1)

        # Second call returns cached
        val2 = self.manager.get_or_set("gs1", factory, "test")
        self.assertEqual(val2, "computed")
        self.assertEqual(called, 1)


if __name__ == "__main__":
    unittest.main()
