"""
Role Inference Domain.

Responsible for:
- Inferring server roles from hostnames and services
- Generating human-readable role explanations
"""
from .service import RoleInferenceService

__all__ = ["RoleInferenceService"]
