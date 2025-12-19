"""
Merlya - AI-powered infrastructure assistant.

Version is read dynamically from package metadata.
"""

try:
    from importlib.metadata import version

    __version__ = version("merlya")
except Exception:
    __version__ = "0.7.7"  # Fallback
__author__ = "Cedric"
