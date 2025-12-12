"""
Merlya Parser Backends.

Provides different backends for text parsing:
- HeuristicBackend: Pattern-based parsing (lightweight)
- ONNXParserBackend: ONNX model-based NER extraction (balanced/performance)
"""

from merlya.parser.backends.base import ParserBackend
from merlya.parser.backends.heuristic import HeuristicBackend
from merlya.parser.backends.onnx import ONNXParserBackend

__all__ = ["HeuristicBackend", "ONNXParserBackend", "ParserBackend"]
