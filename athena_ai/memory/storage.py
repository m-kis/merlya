import json
from pathlib import Path
from typing import Any, Dict, Optional


class MemoryStorage:
    def __init__(self, env: str = "dev"):
        self.env = env
        self.base_path = Path.home() / ".athena" / "memory" / env
        self._ensure_structure()

    def _ensure_structure(self):
        """Create necessary directories."""
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "snapshots").mkdir(exist_ok=True)

    def save_context(self, context: Dict[str, Any]):
        """Save context to a JSON file."""
        context_file = self.base_path / "context.json"
        with open(context_file, "w") as f:
            json.dump(context, f, indent=2)

    def load_context(self) -> Optional[Dict[str, Any]]:
        """Load context from JSON file."""
        context_file = self.base_path / "context.json"
        if context_file.exists():
            with open(context_file, "r") as f:
                return json.load(f)
        return None

    def log_action(self, action: Dict[str, Any]):
        """Log an action to the actions log (JSONL)."""
        log_file = self.base_path / "actions.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(action) + "\n")
