"""
Merlya Parser Backends.

Provides different backends for text parsing:
- HeuristicBackend: Pattern-based parsing (lightweight)
- ONNXBackend: ONNX model-based NER extraction (balanced/performance)
"""

from merlya.parser.backends.base import ParserBackend

__all__ = ["ParserBackend"]
