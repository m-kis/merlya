"""
Merlya Provisioners - Terraform Backend.

Backend implementation using Terraform CLI.

v0.9.0: Initial implementation.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from merlya.provisioners.backends.base import (
    AbstractProvisionerBackend,
    BackendCapabilities,
    BackendError,
    BackendExecutionError,
    BackendNotAvailableError,
    BackendResult,
    BackendType,
)
from merlya.provisioners.providers.base import ProviderType

if TYPE_CHECKING:
    from merlya.core.context import SharedContext
    from merlya.provisioners.base import ProvisionerDeps
    from merlya.provisioners.providers.base import InstanceSpec


def _escape_hcl_string(value: str) -> str:
    """Escape special characters for HCL string values."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("${", "$${")  # Escape interpolation
    )


def _sanitize_resource_name(name: str) -> str:
    """Sanitize name for use as Terraform resource identifier.

    Terraform resource names must start with a letter or underscore
    and contain only letters, digits, and underscores.
    """
    # Replace invalid characters (including hyphens) with underscores
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    # Ensure starts with letter or underscore
    if sanitized and not sanitized[0].isalpha() and sanitized[0] != "_":
        sanitized = "_" + sanitized
    return sanitized or "_unnamed"


class TerraformBackend(AbstractProvisionerBackend):
    """
    Terraform CLI backend for infrastructure provisioning.

    Uses terraform init, plan, apply, destroy commands.
    """

    def __init__(
        self,
        ctx: SharedContext,
        deps: ProvisionerDeps,
        working_dir: str | None = None,
        var_file: str | None = None,
        variables: dict[str, Any] | None = None,
        backend_config: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize Terraform backend.

        Args:
            ctx: Shared context.
            deps: Provisioner dependencies.
            working_dir: Directory containing Terraform files.
            var_file: Path to .tfvars file.
            variables: Variables to pass via -var.
            backend_config: Backend configuration overrides.
        """
        super().__init__(ctx, deps, working_dir)
        self._var_file = var_file
        self._variables = variables or {}
        self._backend_config = backend_config or {}
        self._plan_file = ".merlya_tfplan"
        self._initialized = False
        self._temp_dir: str | None = None

    @property
    def backend_type(self) -> BackendType:
        return BackendType.TERRAFORM

    @property
    def name(self) -> str:
        return "Terraform"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            can_plan=True,
            can_diff=True,
            can_apply=True,
            can_destroy=True,
            can_rollback=True,
            supports_state=True,
            supports_modules=True,
            supports_workspaces=True,
        )

    async def is_available(self) -> bool:
        """Check if Terraform CLI is available."""
        return shutil.which("terraform") is not None

    async def _run_terraform(
        self,
        *args: str,
        capture_output: bool = True,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """
        Run terraform command safely using subprocess without shell.

        Args:
            *args: Command arguments.
            capture_output: Capture stdout/stderr.
            check: Raise on non-zero exit.

        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        cmd = ["terraform", *args]
        cwd = self._working_dir or self._temp_dir

        if cwd is None:
            raise BackendExecutionError(
                "No working directory configured for Terraform",
                backend=BackendType.TERRAFORM,
                operation=args[0] if args else "unknown",
                details={},
            )

        logger.debug(f"Running: {' '.join(cmd)} in {cwd}")

        # Use create_subprocess with explicit args (no shell injection possible)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE if capture_output else None,
            stderr=asyncio.subprocess.PIPE if capture_output else None,
        )

        stdout_bytes, stderr_bytes = await process.communicate()
        stdout = stdout_bytes.decode() if stdout_bytes else ""
        stderr = stderr_bytes.decode() if stderr_bytes else ""

        if check and process.returncode != 0:
            raise BackendExecutionError(
                f"Terraform command failed: {stderr or stdout}",
                backend=BackendType.TERRAFORM,
                operation=args[0] if args else "unknown",
                details={"returncode": process.returncode, "stderr": stderr},
            )

        return process.returncode or 0, stdout, stderr

    async def initialize(self) -> BackendResult:
        """Run terraform init."""
        result = BackendResult(operation="init")

        if not await self.is_available():
            raise BackendNotAvailableError(
                "Terraform CLI not found. Install from https://terraform.io",
                backend=BackendType.TERRAFORM,
                operation="init",
            )

        try:
            # Build init args
            init_args = ["init", "-input=false"]

            # Add backend config if provided
            for key, value in self._backend_config.items():
                init_args.append(f"-backend-config={key}={value}")

            _, stdout, stderr = await self._run_terraform(*init_args)

            result.success = True
            result.stdout = stdout
            result.stderr = stderr
            self._initialized = True

        except BackendExecutionError as e:
            result.success = False
            result.errors.append(str(e))
            result.stderr = e.details.get("stderr", "")

        result.finalize()
        return result

    async def plan(
        self,
        specs: list[InstanceSpec],
        provider: ProviderType,
    ) -> BackendResult:
        """Generate Terraform plan."""
        result = BackendResult(operation="plan")

        try:
            cwd = self._working_dir or self._temp_dir
            if cwd is None:
                if specs:
                    await self.generate_config(specs, provider)
                else:
                    raise BackendExecutionError(
                        "No working directory configured for Terraform",
                        backend=BackendType.TERRAFORM,
                        operation="plan",
                        details={},
                    )

            # Ensure initialized
            if not self._initialized:
                init_result = await self.initialize()
                if not init_result.success:
                    result.errors.extend(init_result.errors)
                    result.finalize()
                    return result

            # Build plan args
            plan_args = ["plan", "-input=false", f"-out={self._plan_file}"]

            # Add var file
            if self._var_file:
                plan_args.append(f"-var-file={self._var_file}")

            # Add variables
            for key, value in self._variables.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                plan_args.append(f"-var={key}={value}")

            _, stdout, stderr = await self._run_terraform(*plan_args)

            result.success = True
            result.stdout = stdout
            result.stderr = stderr

            # Parse plan output for resource counts
            result.output_data = self._parse_plan_output(stdout)

        except BackendExecutionError as e:
            result.success = False
            result.errors.append(str(e))

        result.finalize()
        return result

    async def apply(self) -> BackendResult:
        """Apply Terraform plan."""
        result = BackendResult(operation="apply")

        try:
            # Build apply args
            apply_args = ["apply", "-input=false", "-auto-approve"]

            # Use plan file if available (use consistent cwd logic)
            cwd = self._working_dir or self._temp_dir
            if cwd:
                plan_path = Path(cwd) / self._plan_file
                if plan_path.exists():
                    apply_args.append(self._plan_file)

            _, stdout, stderr = await self._run_terraform(*apply_args)

            result.success = True
            result.stdout = stdout
            result.stderr = stderr

            # Parse apply output
            apply_data = self._parse_apply_output(stdout)
            result.resources_created = apply_data.get("created", [])
            result.resources_updated = apply_data.get("updated", [])
            result.resources_deleted = apply_data.get("deleted", [])

            # Get outputs
            result.output_data = await self.get_outputs()

            # Store state for rollback
            result.rollback_data = await self.get_state()

        except BackendExecutionError as e:
            result.success = False
            result.errors.append(str(e))

        result.finalize()
        return result

    async def destroy(self, resource_ids: list[str] | None = None) -> BackendResult:
        """Destroy Terraform resources."""
        result = BackendResult(operation="destroy")

        try:
            # Ensure initialized
            if not self._initialized:
                init_result = await self.initialize()
                if not init_result.success:
                    result.errors.extend(init_result.errors)
                    result.finalize()
                    return result

            # Build destroy args
            destroy_args = ["destroy", "-input=false", "-auto-approve"]

            # Target specific resources if provided
            if resource_ids:
                for resource_id in resource_ids:
                    destroy_args.append(f"-target={resource_id}")

            # Add variables
            if self._var_file:
                destroy_args.append(f"-var-file={self._var_file}")
            for key, value in self._variables.items():
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                destroy_args.append(f"-var={key}={value}")

            _, stdout, stderr = await self._run_terraform(*destroy_args)

            result.success = True
            result.stdout = stdout
            result.stderr = stderr

            # Parse destroy output
            destroy_data = self._parse_destroy_output(stdout)
            result.resources_deleted = destroy_data.get("deleted", [])

        except BackendExecutionError as e:
            result.success = False
            result.errors.append(str(e))

        result.finalize()
        return result

    async def validate(self) -> BackendResult:
        """Validate Terraform configuration."""
        result = BackendResult(operation="validate")

        try:
            # Ensure initialized
            if not self._initialized:
                init_result = await self.initialize()
                if not init_result.success:
                    result.errors.extend(init_result.errors)
                    result.finalize()
                    return result

            _, stdout, _stderr = await self._run_terraform("validate", "-json")

            validate_result = json.loads(stdout)
            result.success = validate_result.get("valid", False)

            if not result.success:
                for diag in validate_result.get("diagnostics", []):
                    if diag.get("severity") == "error":
                        result.errors.append(diag.get("summary", "Unknown error"))
                    else:
                        result.warnings.append(diag.get("summary", ""))

        except (BackendExecutionError, json.JSONDecodeError) as e:
            result.success = False
            result.errors.append(str(e))

        result.finalize()
        return result

    async def get_outputs(self) -> dict[str, Any]:
        """Get Terraform outputs."""
        try:
            _, stdout, _ = await self._run_terraform("output", "-json", check=False)
            if stdout.strip():
                outputs = json.loads(stdout)
                return {k: v.get("value") for k, v in outputs.items()}
        except (json.JSONDecodeError, BackendError):
            pass
        return {}

    async def get_state(self) -> dict[str, Any]:
        """Get Terraform state."""
        try:
            _, stdout, _ = await self._run_terraform("show", "-json", check=False)
            if stdout.strip():
                result: dict[str, Any] = json.loads(stdout)
                return result
        except (json.JSONDecodeError, BackendError):
            pass
        return {}

    async def rollback(self, _rollback_data: dict[str, Any]) -> BackendResult:
        """Rollback by destroying created resources."""
        # For Terraform, rollback typically means destroy
        return await self.destroy()

    def _parse_plan_output(self, output: str) -> dict[str, Any]:
        """Parse terraform plan output for resource counts."""
        data: dict[str, Any] = {
            "to_create": 0,
            "to_update": 0,
            "to_delete": 0,
            "resources": [],
        }

        for line in output.split("\n"):
            line = line.strip()
            if "will be created" in line or "to add" in line:
                data["to_create"] += 1
            elif "will be updated" in line or "to change" in line:
                data["to_update"] += 1
            elif "will be destroyed" in line or "to destroy" in line:
                data["to_delete"] += 1

            # Extract resource names
            if line.startswith("# ") and ("will be" in line or "must be" in line):
                parts = line.split()
                if len(parts) >= 2:
                    data["resources"].append(parts[1])

        return data

    def _parse_apply_output(self, output: str) -> dict[str, list[str]]:
        """Parse terraform apply output."""
        data: dict[str, list[str]] = {
            "created": [],
            "updated": [],
            "deleted": [],
        }

        for line in output.split("\n"):
            line = line.strip()
            if "created" in line.lower() and ":" in line:
                resource = line.split(":")[0].strip()
                data["created"].append(resource)
            elif "modified" in line.lower() or "updated" in line.lower():
                resource = line.split(":")[0].strip()
                data["updated"].append(resource)
            elif "destroyed" in line.lower() or "deleted" in line.lower():
                resource = line.split(":")[0].strip()
                data["deleted"].append(resource)

        return data

    def _parse_destroy_output(self, output: str) -> dict[str, list[str]]:
        """Parse terraform destroy output."""
        data: dict[str, list[str]] = {"deleted": []}

        for line in output.split("\n"):
            line = line.strip()
            # Check for destroyed resources and try to extract resource name
            if ("destroyed" in line.lower() or "Destroy complete" in line) and ":" in line:
                resource = line.split(":")[0].strip()
                data["deleted"].append(resource)

        return data

    async def generate_config(
        self,
        specs: list[InstanceSpec],
        provider: ProviderType,
    ) -> str:
        """
        Generate Terraform configuration for specs.

        Returns path to generated config directory.
        """
        # Create temp directory for config
        self._temp_dir = tempfile.mkdtemp(prefix="merlya_tf_")
        self._working_dir = self._temp_dir

        # Generate main.tf
        config = self._generate_tf_config(specs, provider)
        config_path = Path(self._temp_dir) / "main.tf"
        config_path.write_text(config)

        logger.debug(f"Generated Terraform config at {self._temp_dir}")
        return self._temp_dir

    def _generate_tf_config(
        self,
        specs: list[InstanceSpec],
        provider: ProviderType,
    ) -> str:
        """Generate Terraform HCL configuration."""
        lines = []

        # Provider block
        if provider == ProviderType.AWS:
            lines.append('provider "aws" {')
            if self._deps.extra.get("region"):
                lines.append(f'  region = "{self._deps.extra["region"]}"')
            lines.append("}")
            lines.append("")

            # Resources
            for spec in specs:
                resource_name = _sanitize_resource_name(spec.name)
                lines.append(f'resource "aws_instance" "{resource_name}" {{')
                config = spec.to_provider_config(provider)
                lines.append(f'  ami           = "{_escape_hcl_string(config["ami"])}"')
                lines.append(f'  instance_type = "{_escape_hcl_string(config["instance_type"])}"')

                if config.get("subnet_id"):
                    lines.append(f'  subnet_id = "{_escape_hcl_string(config["subnet_id"])}"')
                if config.get("vpc_security_group_ids"):
                    sg_ids = ", ".join(
                        f'"{_escape_hcl_string(sg)}"' for sg in config["vpc_security_group_ids"]
                    )
                    lines.append(f"  vpc_security_group_ids = [{sg_ids}]")
                if config.get("key_name"):
                    lines.append(f'  key_name = "{_escape_hcl_string(config["key_name"])}"')
                if config.get("associate_public_ip_address"):
                    lines.append("  associate_public_ip_address = true")

                # Tags (escape values to prevent HCL injection)
                lines.append("  tags = {")
                lines.append(f'    Name = "{_escape_hcl_string(spec.name)}"')
                for key, value in spec.tags.items():
                    escaped_key = _escape_hcl_string(key)
                    escaped_value = _escape_hcl_string(value)
                    lines.append(f'    {escaped_key} = "{escaped_value}"')
                lines.append("  }")
                lines.append("}")
                lines.append("")

        return "\n".join(lines)

    def cleanup(self) -> None:
        """Clean up temporary files."""
        if self._temp_dir and Path(self._temp_dir).exists():
            shutil.rmtree(self._temp_dir)
            self._temp_dir = None
