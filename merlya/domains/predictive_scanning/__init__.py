"""
Predictive Scanning Domain.

Responsible for:
- Analyzing queries to predict likely target hosts
- Pre-scanning hosts in background to reduce latency
- Caching scan results for immediate availability
"""
from .service import PredictiveScanningService

__all__ = ["PredictiveScanningService"]
