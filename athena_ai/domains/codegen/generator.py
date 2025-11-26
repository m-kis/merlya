"""
Code Generator for Infrastructure as Code.

Uses Strategy Pattern for different IaC formats.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader

from athena_ai.utils.logger import logger


class BaseGenerator(ABC):
    """
    Base class for code generators.

    Strategy Pattern: Each generator implements a specific format.
    """

    def __init__(self, template_dir: Optional[Path] = None):
        """
        Initialize generator with template directory.

        Args:
            template_dir: Path to Jinja2 templates
        """
        if template_dir is None:
            # Default to module's template directory
            template_dir = Path(__file__).parent / "templates"

        self.template_dir = template_dir
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True
        )

    @abstractmethod
    def generate(self, spec: Dict[str, Any]) -> str:
        """
        Generate code from specification.

        Args:
            spec: Specification dict

        Returns:
            Generated code as string
        """
        pass

    @abstractmethod
    def validate(self, code: str) -> bool:
        """
        Validate generated code syntax.

        Args:
            code: Generated code

        Returns:
            True if valid
        """
        pass


class TerraformGenerator(BaseGenerator):
    """Generate Terraform HCL configurations."""

    def generate(self, spec: Dict[str, Any]) -> str:
        """
        Generate Terraform configuration.

        Args:
            spec: Dict with:
                - provider: cloud provider (aws, gcp, azure)
                - resources: list of resources to create
                - variables: optional variables
                - outputs: optional outputs

        Returns:
            Terraform HCL code
        """
        provider = spec.get("provider", "aws")
        resources = spec.get("resources", [])
        variables = spec.get("variables", {})
        outputs = spec.get("outputs", {})

        template = self.env.get_template("terraform/main.tf.j2")

        code = template.render(
            provider=provider,
            resources=resources,
            variables=variables,
            outputs=outputs
        )

        logger.info(f"Generated Terraform config for {provider} with {len(resources)} resources")
        return code

    def validate(self, code: str) -> bool:
        """
        Basic Terraform syntax validation.

        Args:
            code: Terraform code

        Returns:
            True if syntax looks valid
        """
        # Basic checks - for full validation, would use terraform validate
        required_keywords = ["provider", "resource"]
        has_keywords = any(kw in code for kw in required_keywords)

        if not has_keywords:
            logger.warning("Terraform code missing required keywords")
            return False

        # Check for balanced braces
        if code.count("{") != code.count("}"):
            logger.warning("Terraform code has unbalanced braces")
            return False

        return True


class AnsibleGenerator(BaseGenerator):
    """Generate Ansible playbooks."""

    def generate(self, spec: Dict[str, Any]) -> str:
        """
        Generate Ansible playbook.

        Args:
            spec: Dict with:
                - hosts: target hosts or groups
                - tasks: list of tasks
                - vars: optional variables
                - become: whether to use sudo

        Returns:
            Ansible playbook YAML
        """
        hosts = spec.get("hosts", "all")
        tasks = spec.get("tasks", [])
        vars_dict = spec.get("vars", {})
        become = spec.get("become", False)

        template = self.env.get_template("ansible/playbook.yml.j2")

        code = template.render(
            hosts=hosts,
            tasks=tasks,
            vars=vars_dict,
            become=become
        )

        logger.info(f"Generated Ansible playbook for {hosts} with {len(tasks)} tasks")
        return code

    def validate(self, code: str) -> bool:
        """
        Basic Ansible YAML syntax validation.

        Args:
            code: Ansible playbook YAML

        Returns:
            True if syntax looks valid
        """
        try:
            import yaml
            parsed = yaml.safe_load(code)

            # Check for required structure
            if not isinstance(parsed, list):
                logger.warning("Ansible playbook must be a list of plays")
                return False

            for play in parsed:
                if "hosts" not in play or "tasks" not in play:
                    logger.warning("Each play must have 'hosts' and 'tasks'")
                    return False

            return True

        except yaml.YAMLError as e:
            logger.error(f"YAML syntax error: {e}")
            return False


class DockerfileGenerator(BaseGenerator):
    """Generate Dockerfiles."""

    def generate(self, spec: Dict[str, Any]) -> str:
        """
        Generate Dockerfile.

        Args:
            spec: Dict with:
                - base_image: base image (e.g., "python:3.11")
                - workdir: working directory
                - dependencies: list of dependencies or requirements file
                - commands: list of RUN commands
                - entrypoint: optional entrypoint
                - expose: ports to expose

        Returns:
            Dockerfile content
        """
        base_image = spec.get("base_image", "ubuntu:22.04")
        workdir = spec.get("workdir", "/app")
        dependencies = spec.get("dependencies", [])
        commands = spec.get("commands", [])
        entrypoint = spec.get("entrypoint")
        expose = spec.get("expose", [])

        template = self.env.get_template("docker/Dockerfile.j2")

        code = template.render(
            base_image=base_image,
            workdir=workdir,
            dependencies=dependencies,
            commands=commands,
            entrypoint=entrypoint,
            expose=expose
        )

        logger.info(f"Generated Dockerfile from {base_image}")
        return code

    def validate(self, code: str) -> bool:
        """
        Basic Dockerfile syntax validation.

        Args:
            code: Dockerfile content

        Returns:
            True if syntax looks valid
        """
        lines = code.strip().split('\n')

        if not lines:
            return False

        # Check for FROM instruction
        has_from = any(line.strip().startswith("FROM") for line in lines)

        if not has_from:
            logger.warning("Dockerfile must have FROM instruction")
            return False

        return True


class KubernetesGenerator(BaseGenerator):
    """Generate Kubernetes manifests."""

    def generate(self, spec: Dict[str, Any]) -> str:
        """
        Generate Kubernetes manifest.

        Args:
            spec: Dict with:
                - kind: resource kind (Deployment, Service, ConfigMap, etc.)
                - name: resource name
                - namespace: optional namespace
                - spec: resource-specific spec
                - labels: optional labels

        Returns:
            Kubernetes YAML manifest
        """
        kind = spec.get("kind", "Deployment")
        name = spec.get("name", "app")
        namespace = spec.get("namespace", "default")
        resource_spec = spec.get("spec", {})
        labels = spec.get("labels", {})

        template = self.env.get_template(f"k8s/{kind.lower()}.yml.j2")

        code = template.render(
            kind=kind,
            name=name,
            namespace=namespace,
            spec=resource_spec,
            labels=labels
        )

        logger.info(f"Generated Kubernetes {kind} manifest for {name}")
        return code

    def validate(self, code: str) -> bool:
        """
        Basic Kubernetes YAML validation.

        Args:
            code: Kubernetes manifest YAML

        Returns:
            True if syntax looks valid
        """
        try:
            import yaml
            parsed = yaml.safe_load(code)

            # Check for required fields
            required_fields = ["apiVersion", "kind", "metadata"]
            for field in required_fields:
                if field not in parsed:
                    logger.warning(f"Kubernetes manifest missing required field: {field}")
                    return False

            return True

        except yaml.YAMLError as e:
            logger.error(f"YAML syntax error: {e}")
            return False


class CodeGenerator:
    """
    Main code generator facade.

    Provides unified interface for all IaC generators.
    """

    def __init__(self, template_dir: Optional[Path] = None):
        """
        Initialize code generator.

        Args:
            template_dir: Optional custom template directory
        """
        self.template_dir = template_dir or (Path(__file__).parent / "templates")

        # Initialize generators (lazy loading)
        self._generators: Dict[str, BaseGenerator] = {}

    def _get_generator(self, format: str) -> BaseGenerator:
        """
        Get or create generator for format.

        Args:
            format: IaC format (terraform, ansible, docker, k8s)

        Returns:
            Generator instance
        """
        if format not in self._generators:
            if format == "terraform":
                self._generators[format] = TerraformGenerator(self.template_dir)
            elif format == "ansible":
                self._generators[format] = AnsibleGenerator(self.template_dir)
            elif format == "docker":
                self._generators[format] = DockerfileGenerator(self.template_dir)
            elif format == "k8s" or format == "kubernetes":
                self._generators[format] = KubernetesGenerator(self.template_dir)
            else:
                raise ValueError(f"Unknown format: {format}")

        return self._generators[format]

    def generate(
        self,
        format: str,
        spec: Dict[str, Any],
        output_file: Optional[Path] = None
    ) -> str:
        """
        Generate IaC code.

        Args:
            format: IaC format (terraform, ansible, docker, k8s)
            spec: Specification dict
            output_file: Optional file to write to

        Returns:
            Generated code
        """
        generator = self._get_generator(format)
        code = generator.generate(spec)

        # Validate generated code
        if not generator.validate(code):
            logger.warning(f"Generated {format} code may have syntax issues")

        # Write to file if requested
        if output_file:
            output_file.write_text(code)
            logger.info(f"Wrote {format} code to {output_file}")

        return code
