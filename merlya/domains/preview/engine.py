"""
Diff Engine for file and configuration comparisons.

Uses standard library difflib for simplicity (KISS principle).
"""
import difflib
from pathlib import Path
from typing import List

from merlya.utils.logger import logger


class DiffEngine:
    """
    Engine for computing diffs between files, strings, or configurations.

    KISS: Uses stdlib difflib, no external dependencies needed.
    """

    @staticmethod
    def diff_strings(
        old: str,
        new: str,
        context_lines: int = 3
    ) -> List[str]:
        """
        Generate unified diff between two strings.

        Args:
            old: Original content
            new: New content
            context_lines: Number of context lines around changes

        Returns:
            List of diff lines (unified diff format)
        """
        old_lines = old.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="before",
            tofile="after",
            lineterm="",
            n=context_lines
        )

        return list(diff)

    @staticmethod
    def diff_files(
        old_path: Path,
        new_path: Path,
        context_lines: int = 3
    ) -> List[str]:
        """
        Generate diff between two files.

        Args:
            old_path: Path to original file
            new_path: Path to new file
            context_lines: Number of context lines

        Returns:
            List of diff lines
        """
        try:
            with open(old_path, "r") as f:
                old_content = f.read()
            with open(new_path, "r") as f:
                new_content = f.read()

            return DiffEngine.diff_strings(old_content, new_content, context_lines)

        except Exception as e:
            logger.error(f"Failed to diff files: {e}")
            return [f"Error: {str(e)}"]

    @staticmethod
    def similarity_ratio(old: str, new: str) -> float:
        """
        Calculate similarity ratio between two strings.

        Args:
            old: Original content
            new: New content

        Returns:
            Similarity ratio (0.0 to 1.0)
        """
        matcher = difflib.SequenceMatcher(None, old, new)
        return matcher.ratio()

    @staticmethod
    def get_change_summary(old: str, new: str) -> dict:
        """
        Get summary of changes between two strings.

        Args:
            old: Original content
            new: New content

        Returns:
            Dict with changes summary
        """
        old_lines = old.splitlines()
        new_lines = new.splitlines()

        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))

        added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
        removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))

        return {
            "added_lines": added,
            "removed_lines": removed,
            "total_changes": added + removed,
            "old_line_count": len(old_lines),
            "new_line_count": len(new_lines),
            "similarity": DiffEngine.similarity_ratio(old, new)
        }
