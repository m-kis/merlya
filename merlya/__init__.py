"""
Merlya - AI-powered infrastructure orchestration CLI.

A natural language interface for managing infrastructure,
executing commands, and automating operations.
"""
import warnings

# Suppress noisy autogen warnings that don't affect functionality
# "Finish reason mismatch" occurs with some LLM providers but is harmless
warnings.filterwarnings(
    "ignore",
    message="Finish reason mismatch",
    category=UserWarning,
    module="autogen_agentchat"
)

try:
    from importlib.metadata import PackageNotFoundError, version
    try:
        __version__ = version("merlya")
    except PackageNotFoundError:
        # Package not installed, fallback to pyproject.toml
        __version__ = "0.3.0"
except ImportError:
    # Python < 3.8
    __version__ = "0.3.0"

__author__ = "Merlya Contributors"
