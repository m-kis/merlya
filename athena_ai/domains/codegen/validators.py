"""
Validators for generated IaC code.

Provides syntax and semantic validation.
"""
from typing import Optional, List, Dict, Any
from athena_ai.utils.logger import logger


class ValidationResult:
    """Result of code validation."""

    def __init__(self, valid: bool, errors: List[str] = None, warnings: List[str] = None):
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []

    def __bool__(self) -> bool:
        return self.valid

    def __str__(self) -> str:
        if self.valid:
            return "✓ Validation passed"
        return f"✗ Validation failed:\n" + "\n".join(f"  - {e}" for e in self.errors)


class TerraformValidator:
    """Validate Terraform HCL code."""

    @staticmethod
    def validate(code: str) -> ValidationResult:
        """
        Validate Terraform code.

        Args:
            code: Terraform HCL code

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        # Check for balanced braces
        if code.count("{") != code.count("}"):
            errors.append("Unbalanced braces")

        # Check for required blocks
        if "provider" not in code and "terraform" not in code:
            warnings.append("No provider or terraform block found")

        # Check for resource or data blocks
        has_resources = "resource" in code or "data" in code or "module" in code
        if not has_resources:
            warnings.append("No resources, data sources, or modules defined")

        # Check for common syntax issues
        lines = code.split('\n')
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Check for missing equals sign in assignments
            if stripped and not stripped.startswith('#') and '=' not in stripped and '{' not in stripped and '}' not in stripped:
                # Could be a keyword or value
                if any(kw in stripped for kw in ['resource', 'provider', 'variable', 'output', 'data', 'module']):
                    continue
                # Might be missing =
                if '"' in stripped or "'" in stripped:
                    warnings.append(f"Line {i}: Possible missing '=' operator")

        valid = len(errors) == 0
        return ValidationResult(valid, errors, warnings)


class AnsibleValidator:
    """Validate Ansible playbook YAML."""

    @staticmethod
    def validate(code: str) -> ValidationResult:
        """
        Validate Ansible playbook.

        Args:
            code: Ansible YAML code

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        try:
            import yaml

            # Parse YAML
            parsed = yaml.safe_load(code)

            # Must be a list of plays
            if not isinstance(parsed, list):
                errors.append("Playbook must be a list of plays")
                return ValidationResult(False, errors, warnings)

            # Validate each play
            for i, play in enumerate(parsed):
                if not isinstance(play, dict):
                    errors.append(f"Play {i + 1} must be a dictionary")
                    continue

                # Required fields
                if "hosts" not in play:
                    errors.append(f"Play {i + 1} missing 'hosts' field")

                if "tasks" not in play and "roles" not in play:
                    warnings.append(f"Play {i + 1} has no tasks or roles")

                # Validate tasks if present
                if "tasks" in play:
                    tasks = play["tasks"]
                    if not isinstance(tasks, list):
                        errors.append(f"Play {i + 1} 'tasks' must be a list")
                    else:
                        for j, task in enumerate(tasks):
                            if not isinstance(task, dict):
                                errors.append(f"Play {i + 1}, Task {j + 1} must be a dictionary")

        except yaml.YAMLError as e:
            errors.append(f"YAML syntax error: {str(e)}")

        valid = len(errors) == 0
        return ValidationResult(valid, errors, warnings)


class DockerfileValidator:
    """Validate Dockerfile."""

    @staticmethod
    def validate(code: str) -> ValidationResult:
        """
        Validate Dockerfile.

        Args:
            code: Dockerfile content

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        lines = [line.strip() for line in code.split('\n') if line.strip() and not line.strip().startswith('#')]

        if not lines:
            errors.append("Dockerfile is empty")
            return ValidationResult(False, errors, warnings)

        # First instruction must be FROM (or ARG for build args)
        first_instruction = lines[0].split()[0].upper()
        if first_instruction not in ["FROM", "ARG"]:
            errors.append("First instruction must be FROM (or ARG)")

        # Check for FROM instruction
        has_from = any(line.split()[0].upper() == "FROM" for line in lines if line)
        if not has_from:
            errors.append("Dockerfile must contain FROM instruction")

        # Validate instruction keywords
        valid_instructions = {
            "FROM", "RUN", "CMD", "LABEL", "EXPOSE", "ENV",
            "ADD", "COPY", "ENTRYPOINT", "VOLUME", "USER",
            "WORKDIR", "ARG", "ONBUILD", "STOPSIGNAL", "HEALTHCHECK", "SHELL"
        }

        for i, line in enumerate(lines, 1):
            if not line:
                continue

            instruction = line.split()[0].upper()
            if instruction not in valid_instructions:
                warnings.append(f"Line {i}: Unknown instruction '{instruction}'")

        # Best practices
        if not any(line.split()[0].upper() == "USER" for line in lines):
            warnings.append("Consider adding USER instruction (avoid running as root)")

        valid = len(errors) == 0
        return ValidationResult(valid, errors, warnings)


class KubernetesValidator:
    """Validate Kubernetes manifests."""

    @staticmethod
    def validate(code: str) -> ValidationResult:
        """
        Validate Kubernetes manifest.

        Args:
            code: Kubernetes YAML code

        Returns:
            ValidationResult
        """
        errors = []
        warnings = []

        try:
            import yaml

            # Parse YAML (can be single doc or multi-doc)
            docs = list(yaml.safe_load_all(code))

            for i, doc in enumerate(docs):
                if not doc:
                    continue

                # Required fields
                required = ["apiVersion", "kind", "metadata"]
                for field in required:
                    if field not in doc:
                        errors.append(f"Document {i + 1} missing required field: {field}")

                # Validate metadata
                if "metadata" in doc:
                    metadata = doc["metadata"]
                    if not isinstance(metadata, dict):
                        errors.append(f"Document {i + 1} 'metadata' must be a dict")
                    elif "name" not in metadata:
                        errors.append(f"Document {i + 1} metadata missing 'name'")

                # Kind-specific validation
                kind = doc.get("kind", "")

                if kind in ["Deployment", "StatefulSet", "DaemonSet"]:
                    if "spec" not in doc:
                        errors.append(f"{kind} must have 'spec' field")
                    elif "selector" not in doc.get("spec", {}):
                        warnings.append(f"{kind} should have spec.selector")

                if kind == "Service":
                    spec = doc.get("spec", {})
                    if "selector" not in spec:
                        warnings.append("Service should have spec.selector")
                    if "ports" not in spec:
                        warnings.append("Service should define ports")

        except yaml.YAMLError as e:
            errors.append(f"YAML syntax error: {str(e)}")

        valid = len(errors) == 0
        return ValidationResult(valid, errors, warnings)
