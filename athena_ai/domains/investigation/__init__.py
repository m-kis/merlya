"""
Investigation Domain.

Responsible for determining how to investigate services/concepts:
- Direct services (mysql, nginx) → simple systemctl commands
- Concepts (backup, monitoring, logs) → LLM-generated investigation commands
- Generic → basic system checks

This is Correction 10 from the CHANGELOG.
"""
from .service import InvestigationService

__all__ = ["InvestigationService"]
