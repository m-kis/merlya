"""
Action Stack for robust Undo/Redo operations.

Implements Command Pattern for reversible actions.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from athena_ai.utils.logger import logger


class ActionStatus(Enum):
    """Status of an action."""
    PENDING = "pending"
    EXECUTED = "executed"
    UNDONE = "undone"
    FAILED = "failed"


@dataclass
class ActionMetadata:
    """Metadata for an action."""
    action_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    user: str = "system"
    target: str = "local"
    status: ActionStatus = ActionStatus.PENDING
    error: Optional[str] = None


class Action(ABC):
    """
    Abstract base class for reversible actions.

    Command Pattern: Each action knows how to execute and undo itself.
    """

    def __init__(self, metadata: ActionMetadata):
        self.metadata = metadata
        self._backup: Optional[Any] = None

    @abstractmethod
    def execute(self) -> bool:
        """
        Execute the action.

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def undo(self) -> bool:
        """
        Undo the action.

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def describe(self) -> str:
        """
        Get human-readable description of the action.

        Returns:
            Description string
        """
        pass

    def can_undo(self) -> bool:
        """
        Check if action can be undone.

        Returns:
            True if undo is possible
        """
        return self.metadata.status == ActionStatus.EXECUTED


class FileEditAction(Action):
    """
    Action for editing a file (local or remote).

    Stores original content for rollback.
    """

    def __init__(
        self,
        metadata: ActionMetadata,
        file_path: str,
        old_content: str,
        new_content: str,
        executor: Any = None  # ActionExecutor instance
    ):
        super().__init__(metadata)
        self.file_path = file_path
        self.old_content = old_content
        self.new_content = new_content
        self.executor = executor

    def execute(self) -> bool:
        """Write new content to file."""
        try:
            target = self.metadata.target

            if target in ["local", "localhost"]:
                # Local file write
                from pathlib import Path
                Path(self.file_path).write_text(self.new_content)
            else:
                # Remote file write via SSH
                if not self.executor:
                    raise ValueError("Executor required for remote file operations")

                # Use SFTP for safe remote write
                # For MVP, use cat with heredoc
                import shlex
                safe_content = shlex.quote(self.new_content)
                cmd = f"cat > {self.file_path} << 'ATHENA_EOF'\n{self.new_content}\nATHENA_EOF"
                result = self.executor.execute(target, cmd)

                if not result.get("success"):
                    raise Exception(result.get("stderr", "Unknown error"))

            self.metadata.status = ActionStatus.EXECUTED
            logger.info(f"Executed FileEditAction: {self.file_path} on {self.metadata.target}")
            return True

        except Exception as e:
            self.metadata.status = ActionStatus.FAILED
            self.metadata.error = str(e)
            logger.error(f"Failed to execute FileEditAction: {e}")
            return False

    def undo(self) -> bool:
        """Restore original content."""
        if not self.can_undo():
            logger.warning("Cannot undo action that wasn't successfully executed")
            return False

        try:
            target = self.metadata.target

            if target in ["local", "localhost"]:
                from pathlib import Path
                Path(self.file_path).write_text(self.old_content)
            else:
                if not self.executor:
                    raise ValueError("Executor required for remote operations")

                cmd = f"cat > {self.file_path} << 'ATHENA_EOF'\n{self.old_content}\nATHENA_EOF"
                result = self.executor.execute(target, cmd)

                if not result.get("success"):
                    raise Exception(result.get("stderr", "Unknown error"))

            self.metadata.status = ActionStatus.UNDONE
            logger.info(f"Undone FileEditAction: {self.file_path} on {self.metadata.target}")
            return True

        except Exception as e:
            self.metadata.error = str(e)
            logger.error(f"Failed to undo FileEditAction: {e}")
            return False

    def describe(self) -> str:
        """Human-readable description."""
        return f"Edit {self.file_path} on {self.metadata.target}"


class CommandAction(Action):
    """
    Action for command execution.

    Note: Not all commands are reversible!
    """

    def __init__(
        self,
        metadata: ActionMetadata,
        command: str,
        undo_command: Optional[str] = None,
        executor: Any = None
    ):
        super().__init__(metadata)
        self.command = command
        self.undo_command = undo_command
        self.executor = executor
        self._result: Optional[Dict] = None

    def execute(self) -> bool:
        """Execute command."""
        try:
            if not self.executor:
                raise ValueError("Executor required for command execution")

            target = self.metadata.target
            result = self.executor.execute(target, self.command)
            self._result = result

            if result.get("success"):
                self.metadata.status = ActionStatus.EXECUTED
                logger.info(f"Executed CommandAction: {self.command[:50]}...")
                return True
            else:
                self.metadata.status = ActionStatus.FAILED
                self.metadata.error = result.get("stderr", "Unknown error")
                return False

        except Exception as e:
            self.metadata.status = ActionStatus.FAILED
            self.metadata.error = str(e)
            logger.error(f"Failed to execute CommandAction: {e}")
            return False

    def undo(self) -> bool:
        """Execute undo command if available."""
        if not self.can_undo():
            logger.warning("Cannot undo action that wasn't successfully executed")
            return False

        if not self.undo_command:
            logger.warning(f"No undo command defined for: {self.command}")
            return False

        try:
            if not self.executor:
                raise ValueError("Executor required for undo")

            target = self.metadata.target
            result = self.executor.execute(target, self.undo_command)

            if result.get("success"):
                self.metadata.status = ActionStatus.UNDONE
                logger.info(f"Undone CommandAction with: {self.undo_command[:50]}...")
                return True
            else:
                self.metadata.error = result.get("stderr", "Unknown error")
                return False

        except Exception as e:
            self.metadata.error = str(e)
            logger.error(f"Failed to undo CommandAction: {e}")
            return False

    def can_undo(self) -> bool:
        """Can only undo if undo command is defined."""
        return super().can_undo() and self.undo_command is not None

    def describe(self) -> str:
        """Human-readable description."""
        return f"Execute '{self.command[:50]}...' on {self.metadata.target}"


class ActionStack:
    """
    Stack of actions with undo/redo capabilities.

    Follows Command Pattern for action history management.
    """

    def __init__(self, max_history: int = 100):
        """
        Initialize action stack.

        Args:
            max_history: Maximum number of actions to keep in history
        """
        self._executed_actions: List[Action] = []
        self._undone_actions: List[Action] = []
        self.max_history = max_history

    def push(self, action: Action) -> None:
        """
        Add an action to the stack and execute it.

        Args:
            action: Action to execute
        """
        success = action.execute()

        if success:
            self._executed_actions.append(action)

            # Clear redo stack (new action invalidates undone actions)
            self._undone_actions.clear()

            # Trim history if needed
            if len(self._executed_actions) > self.max_history:
                self._executed_actions.pop(0)

            logger.debug(f"Pushed action: {action.describe()}")
        else:
            logger.error(f"Failed to execute action: {action.describe()}")

    def undo(self) -> bool:
        """
        Undo the last executed action.

        Returns:
            True if undo was successful
        """
        if not self._executed_actions:
            logger.warning("No actions to undo")
            return False

        action = self._executed_actions.pop()

        if not action.can_undo():
            logger.warning(f"Action cannot be undone: {action.describe()}")
            self._executed_actions.append(action)  # Put it back
            return False

        success = action.undo()

        if success:
            self._undone_actions.append(action)
            logger.info(f"Undone action: {action.describe()}")
        else:
            # Put it back if undo failed
            self._executed_actions.append(action)
            logger.error(f"Failed to undo action: {action.describe()}")

        return success

    def redo(self) -> bool:
        """
        Redo the last undone action.

        Returns:
            True if redo was successful
        """
        if not self._undone_actions:
            logger.warning("No actions to redo")
            return False

        action = self._undone_actions.pop()
        success = action.execute()

        if success:
            self._executed_actions.append(action)
            logger.info(f"Redone action: {action.describe()}")
        else:
            # Put it back if redo failed
            self._undone_actions.append(action)
            logger.error(f"Failed to redo action: {action.describe()}")

        return success

    def get_history(self, limit: int = 10) -> List[str]:
        """
        Get recent action history.

        Args:
            limit: Maximum number of actions to return

        Returns:
            List of action descriptions
        """
        recent = self._executed_actions[-limit:]
        return [a.describe() for a in recent]

    def clear(self) -> None:
        """Clear all action history."""
        self._executed_actions.clear()
        self._undone_actions.clear()
        logger.info("Cleared action stack")

    def can_undo(self) -> bool:
        """Check if undo is possible."""
        return bool(self._executed_actions) and self._executed_actions[-1].can_undo()

    def can_redo(self) -> bool:
        """Check if redo is possible."""
        return bool(self._undone_actions)
