"""
Tests for SmartExtractor IaC detection.

v0.9.0: Tests for infrastructure-as-code intent detection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from merlya.router.smart_extractor import (
    ExtractedEntities,
    SmartExtractor,
)


@pytest.fixture
def extractor() -> SmartExtractor:
    """Create a SmartExtractor with mock config."""
    config = MagicMock()
    return SmartExtractor(config)





class TestExtractedEntitiesModel:
    """Test ExtractedEntities model fields."""

    def test_default_values(self) -> None:
        """Default values should be empty/None."""
        entities = ExtractedEntities()
        assert entities.iac_tools == []
        assert entities.iac_operation is None
        assert entities.cloud_provider is None
        assert entities.infrastructure_resources == []

    def test_all_fields(self) -> None:
        """All IaC fields can be set."""
        entities = ExtractedEntities(
            iac_tools=["terraform", "ansible"],
            iac_operation="provision",
            cloud_provider="aws",
            infrastructure_resources=["vm", "vpc"],
        )
        assert entities.iac_tools == ["terraform", "ansible"]
        assert entities.iac_operation == "provision"
        assert entities.cloud_provider == "aws"
        assert entities.infrastructure_resources == ["vm", "vpc"]
