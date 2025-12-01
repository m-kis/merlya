"""
Preview Manager for infrastructure actions.

Generates previews before executing critical operations.
"""
from typing import Any, Dict

from .engine import DiffEngine
from .formatters import DiffFormatter


class PreviewManager:
    """
    Manage previews for infrastructure actions.

    Shows what will change before executing.
    """

    def __init__(self):
        self.diff_engine = DiffEngine()
        self.formatter = DiffFormatter()

    def preview_file_edit(
        self,
        target: str,
        file_path: str,
        old_content: str,
        new_content: str
    ) -> Dict[str, Any]:
        """
        Preview file edit operation.

        Args:
            target: Target host (local or remote)
            file_path: Path to file being edited
            old_content: Current file content
            new_content: Proposed new content

        Returns:
            Dict with preview information
        """
        # Generate diff
        diff_lines = self.diff_engine.diff_strings(old_content, new_content)
        summary = self.diff_engine.get_change_summary(old_content, new_content)

        # Format for display
        formatted_diff = self.formatter.format_diff(
            diff_lines,
            title=f"Preview: {file_path} on {target}"
        )

        return {
            "action": "edit_file",
            "target": target,
            "file_path": file_path,
            "diff": diff_lines,
            "formatted_diff": formatted_diff,
            "summary": summary,
            "safe": summary["similarity"] > 0.5  # Flag risky changes
        }

    def preview_command(
        self,
        target: str,
        command: str,
        risk_level: str,
        reason: str = ""
    ) -> Dict[str, Any]:
        """
        Preview command execution.

        Args:
            target: Target host
            command: Command to execute
            risk_level: Risk level (LOW, MEDIUM, HIGH)
            reason: Why this command is needed

        Returns:
            Dict with preview information
        """
        return {
            "action": "execute_command",
            "target": target,
            "command": command,
            "risk_level": risk_level,
            "reason": reason,
            "safe": risk_level == "LOW"
        }

    def preview_terraform_plan(
        self,
        plan_output: str
    ) -> Dict[str, Any]:
        """
        Preview Terraform plan.

        Args:
            plan_output: Output from terraform plan

        Returns:
            Dict with preview information
        """
        # Parse terraform plan output
        lines = plan_output.split('\n')

        changes = {
            "to_add": 0,
            "to_change": 0,
            "to_destroy": 0
        }

        for line in lines:
            if "will be created" in line or "to add" in line:
                changes["to_add"] += 1
            elif "will be updated" in line or "to change" in line:
                changes["to_change"] += 1
            elif "will be destroyed" in line or "to destroy" in line:
                changes["to_destroy"] += 1

        return {
            "action": "terraform_plan",
            "changes": changes,
            "plan_output": plan_output,
            "safe": changes["to_destroy"] == 0  # Destruction is risky
        }

    def format_preview(self, preview: Dict[str, Any]) -> str:
        """
        Format preview for display.

        Args:
            preview: Preview dict from preview_* methods

        Returns:
            Formatted preview string
        """
        action = preview.get("action", "unknown")

        if action == "edit_file":
            output = []
            output.append(f"\n{'='*60}")
            output.append("📝 FILE EDIT PREVIEW")
            output.append(f"{'='*60}")
            output.append(f"Target: {preview['target']}")
            output.append(f"File: {preview['file_path']}")
            output.append(f"\n{self.formatter.format_change_summary(preview['summary'])}")
            output.append(f"\n{preview['formatted_diff']}")
            output.append(f"\n{'='*60}")

            if not preview.get("safe", True):
                output.append("⚠️  WARNING: Large changes detected!")

            return "\n".join(output)

        elif action == "execute_command":
            output = []
            output.append(f"\n{'='*60}")
            output.append("⚙️  COMMAND EXECUTION PREVIEW")
            output.append(f"{'='*60}")
            output.append(f"Target: {preview['target']}")
            output.append(f"Command: {preview['command']}")
            output.append(f"Risk Level: {preview['risk_level']}")
            if preview.get("reason"):
                output.append(f"Reason: {preview['reason']}")
            output.append(f"{'='*60}")

            if preview['risk_level'] in ["MEDIUM", "HIGH"]:
                output.append("⚠️  This command requires confirmation!")

            return "\n".join(output)

        elif action == "terraform_plan":
            output = []
            output.append(f"\n{'='*60}")
            output.append("🏗️  TERRAFORM PLAN PREVIEW")
            output.append(f"{'='*60}")
            changes = preview['changes']
            output.append(f"Resources to add: [green]+{changes['to_add']}[/green]")
            output.append(f"Resources to change: [yellow]~{changes['to_change']}[/yellow]")
            output.append(f"Resources to destroy: [red]-{changes['to_destroy']}[/red]")
            output.append(f"\n{preview['plan_output'][:500]}...")
            output.append(f"{'='*60}")

            if not preview.get("safe", True):
                output.append("⚠️  WARNING: Resources will be destroyed!")

            return "\n".join(output)

        return str(preview)
