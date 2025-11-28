"""Tests for log_prefix helper and USE_EMOJI_LOGS configuration."""
import os
import unittest
from unittest.mock import patch


class TestLogPrefix(unittest.TestCase):
    """Test cases for the log_prefix helper function."""

    def test_emoji_enabled_by_default(self):
        """Emoji logs should be enabled when USE_EMOJI_LOGS is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove USE_EMOJI_LOGS if present
            os.environ.pop("USE_EMOJI_LOGS", None)
            # Need to reimport to pick up env change
            from athena_ai.utils.logger import use_emoji_logs, log_prefix
            self.assertTrue(use_emoji_logs())
            self.assertEqual(log_prefix("🔄"), "🔄")

    def test_emoji_enabled_explicit(self):
        """Emoji logs should be enabled when USE_EMOJI_LOGS=1."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "1"}):
            from athena_ai.utils.logger import use_emoji_logs, log_prefix
            self.assertTrue(use_emoji_logs())
            self.assertEqual(log_prefix("❌"), "❌")

    def test_emoji_disabled_zero(self):
        """Emoji logs should be disabled when USE_EMOJI_LOGS=0."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "0"}):
            from athena_ai.utils.logger import use_emoji_logs, log_prefix
            self.assertFalse(use_emoji_logs())
            self.assertEqual(log_prefix("🔄"), "[RETRY]")
            self.assertEqual(log_prefix("⚠️"), "[WARN]")
            self.assertEqual(log_prefix("💀"), "[DEAD]")
            self.assertEqual(log_prefix("⏱️"), "[TIMEOUT]")
            self.assertEqual(log_prefix("🌐"), "[CONNECT]")
            self.assertEqual(log_prefix("✓"), "[OK]")
            self.assertEqual(log_prefix("✅"), "[OK]")
            self.assertEqual(log_prefix("❌"), "[ERROR]")
            self.assertEqual(log_prefix("🔒"), "[CLOSE]")
            self.assertEqual(log_prefix("🧹"), "[CLEANUP]")

    def test_emoji_disabled_false(self):
        """Emoji logs should be disabled when USE_EMOJI_LOGS=false."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "false"}):
            from athena_ai.utils.logger import use_emoji_logs, log_prefix
            self.assertFalse(use_emoji_logs())
            self.assertEqual(log_prefix("❌"), "[ERROR]")

    def test_emoji_disabled_no(self):
        """Emoji logs should be disabled when USE_EMOJI_LOGS=no."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "no"}):
            from athena_ai.utils.logger import use_emoji_logs, log_prefix
            self.assertFalse(use_emoji_logs())

    def test_emoji_disabled_off(self):
        """Emoji logs should be disabled when USE_EMOJI_LOGS=off."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "off"}):
            from athena_ai.utils.logger import use_emoji_logs, log_prefix
            self.assertFalse(use_emoji_logs())

    def test_emoji_disabled_case_insensitive(self):
        """USE_EMOJI_LOGS should be case-insensitive."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "FALSE"}):
            from athena_ai.utils.logger import use_emoji_logs
            self.assertFalse(use_emoji_logs())

    def test_unknown_emoji_returns_empty_when_disabled(self):
        """Unknown emojis should return empty string when disabled."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "0"}):
            from athena_ai.utils.logger import log_prefix
            self.assertEqual(log_prefix("🎉"), "")

    def test_unknown_emoji_returns_emoji_when_enabled(self):
        """Unknown emojis should return the emoji when enabled."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "1"}):
            from athena_ai.utils.logger import log_prefix
            self.assertEqual(log_prefix("🎉"), "🎉")


class TestSSHConnectionPoolLogMessages(unittest.TestCase):
    """Integration tests to verify SSH connection pool logs correctly with flag off."""

    def test_log_messages_no_emoji_when_disabled(self):
        """Verify log messages use ASCII prefixes when USE_EMOJI_LOGS=0."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "0"}):
            from athena_ai.utils.logger import log_prefix

            # Simulate the log message formats from ssh_connection_pool.py
            msg1 = f"{log_prefix('🔄')} Circuit breaker timeout expired for test-host, resetting"
            self.assertIn("[RETRY]", msg1)
            self.assertNotIn("🔄", msg1)

            msg2 = f"{log_prefix('⚠️')} SSH failure recorded for test-host: 1 failure(s)"
            self.assertIn("[WARN]", msg2)
            self.assertNotIn("⚠️", msg2)

            msg3 = f"{log_prefix('❌')} Failed to connect to test@test-host: Connection refused"
            self.assertIn("[ERROR]", msg3)
            self.assertNotIn("❌", msg3)

            msg4 = f"{log_prefix('✓')} Established SSH connection to test@test-host"
            self.assertIn("[OK]", msg4)
            self.assertNotIn("✓", msg4)

    def test_log_messages_have_emoji_when_enabled(self):
        """Verify log messages use emoji prefixes when USE_EMOJI_LOGS=1."""
        with patch.dict(os.environ, {"USE_EMOJI_LOGS": "1"}):
            from athena_ai.utils.logger import log_prefix

            msg1 = f"{log_prefix('🔄')} Circuit breaker timeout expired for test-host, resetting"
            self.assertIn("🔄", msg1)
            self.assertNotIn("[RETRY]", msg1)

            msg2 = f"{log_prefix('❌')} Failed to connect to test@test-host: Connection refused"
            self.assertIn("❌", msg2)
            self.assertNotIn("[ERROR]", msg2)


if __name__ == "__main__":
    unittest.main()
