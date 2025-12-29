"""
Merlya Parser Backends.

Provides text parsing using pattern-based heuristics.
ONNX model-based parsing has been removed in v0.8.0.
"""

from merlya.parser.backends.base import ParserBackend
from merlya.parser.backends.heuristic import HeuristicBackend

__all__ = ["HeuristicBackend", "ParserBackend"]
