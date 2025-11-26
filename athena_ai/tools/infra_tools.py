"""
Infrastructure Tools using Preview, CodeGen, and Rollback.

Demonstrates integration of all new capabilities.
"""
from typing import Any, Dict
from pathlib import Path
from athena_ai.domains.tools.base import BaseTool, ToolMetadata, ToolParameter, ToolCategory
from athena_ai.domains.codegen.generator import CodeGenerator
from athena_ai.domains.preview.previewer import PreviewManager
from athena_ai.remediation.rollback import RollbackManager
from athena_ai.utils.logger import logger


class GenerateTerraformTool(BaseTool):
    """
    Generate Terraform configuration from specification.

    Integrates Code Generation with validation.
    """

    def __init__(self):
        super().__init__()
        self.codegen = CodeGenerator()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="generate_terraform",
            description="Generate Terraform infrastructure code from specification",
            category=ToolCategory.CODE_GENERATION,
            parameters=[
                ToolParameter(
                    name="provider",
                    type="string",
                    description="Cloud provider (aws, gcp, azure)",
                    required=True
                ),
                ToolParameter(
                    name="resources",
                    type="array",
                    description="List of resources to create",
                    required=True
                ),
                ToolParameter(
                    name="output_file",
                    type="string",
                    description="Optional output file path",
                    required=False
                )
            ],
            version="1.0.0"
        )

    def execute(self, **kwargs) -> Any:
        """Generate Terraform code."""
        provider = kwargs.get("provider")
        resources = kwargs.get("resources", [])
        output_file = kwargs.get("output_file")

        spec = {
            "provider": provider,
            "resources": resources,
            "variables": kwargs.get("variables", {}),
            "outputs": kwargs.get("outputs", {})
        }

        output_path = Path(output_file) if output_file else None

        try:
            code = self.codegen.generate("terraform", spec, output_path)

            result = f"✅ Generated Terraform configuration for {provider}\n\n"
            result += f"Resources: {len(resources)}\n\n"

            if output_path:
                result += f"📄 Written to: {output_path}\n\n"

            result += f"```hcl\n{code[:500]}...\n```"

            return result

        except Exception as e:
            logger.error(f"Failed to generate Terraform code: {e}")
            return f"❌ Failed to generate Terraform: {str(e)}"


class GenerateAnsibleTool(BaseTool):
    """Generate Ansible playbook from specification."""

    def __init__(self):
        super().__init__()
        self.codegen = CodeGenerator()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="generate_ansible",
            description="Generate Ansible playbook from specification",
            category=ToolCategory.CODE_GENERATION,
            parameters=[
                ToolParameter(
                    name="hosts",
                    type="string",
                    description="Target hosts or groups",
                    required=True
                ),
                ToolParameter(
                    name="tasks",
                    type="array",
                    description="List of tasks to perform",
                    required=True
                ),
                ToolParameter(
                    name="output_file",
                    type="string",
                    description="Optional output file path",
                    required=False
                )
            ],
            version="1.0.0"
        )

    def execute(self, **kwargs) -> Any:
        """Generate Ansible playbook."""
        hosts = kwargs.get("hosts")
        tasks = kwargs.get("tasks", [])
        output_file = kwargs.get("output_file")

        spec = {
            "hosts": hosts,
            "tasks": tasks,
            "vars": kwargs.get("vars", {}),
            "become": kwargs.get("become", False)
        }

        output_path = Path(output_file) if output_file else None

        try:
            code = self.codegen.generate("ansible", spec, output_path)

            result = f"✅ Generated Ansible playbook for {hosts}\n\n"
            result += f"Tasks: {len(tasks)}\n\n"

            if output_path:
                result += f"📄 Written to: {output_path}\n\n"

            result += f"```yaml\n{code[:500]}...\n```"

            return result

        except Exception as e:
            logger.error(f"Failed to generate Ansible playbook: {e}")
            return f"❌ Failed to generate Ansible: {str(e)}"


class GenerateDockerfileTool(BaseTool):
    """Generate Dockerfile from specification."""

    def __init__(self):
        super().__init__()
        self.codegen = CodeGenerator()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="generate_dockerfile",
            description="Generate Dockerfile from specification",
            category=ToolCategory.CODE_GENERATION,
            parameters=[
                ToolParameter(
                    name="base_image",
                    type="string",
                    description="Base Docker image (e.g., python:3.11)",
                    required=True
                ),
                ToolParameter(
                    name="workdir",
                    type="string",
                    description="Working directory in container",
                    required=False
                ),
                ToolParameter(
                    name="commands",
                    type="array",
                    description="List of RUN commands",
                    required=False
                ),
                ToolParameter(
                    name="output_file",
                    type="string",
                    description="Optional output file path",
                    required=False
                )
            ],
            version="1.0.0"
        )

    def execute(self, **kwargs) -> Any:
        """Generate Dockerfile."""
        base_image = kwargs.get("base_image")
        output_file = kwargs.get("output_file")

        spec = {
            "base_image": base_image,
            "workdir": kwargs.get("workdir", "/app"),
            "commands": kwargs.get("commands", []),
            "dependencies": kwargs.get("dependencies", []),
            "expose": kwargs.get("expose", []),
            "entrypoint": kwargs.get("entrypoint")
        }

        output_path = Path(output_file) if output_file else None

        try:
            code = self.codegen.generate("docker", spec, output_path)

            result = f"✅ Generated Dockerfile from {base_image}\n\n"

            if output_path:
                result += f"📄 Written to: {output_path}\n\n"

            result += f"```dockerfile\n{code}\n```"

            return result

        except Exception as e:
            logger.error(f"Failed to generate Dockerfile: {e}")
            return f"❌ Failed to generate Dockerfile: {str(e)}"


class PreviewFileEditTool(BaseTool):
    """Preview file changes before applying them."""

    def __init__(self):
        super().__init__()
        self.previewer = PreviewManager()

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="preview_file_edit",
            description="Preview changes to a file before applying them",
            category=ToolCategory.PREVIEW,
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Target host (local or remote)",
                    required=True
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to file",
                    required=True
                ),
                ToolParameter(
                    name="old_content",
                    type="string",
                    description="Current file content",
                    required=True
                ),
                ToolParameter(
                    name="new_content",
                    type="string",
                    description="Proposed new content",
                    required=True
                )
            ],
            version="1.0.0"
        )

    def execute(self, **kwargs) -> Any:
        """Generate preview of file changes."""
        target = kwargs.get("target")
        file_path = kwargs.get("file_path")
        old_content = kwargs.get("old_content")
        new_content = kwargs.get("new_content")

        try:
            preview = self.previewer.preview_file_edit(
                target=target,
                file_path=file_path,
                old_content=old_content,
                new_content=new_content
            )

            formatted = self.previewer.format_preview(preview)
            return formatted

        except Exception as e:
            logger.error(f"Failed to generate preview: {e}")
            return f"❌ Failed to preview changes: {str(e)}"


class RollbackTool(BaseTool):
    """Undo or redo the last action."""

    def __init__(self, env: str = "dev"):
        super().__init__()
        self.rollback_manager = RollbackManager(env=env)

    def get_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name="rollback_action",
            description="Undo the last action or redo an undone action",
            category=ToolCategory.INFRASTRUCTURE,
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform: 'undo', 'redo', or 'history'",
                    required=True
                )
            ],
            version="1.0.0"
        )

    def execute(self, **kwargs) -> Any:
        """Execute rollback operation."""
        operation = kwargs.get("operation", "undo")

        try:
            if operation == "undo":
                success = self.rollback_manager.undo_last_action()
                if success:
                    return "✅ Successfully undone last action"
                else:
                    return "❌ No action to undo or undo failed"

            elif operation == "redo":
                success = self.rollback_manager.redo_last_action()
                if success:
                    return "✅ Successfully redone last action"
                else:
                    return "❌ No action to redo or redo failed"

            elif operation == "history":
                history = self.rollback_manager.get_action_history(limit=10)
                if history:
                    result = "📜 Recent actions:\n\n"
                    for i, action in enumerate(history, 1):
                        result += f"{i}. {action}\n"
                    return result
                else:
                    return "No action history available"

            else:
                return f"❌ Unknown operation: {operation}. Use 'undo', 'redo', or 'history'"

        except Exception as e:
            logger.error(f"Rollback operation failed: {e}")
            return f"❌ Rollback failed: {str(e)}"
