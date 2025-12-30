"""
Merlya Templates - Infrastructure template system.

Provides reusable IaC templates with variable substitution.

v0.9.0: Initial implementation.
"""

from merlya.templates.models import (
    IaCBackend,
    Template,
    TemplateCategory,
    TemplateInstance,
    TemplateOutput,
    TemplateVariable,
    VariableType,
)
from merlya.templates.registry import TemplateRegistry

__all__ = [
    "IaCBackend",
    "Template",
    "TemplateCategory",
    "TemplateInstance",
    "TemplateOutput",
    "TemplateRegistry",
    "TemplateVariable",
    "VariableType",
]
