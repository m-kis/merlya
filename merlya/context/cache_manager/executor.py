"""
Cache Persistence Executor.
"""

import atexit
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

# Shared executor for background persistence tasks
_persistence_executor: Optional[ThreadPoolExecutor] = None
_persistence_executor_lock = threading.Lock()


def get_persistence_executor() -> ThreadPoolExecutor:
    """Get or create the shared persistence executor (thread-safe)."""
    global _persistence_executor
    if _persistence_executor is not None:
        return _persistence_executor

    with _persistence_executor_lock:
        if _persistence_executor is None:
            _persistence_executor = ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix="CachePersist"
            )
        return _persistence_executor


def shutdown_persistence_executor(wait: bool = False) -> None:
    """Shutdown the persistence executor.

    Args:
        wait: If True, wait for pending tasks to complete.
              If False (default), cancel pending tasks for faster shutdown.
    """
    global _persistence_executor
    with _persistence_executor_lock:
        if _persistence_executor is not None:
            _persistence_executor.shutdown(wait=wait, cancel_futures=not wait)
            _persistence_executor = None


# Register cleanup on interpreter exit
atexit.register(lambda: shutdown_persistence_executor(wait=False))
