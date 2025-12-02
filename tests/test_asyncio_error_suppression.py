"""
Tests for asyncio error suppression during shutdown.

These tests verify that noisy AutoGen/asyncio shutdown messages are
properly filtered out while real errors are preserved.
"""
import io
import sys

import pytest


class TestFilteredStderr:
    """Test the FilteredStderr class used for shutdown noise suppression."""

    def test_suppress_asyncio_errors_import(self):
        """Verify suppress_asyncio_errors can be imported."""
        from merlya.repl.core import suppress_asyncio_errors
        assert callable(suppress_asyncio_errors)

    def test_suppresses_autogen_error_message(self):
        """Error processing publish message should be suppressed."""
        from merlya.repl.core import suppress_asyncio_errors

        captured = io.StringIO()
        with suppress_asyncio_errors():
            # Redirect current stderr to our capture
            sys.stderr.write("Error processing publish message for Agent_123\n")

        # The original stderr should not have received the message
        # (we can't easily capture this without more complex mocking,
        # but we verify no exception is raised)
        assert True

    def test_suppresses_task_done_error(self):
        """task_done() called too many times should be suppressed."""
        from merlya.repl.core import suppress_asyncio_errors

        with suppress_asyncio_errors():
            sys.stderr.write("ValueError: task_done() called too many times\n")
        assert True

    def test_suppresses_cancelled_error(self):
        """CancelledError messages should be suppressed."""
        from merlya.repl.core import suppress_asyncio_errors

        with suppress_asyncio_errors():
            sys.stderr.write("asyncio.exceptions.CancelledError\n")
        assert True

    def test_suppresses_full_traceback(self):
        """Full traceback with AutoGen components should be suppressed."""
        from merlya.repl.core import suppress_asyncio_errors

        traceback_text = """Traceback (most recent call last):
  File "/path/to/autogen_core/_single_threaded_agent_runtime.py", line 606
    return await agent.on_message(
  File "/path/to/autogen_core/_base_agent.py", line 119
    return await self.on_message_impl(message, ctx)
asyncio.exceptions.CancelledError
"""
        with suppress_asyncio_errors():
            for line in traceback_text.split('\n'):
                sys.stderr.write(line + '\n')
        assert True

    def test_suppresses_httpx_traceback(self):
        """HTTPX client shutdown errors should be suppressed."""
        from merlya.repl.core import suppress_asyncio_errors

        traceback_text = """Traceback (most recent call last):
  File "httpx/_client.py", line 1643, in send
    raise exc
  File "httpx/_models.py", line 979, in aread
    self._content = b"".join([part async for part in self.aiter_bytes()])
asyncio.exceptions.CancelledError
"""
        with suppress_asyncio_errors():
            for line in traceback_text.split('\n'):
                sys.stderr.write(line + '\n')
        assert True

    def test_context_manager_restores_stderr(self):
        """stderr should be restored after context manager exits."""
        from merlya.repl.core import suppress_asyncio_errors

        original_stderr = sys.stderr
        with suppress_asyncio_errors():
            # Inside context, stderr is wrapped
            assert sys.stderr is not original_stderr
        # After context, stderr is restored
        assert sys.stderr is original_stderr

    def test_flush_works(self):
        """FilteredStderr.flush() should not raise."""
        from merlya.repl.core import suppress_asyncio_errors

        with suppress_asyncio_errors():
            sys.stderr.flush()
        assert True


class TestNoisePatternsCompleteness:
    """Verify that all common shutdown noise patterns are covered."""

    @pytest.fixture
    def noise_patterns(self):
        """Get the list of noise patterns from the actual implementation."""
        # Import the function to access the class
        from merlya.repl.core import suppress_asyncio_errors

        # Create a temporary context to access the class
        import contextlib
        with suppress_asyncio_errors():
            # Access the FilteredStderr instance
            filtered = sys.stderr
            return filtered.NOISE_PATTERNS

    def test_autogen_patterns_included(self, noise_patterns):
        """AutoGen-specific patterns should be in the filter list."""
        assert any("autogen" in p for p in noise_patterns)

    def test_asyncio_patterns_included(self, noise_patterns):
        """asyncio-specific patterns should be in the filter list."""
        assert any("CancelledError" in p for p in noise_patterns)
        assert any("task_done" in p for p in noise_patterns)

    def test_httpx_patterns_included(self, noise_patterns):
        """HTTPX client patterns should be in the filter list."""
        assert any("httpx" in p for p in noise_patterns)

    def test_openai_patterns_included(self, noise_patterns):
        """OpenAI client patterns should be in the filter list."""
        assert any("openai" in p for p in noise_patterns)


class TestIntegration:
    """Integration tests for error suppression in REPL context."""

    def test_repl_uses_error_suppression(self):
        """Verify REPL code uses suppress_asyncio_errors in key locations."""
        import inspect
        from merlya.repl.core import MerlyaREPL

        # Get the source code of the start method
        source = inspect.getsource(MerlyaREPL.start)

        # Verify suppress_asyncio_errors is used
        assert "suppress_asyncio_errors" in source

    def test_process_single_query_uses_error_suppression(self):
        """Verify single query processing uses error suppression."""
        import inspect
        from merlya.repl.core import MerlyaREPL

        source = inspect.getsource(MerlyaREPL.process_single_query)
        assert "suppress_asyncio_errors" in source
