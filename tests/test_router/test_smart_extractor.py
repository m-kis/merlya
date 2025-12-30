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


class TestIaCToolsExtraction:
    """Test IaC tools detection."""

    def test_terraform_detection(self, extractor: SmartExtractor) -> None:
        """Detect terraform tool."""
        result = extractor._extract_with_regex("run terraform apply")
        assert "terraform" in result.entities.iac_tools

    def test_ansible_detection(self, extractor: SmartExtractor) -> None:
        """Detect ansible tool."""
        result = extractor._extract_with_regex("ansible-playbook deploy.yml")
        assert "ansible" in result.entities.iac_tools

    def test_pulumi_detection(self, extractor: SmartExtractor) -> None:
        """Detect pulumi tool."""
        result = extractor._extract_with_regex("pulumi up --stack prod")
        assert "pulumi" in result.entities.iac_tools

    def test_cloudformation_normalization(self, extractor: SmartExtractor) -> None:
        """CFN should normalize to cloudformation."""
        result = extractor._extract_with_regex("deploy CFN stack")
        assert "cloudformation" in result.entities.iac_tools

    def test_k8s_normalization(self, extractor: SmartExtractor) -> None:
        """k8s should normalize to kubernetes."""
        result = extractor._extract_with_regex("k8s deployment")
        assert "kubernetes" in result.entities.iac_tools

    def test_multiple_tools(self, extractor: SmartExtractor) -> None:
        """Detect multiple IaC tools."""
        result = extractor._extract_with_regex("use terraform and ansible for deployment")
        assert "terraform" in result.entities.iac_tools
        assert "ansible" in result.entities.iac_tools


class TestCloudProviderExtraction:
    """Test cloud provider detection."""

    def test_aws_detection(self, extractor: SmartExtractor) -> None:
        """Detect AWS provider."""
        result = extractor._extract_with_regex("create EC2 instance on AWS")
        assert result.entities.cloud_provider == "aws"

    def test_gcp_detection(self, extractor: SmartExtractor) -> None:
        """Detect GCP provider."""
        result = extractor._extract_with_regex("deploy to Google Cloud")
        assert result.entities.cloud_provider == "gcp"

    def test_azure_detection(self, extractor: SmartExtractor) -> None:
        """Detect Azure provider."""
        result = extractor._extract_with_regex("provision Azure VM")
        assert result.entities.cloud_provider == "azure"

    def test_ovh_detection(self, extractor: SmartExtractor) -> None:
        """Detect OVH provider."""
        result = extractor._extract_with_regex("create instance on OVH")
        assert result.entities.cloud_provider == "ovh"

    def test_proxmox_detection(self, extractor: SmartExtractor) -> None:
        """Detect Proxmox provider."""
        result = extractor._extract_with_regex("create VM on Proxmox cluster")
        assert result.entities.cloud_provider == "proxmox"

    def test_vmware_detection(self, extractor: SmartExtractor) -> None:
        """Detect VMware provider."""
        result = extractor._extract_with_regex("deploy to vSphere")
        assert result.entities.cloud_provider == "vmware"


class TestInfrastructureResourcesExtraction:
    """Test infrastructure resources detection."""

    def test_vm_detection(self, extractor: SmartExtractor) -> None:
        """Detect VM/instance resources."""
        result = extractor._extract_with_regex("create a new VM with 4 CPUs")
        assert "vm" in result.entities.infrastructure_resources

    def test_vpc_subnet_detection(self, extractor: SmartExtractor) -> None:
        """Detect VPC and subnet resources."""
        result = extractor._extract_with_regex("create VPC with 3 subnets")
        assert "vpc" in result.entities.infrastructure_resources
        assert "subnets" in result.entities.infrastructure_resources

    def test_security_group_detection(self, extractor: SmartExtractor) -> None:
        """Detect security group resources."""
        result = extractor._extract_with_regex("configure security-group for web tier")
        assert "security-group" in result.entities.infrastructure_resources

    def test_load_balancer_detection(self, extractor: SmartExtractor) -> None:
        """Detect load balancer resources."""
        result = extractor._extract_with_regex("create ALB for the app")
        assert "alb" in result.entities.infrastructure_resources


class TestIaCOperationDetection:
    """Test IaC operation type detection."""

    def test_provision_operation(self, extractor: SmartExtractor) -> None:
        """Detect provision operation."""
        result = extractor._extract_with_regex("provision new VM on AWS")
        assert result.entities.iac_operation == "provision"

    def test_create_operation(self, extractor: SmartExtractor) -> None:
        """Create should map to provision."""
        result = extractor._extract_with_regex("create a new instance")
        assert result.entities.iac_operation == "provision"

    def test_update_operation(self, extractor: SmartExtractor) -> None:
        """Detect update operation."""
        result = extractor._extract_with_regex("update the VM configuration")
        assert result.entities.iac_operation == "update"

    def test_scale_operation(self, extractor: SmartExtractor) -> None:
        """Scale should map to update."""
        result = extractor._extract_with_regex("scale up CPU on the server")
        assert result.entities.iac_operation == "update"

    def test_destroy_operation(self, extractor: SmartExtractor) -> None:
        """Detect destroy operation."""
        result = extractor._extract_with_regex("terraform destroy the test infra")
        assert result.entities.iac_operation == "destroy"

    def test_teardown_operation(self, extractor: SmartExtractor) -> None:
        """Teardown should map to destroy."""
        result = extractor._extract_with_regex("teardown the VM infrastructure")
        assert result.entities.iac_operation == "destroy"

    def test_plan_operation(self, extractor: SmartExtractor) -> None:
        """Detect plan operation."""
        result = extractor._extract_with_regex("terraform plan")
        assert result.entities.iac_operation == "plan"

    def test_dryrun_operation(self, extractor: SmartExtractor) -> None:
        """Dry-run should map to plan."""
        result = extractor._extract_with_regex("dry-run the deployment")
        assert result.entities.iac_operation == "plan"


class TestIaCIntentClassification:
    """Test intent classification with IaC operations."""

    def test_provision_is_change(self, extractor: SmartExtractor) -> None:
        """Provision operations should be CHANGE."""
        result = extractor._extract_with_regex("provision new VM on AWS")
        assert result.intent.center == "CHANGE"

    def test_update_is_change(self, extractor: SmartExtractor) -> None:
        """Update operations should be CHANGE."""
        result = extractor._extract_with_regex("update the instance memory")
        assert result.intent.center == "CHANGE"

    def test_destroy_is_change(self, extractor: SmartExtractor) -> None:
        """Destroy operations should be CHANGE."""
        result = extractor._extract_with_regex("destroy the test infrastructure")
        assert result.intent.center == "CHANGE"

    def test_plan_is_diagnostic(self, extractor: SmartExtractor) -> None:
        """Plan operations should be DIAGNOSTIC."""
        result = extractor._extract_with_regex("terraform plan for the vpc")
        assert result.intent.center == "DIAGNOSTIC"

    def test_destroy_is_destructive(self, extractor: SmartExtractor) -> None:
        """Destroy operations should be marked destructive."""
        result = extractor._extract_with_regex("terraform destroy")
        assert result.intent.is_destructive is True


class TestIaCSeverity:
    """Test severity determination with IaC operations."""

    def test_destroy_in_prod_is_critical(self, extractor: SmartExtractor) -> None:
        """Destroy in production should be critical."""
        result = extractor._extract_with_regex("destroy the production infrastructure")
        assert result.intent.severity == "critical"

    def test_destroy_without_env_is_high(self, extractor: SmartExtractor) -> None:
        """Destroy without environment context should be high."""
        result = extractor._extract_with_regex("terraform destroy the test-vm")
        assert result.intent.severity == "high"

    def test_provision_in_prod_is_high(self, extractor: SmartExtractor) -> None:
        """Provision in production should be high."""
        result = extractor._extract_with_regex("create new VM on prod AWS")
        assert result.intent.severity == "high"

    def test_provision_in_staging_is_medium(self, extractor: SmartExtractor) -> None:
        """Provision in staging should be medium."""
        result = extractor._extract_with_regex("provision VM on staging")
        assert result.intent.severity == "medium"

    def test_plan_is_low(self, extractor: SmartExtractor) -> None:
        """Plan operations should be low severity."""
        result = extractor._extract_with_regex("terraform plan")
        assert result.intent.severity == "low"


class TestFrenchIaCPatterns:
    """Test French language IaC patterns."""

    def test_french_provision(self, extractor: SmartExtractor) -> None:
        """Detect French provision patterns."""
        result = extractor._extract_with_regex("créer une nouvelle VM sur AWS")
        assert result.entities.iac_operation == "provision"
        assert result.entities.cloud_provider == "aws"

    def test_french_update(self, extractor: SmartExtractor) -> None:
        """Detect French update patterns."""
        result = extractor._extract_with_regex("mettre à jour le serveur web-01")
        assert result.entities.iac_operation == "update"

    def test_french_destroy(self, extractor: SmartExtractor) -> None:
        """Detect French destroy patterns."""
        result = extractor._extract_with_regex("détruire l'infrastructure de test")
        assert result.entities.iac_operation == "destroy"


class TestDetermineSeverity:
    """Test the _determine_severity method directly."""

    def test_critical_destroy_in_prod(self, extractor: SmartExtractor) -> None:
        """Destroy in production is critical."""
        entities = ExtractedEntities(environment="production", iac_operation="destroy")
        severity = extractor._determine_severity(entities, is_destructive=True)
        assert severity == "critical"

    def test_critical_destructive_in_prod(self, extractor: SmartExtractor) -> None:
        """Any destructive command in production is critical."""
        entities = ExtractedEntities(environment="production")
        severity = extractor._determine_severity(entities, is_destructive=True)
        assert severity == "critical"

    def test_high_destroy_anywhere(self, extractor: SmartExtractor) -> None:
        """Destroy is high severity even without environment."""
        entities = ExtractedEntities(iac_operation="destroy")
        severity = extractor._determine_severity(entities, is_destructive=True)
        assert severity == "high"

    def test_high_provision_in_prod(self, extractor: SmartExtractor) -> None:
        """Provision in production is high severity."""
        entities = ExtractedEntities(environment="production", iac_operation="provision")
        severity = extractor._determine_severity(entities, is_destructive=False)
        assert severity == "high"

    def test_medium_staging_operations(self, extractor: SmartExtractor) -> None:
        """Staging operations are medium severity."""
        entities = ExtractedEntities(environment="staging", iac_operation="provision")
        severity = extractor._determine_severity(entities, is_destructive=False)
        assert severity == "medium"

    def test_medium_provision_no_env(self, extractor: SmartExtractor) -> None:
        """Provision without environment is medium severity."""
        entities = ExtractedEntities(iac_operation="provision")
        severity = extractor._determine_severity(entities, is_destructive=False)
        assert severity == "medium"

    def test_low_plan_operations(self, extractor: SmartExtractor) -> None:
        """Plan operations are low severity."""
        entities = ExtractedEntities(iac_operation="plan")
        severity = extractor._determine_severity(entities, is_destructive=False)
        assert severity == "low"

    def test_low_no_iac_non_destructive(self, extractor: SmartExtractor) -> None:
        """Non-IaC non-destructive is low severity."""
        entities = ExtractedEntities()
        severity = extractor._determine_severity(entities, is_destructive=False)
        assert severity == "low"


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
