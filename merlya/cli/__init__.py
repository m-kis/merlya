"""
Merlya CLI - Command line interface.

Main entry point for the Merlya application.
"""

import asyncio
import sys

from loguru import logger


def main() -> None:
    """Main entry point for merlya CLI."""
    from merlya.core.logging import configure_logging

    # Configure logging
    configure_logging()

    try:
        from merlya.repl import run_repl

        asyncio.run(run_repl())

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
