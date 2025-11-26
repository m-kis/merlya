"""
Athena - AI-powered infrastructure orchestration CLI.

A natural language interface for managing infrastructure,
executing commands, and automating operations.
"""

try:
    from importlib.metadata import PackageNotFoundError, version
    try:
        __version__ = version("athena-ai")
    except PackageNotFoundError:
        # Package not installed, fallback to pyproject.toml
        __version__ = "0.2.0"
except ImportError:
    # Python < 3.8
    __version__ = "0.2.0"

__author__ = "Athena Contributors"
