from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from athena_ai.memory.persistence.host_repository import HostRepository
from athena_ai.memory.persistence.session_repository import SessionRepository
from athena_ai.utils.logger import logger


class SessionManager:
    """
    Manages work sessions like Claude Code to never lose context.
    Stores all queries, responses, actions, and context in SQLite + Markdown.

    Refactored to delegate persistence to HostRepository and SessionRepository.
    """

    def __init__(self, env: str = "dev"):
        self.env = env
        self.base_dir = Path.home() / ".athena" / env
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = self.base_dir / "sessions.db"
        self.sessions_md_dir = self.base_dir / "sessions"
        self.sessions_md_dir.mkdir(exist_ok=True)

        self.current_session_id: Optional[str] = None

        # Initialize repositories
        self.host_repo = HostRepository(str(self.db_path))
        self.session_repo = SessionRepository(str(self.db_path))

        logger.debug(f"Session database initialized at {self.db_path}")

    def start_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Start a new work session."""
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_session_id = session_id

        self.session_repo.start_session(session_id, metadata)

        # Create session markdown file
        self._create_session_md(session_id)

        logger.info(f"Started session: {session_id}")
        return session_id

    def _create_session_md(self, session_id: str):
        """Create a markdown file for the session."""
        md_path = self.sessions_md_dir / f"{session_id}.md"

        content = f"""# Athena Session - {session_id}

**Environment**: {self.env}
**Started**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Status**: Active

---

## Queries

"""
        md_path.write_text(content)

    def log_query(
        self,
        query: str,
        response: str,
        response_type: str = "text",
        actions_count: int = 0,
        execution_time_ms: int = 0
    ) -> int:
        """Log a user query and its response."""
        if not self.current_session_id:
            self.start_session()

        query_id = self.session_repo.log_query(
            self.current_session_id,
            query,
            response,
            response_type,
            actions_count,
            execution_time_ms
        )

        # Append to markdown
        self._append_to_session_md(query, response, actions_count)

        logger.debug(f"Logged query #{query_id} in session {self.current_session_id}")
        return query_id

    def _append_to_session_md(self, query: str, response: str, actions_count: int):
        """Append query/response to session markdown file."""
        md_path = self.sessions_md_dir / f"{self.current_session_id}.md"

        timestamp = datetime.now().strftime("%H:%M:%S")

        content = f"""
### {timestamp} - Query

**Q**: {query}

**A**:
```
{response}
```

**Actions executed**: {actions_count}

---

"""
        with open(md_path, 'a') as f:
            f.write(content)

    def log_action(
        self,
        query_id: int,
        target: str,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        risk_level: str,
        duration_ms: int = 0
    ):
        """Log an executed action."""
        if not self.current_session_id:
            logger.warning("No active session, cannot log action")
            return

        self.session_repo.log_action(
            self.current_session_id,
            query_id,
            target,
            command,
            exit_code,
            stdout,
            stderr,
            risk_level,
            duration_ms
        )

        logger.debug(f"Logged action: {command} on {target}")

    def save_context_snapshot(self, context_data: Dict[str, Any], snapshot_type: str = "auto"):
        """Save a snapshot of the current context."""
        if not self.current_session_id:
            return

        self.session_repo.save_context_snapshot(
            self.current_session_id,
            context_data,
            snapshot_type
        )

        logger.debug(f"Saved context snapshot ({snapshot_type})")

    def end_session(self):
        """End the current session."""
        if not self.current_session_id:
            return

        self.session_repo.end_session(self.current_session_id)

        # Finalize markdown
        md_path = self.sessions_md_dir / f"{self.current_session_id}.md"
        with open(md_path, 'a') as f:
            f.write(f"\n\n---\n**Session ended**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        logger.info(f"Ended session: {self.current_session_id}")
        self.current_session_id = None

    def get_session_history(self, session_id: str) -> Dict[str, Any]:
        """Get full history of a session."""
        return self.session_repo.get_session_history(session_id)

    def list_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent sessions."""
        return self.session_repo.list_sessions(limit)

    def resume_session(self, session_id: str) -> bool:
        """Resume a previous session."""
        success = self.session_repo.resume_session(session_id)
        if success:
            self.current_session_id = session_id
            logger.info(f"Resumed session: {session_id}")
        else:
            logger.error(f"Session {session_id} not found")
        return success

    def get_conversation_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent conversation history for current session.
        Used to provide context to the AI.
        """
        if not self.current_session_id:
            return []
        return self.session_repo.get_conversation_history(self.current_session_id, limit)

    def export_session_md(self, session_id: str, output_path: Optional[Path] = None) -> Path:
        """Export session to markdown file."""
        if not output_path:
            output_path = Path(f"session_{session_id}.md")

        history = self.get_session_history(session_id)

        content = f"""# Athena Session Export

**Session ID**: {session_id}
**Started**: {history['session']['started_at']}
**Ended**: {history['session']['ended_at'] or 'Active'}
**Total Queries**: {history['session']['total_queries']}
**Total Actions**: {history['session']['total_actions']}

---

## Query History

"""

        for query in history['queries']:
            content += f"""
### Query at {query['timestamp']}

**Q**: {query['query']}

**Response**:
```
{query['response'][:500]}...
```

**Actions**: {query['actions_count']} | **Time**: {query['execution_time_ms']}ms

---

"""

        content += "\n## Actions Log\n\n"
        for action in history['actions']:
            content += f"- `{action['timestamp']}` [{action['target']}] {action['command']} (exit: {action['exit_code']}, risk: {action['risk_level']})\n"

        output_path.write_text(content)
        logger.info(f"Session exported to {output_path}")
        return output_path

    # ========================================================================
    # Infrastructure Data Management (Delegated to HostRepository)
    # ========================================================================

    def add_or_update_host(
        self,
        hostname: str,
        ip_address: Optional[str] = None,
        environment: Optional[str] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        status: str = "active",
        ssh_port: int = 22,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add or update a host in the database."""
        return self.host_repo.add_or_update_host(
            hostname, ip_address, environment, role, service, status, ssh_port, metadata
        )

    def get_hosts(
        self,
        environment: Optional[str] = None,
        role: Optional[str] = None,
        service: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query hosts from database."""
        return self.host_repo.get_hosts(environment, role, service, status)

    def add_process(
        self,
        host_id: int,
        process_name: str,
        pid: Optional[int] = None,
        user: Optional[str] = None,
        cpu_percent: Optional[float] = None,
        memory_percent: Optional[float] = None,
        status: Optional[str] = None,
        command_line: Optional[str] = None
    ) -> int:
        """Add process information for a host."""
        return self.host_repo.add_process(
            host_id, process_name, pid, user, cpu_percent, memory_percent, status, command_line
        )

    def get_processes(
        self,
        host_id: Optional[int] = None,
        process_name: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query processes from database."""
        return self.host_repo.get_processes(host_id, process_name, limit)

    def add_inventory_item(
        self,
        host_id: int,
        inventory_type: str,
        key: str,
        value: Optional[str] = None,
        category: Optional[str] = None
    ) -> int:
        """Add inventory item for a host."""
        return self.host_repo.add_inventory_item(host_id, inventory_type, key, value, category)

    def get_inventory(
        self,
        host_id: Optional[int] = None,
        inventory_type: Optional[str] = None,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Query inventory items."""
        return self.host_repo.get_inventory(host_id, inventory_type, category)

    def start_scan(
        self,
        scan_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Record the start of a scan operation."""
        return self.host_repo.start_scan(scan_type, metadata)

    def complete_scan(
        self,
        scan_id: int,
        hosts_scanned: int = 0,
        hosts_discovered: int = 0,
        error_message: Optional[str] = None
    ):
        """Mark a scan as complete."""
        self.host_repo.complete_scan(scan_id, hosts_scanned, hosts_discovered, error_message)

    def get_scans(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent scans."""
        return self.host_repo.get_scans(limit)
