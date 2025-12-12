"""
Merlya Parser Extractors.

High-level extraction functions that use the ParserService.
These are convenience wrappers for common parsing operations.
"""

from merlya.parser.extractors.host_query import extract_host_query
from merlya.parser.extractors.incident import extract_incident
from merlya.parser.extractors.log import extract_log_info

__all__ = [
    "extract_host_query",
    "extract_incident",
    "extract_log_info",
]
