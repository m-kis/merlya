"""
Entity Extraction Domain.

Responsible for extracting structured entities (target_host, service, intent)
from natural language queries using LLM-first approach with regex fallbacks.
"""
from .extractor import EntityExtractor

__all__ = ["EntityExtractor"]
