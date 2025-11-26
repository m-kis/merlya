"""
Error Correction Domain.

Responsible for:
- Analyzing command failures
- Generating intelligent corrections
- Managing retry logic with exponential backoff
"""
from .service import ErrorCorrectionService

__all__ = ["ErrorCorrectionService"]
