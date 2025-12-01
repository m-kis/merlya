import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from merlya.executors.action_executor import ActionExecutor
from merlya.remediation.action_stack import ActionStack
from merlya.utils.logger import logger


class RollbackManager:
    """
    Enhanced Rollback Manager with ActionStack integration.

    Provides robust undo/redo capabilities with automatic snapshots.
    """

    def __init__(self, env: str = "dev"):
        self.backup_dir = Path.home() / ".merlya" / "memory" / env / "snapshots"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.executor = ActionExecutor()

        # NEW: Action stack for undo/redo
        self.action_stack = ActionStack(max_history=100)

        # Snapshot registry
        self.snapshot_file = self.backup_dir / "snapshots.json"
        self.snapshots: List[Dict] = self._load_snapshots()

    def _load_snapshots(self) -> List[Dict]:
        """Load snapshot registry from disk."""
        if self.snapshot_file.exists():
            try:
                with open(self.snapshot_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load snapshots: {e}")
        return []

    def _save_snapshots(self) -> None:
        """Save snapshot registry to disk."""
        try:
            with open(self.snapshot_file, "w") as f:
                json.dump(self.snapshots, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save snapshots: {e}")

    def create_snapshot(
        self,
        target: str,
        file_path: str,
        description: str = ""
    ) -> Optional[str]:
        """
        Create a snapshot of a file before modification.

        Args:
            target: Target host (local or remote)
            file_path: Path to file
            description: Optional description

        Returns:
            Snapshot ID or None if failed
        """
        timestamp = int(time.time())
        snapshot_id = f"snap_{timestamp}"

        backup_path = self._create_file_backup(target, file_path, timestamp)

        if backup_path:
            snapshot = {
                "id": snapshot_id,
                "timestamp": datetime.now().isoformat(),
                "target": target,
                "file_path": file_path,
                "backup_path": backup_path,
                "description": description
            }
            self.snapshots.append(snapshot)
            self._save_snapshots()

            logger.info(f"Created snapshot {snapshot_id} for {file_path} on {target}")
            return snapshot_id

        return None

    def prepare_rollback(self, target: str, action_type: str, details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare for a potential rollback before an action is executed.
        Returns a rollback plan.
        """
        timestamp = int(time.time())
        rollback_plan = {"id": f"rb_{timestamp}", "type": "none", "target": target}

        if action_type == "edit_file":
            file_path = details.get("path")
            if file_path:
                backup_path = self._create_file_backup(target, file_path, timestamp)
                if backup_path:
                    rollback_plan = {
                        "id": f"rb_{timestamp}",
                        "type": "restore_file",
                        "target": target,
                        "source": backup_path,
                        "destination": file_path
                    }

        # For service restarts, we might not have a direct "rollback" other than restart again
        # or revert config if changed previously.

        return rollback_plan

    def _create_file_backup(self, target: str, file_path: str, timestamp: int) -> Optional[str]:
        """Create a backup of a file (local or remote)."""
        filename = Path(file_path).name
        backup_name = f"{filename}.{timestamp}.bak"
        backup_path = str(self.backup_dir / backup_name)

        logger.info(f"Creating backup of {file_path} on {target} to {backup_path}")

        if target == "local" or target == "localhost":
            try:
                if Path(file_path).exists():
                    shutil.copy2(file_path, backup_path)
                    return backup_path
            except Exception as e:
                logger.error(f"Failed to backup local file: {e}")
        else:
            # Remote backup: read file content via SSH and write to local backup dir
            res = self.executor.execute(target, f"cat {file_path}")
            if res["success"]:
                with open(backup_path, "w") as f:
                    f.write(res["stdout"])
                return backup_path
            else:
                logger.error(f"Failed to read remote file for backup: {res.get('stderr')}")

        return None

    def execute_rollback(self, plan: Dict[str, Any]) -> bool:
        """Execute a rollback plan."""
        logger.info(f"Executing rollback: {plan}")

        if plan["type"] == "restore_file":
            source = plan["source"]
            dest = plan["destination"]
            target = plan["target"]

            if target == "local" or target == "localhost":
                try:
                    shutil.copy2(source, dest)
                    logger.info(f"Restored {dest} from {source}")
                    return True
                except Exception as e:
                    logger.error(f"Local rollback failed: {e}")
                    return False
            else:
                # NEW: Improved remote restore using heredoc (safer than shlex.quote)
                try:
                    with open(source, "r") as f:
                        content = f.read()

                    # Use heredoc for safe content transfer
                    cmd = f"cat > {dest} << 'MERLYA_ROLLBACK_EOF'\n{content}\nMERLYA_ROLLBACK_EOF"
                    result = self.executor.execute(target, cmd)

                    if result.get("success"):
                        logger.info(f"Restored {dest} on {target} from {source}")
                        return True
                    else:
                        logger.error(f"Remote rollback failed: {result.get('stderr')}")
                        return False

                except Exception as e:
                    logger.error(f"Remote rollback preparation failed: {e}")
                    return False

        return False

    def undo_last_action(self) -> bool:
        """
        Undo the last action using ActionStack.

        Returns:
            True if successful
        """
        return self.action_stack.undo()

    def redo_last_action(self) -> bool:
        """
        Redo the last undone action.

        Returns:
            True if successful
        """
        return self.action_stack.redo()

    def get_action_history(self, limit: int = 10) -> List[str]:
        """
        Get recent action history.

        Args:
            limit: Maximum number of actions to return

        Returns:
            List of action descriptions
        """
        return self.action_stack.get_history(limit)

    def list_snapshots(self, target: Optional[str] = None) -> List[Dict]:
        """
        List available snapshots.

        Args:
            target: Optional target filter

        Returns:
            List of snapshot dicts
        """
        if target:
            return [s for s in self.snapshots if s["target"] == target]
        return self.snapshots

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """
        Restore a specific snapshot.

        Args:
            snapshot_id: Snapshot ID to restore

        Returns:
            True if successful
        """
        snapshot = next((s for s in self.snapshots if s["id"] == snapshot_id), None)

        if not snapshot:
            logger.error(f"Snapshot {snapshot_id} not found")
            return False

        plan = {
            "type": "restore_file",
            "target": snapshot["target"],
            "source": snapshot["backup_path"],
            "destination": snapshot["file_path"]
        }

        return self.execute_rollback(plan)
