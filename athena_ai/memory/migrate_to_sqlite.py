"""
Migration utility to convert JSON conversations to SQLite.

Migrates existing JSON-based conversations to the new SQLite-based storage.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from athena_ai.utils.logger import logger


class ConversationMigrator:
    """Migrates conversations from JSON to SQLite."""

    def __init__(self, env: str = "dev"):
        """
        Initialize migrator.

        Args:
            env: Environment name
        """
        self.env = env
        self.base_dir = Path.home() / ".athena" / env
        self.conversations_dir = self.base_dir / "conversations"
        self.db_path = self.base_dir / "sessions.db"

    def migrate_all(self) -> Dict[str, Any]:
        """
        Migrate all JSON conversations to SQLite.

        Returns:
            Migration summary
        """
        if not self.conversations_dir.exists():
            logger.info("No conversations directory found - nothing to migrate")
            return {
                "status": "success",
                "migrated": 0,
                "skipped": 0,
                "errors": []
            }

        summary = {
            "status": "success",
            "migrated": 0,
            "skipped": 0,
            "errors": []
        }

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if conversations table exists
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='conversations'
        """)

        if not cursor.fetchone():
            conn.close()
            logger.error("Conversations table not found - database not initialized")
            summary["status"] = "error"
            summary["errors"].append("Database not initialized")
            return summary

        # Get all existing conversation IDs in database
        cursor.execute("SELECT id FROM conversations")
        existing_ids = {row[0] for row in cursor.fetchall()}

        conn.close()

        # Migrate current.json
        current_file = self.conversations_dir / "current.json"
        if current_file.exists():
            try:
                self._migrate_conversation_file(current_file, is_current=True)
                summary["migrated"] += 1
                logger.info("Migrated current conversation")
            except Exception as e:
                logger.error(f"Failed to migrate current conversation: {e}")
                summary["errors"].append(f"current.json: {str(e)}")

        # Migrate archived conversations
        for conv_file in self.conversations_dir.glob("conv_*.json"):
            try:
                # Load conversation data
                with open(conv_file, 'r') as f:
                    data = json.load(f)

                conv_id = data.get("id")

                # Skip if already exists
                if conv_id in existing_ids:
                    logger.debug(f"Skipping {conv_id} - already exists in database")
                    summary["skipped"] += 1
                    continue

                # Migrate
                self._migrate_conversation_file(conv_file, is_current=False)
                summary["migrated"] += 1
                logger.info(f"Migrated conversation: {conv_id}")

            except Exception as e:
                logger.error(f"Failed to migrate {conv_file.name}: {e}")
                summary["errors"].append(f"{conv_file.name}: {str(e)}")

        # Update summary status
        if summary["errors"]:
            summary["status"] = "partial" if summary["migrated"] > 0 else "error"

        logger.info(
            f"Migration complete: {summary['migrated']} migrated, "
            f"{summary['skipped']} skipped, {len(summary['errors'])} errors"
        )

        return summary

    def _migrate_conversation_file(self, file_path: Path, is_current: bool = False):
        """
        Migrate a single conversation file.

        Args:
            file_path: Path to JSON file
            is_current: Whether this is the current conversation
        """
        with open(file_path, 'r') as f:
            data = json.load(f)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            # Insert conversation
            cursor.execute("""
                INSERT OR REPLACE INTO conversations
                (id, title, created_at, updated_at, token_count, compacted, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data["id"],
                data["title"],
                data["created_at"],
                data["updated_at"],
                data.get("token_count", 0),
                1 if data.get("compacted", False) else 0,
                1 if is_current else 0
            ))

            # Insert messages
            for msg_data in data.get("messages", []):
                cursor.execute("""
                    INSERT INTO messages
                    (conversation_id, role, content, timestamp, tokens)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    data["id"],
                    msg_data["role"],
                    msg_data["content"],
                    msg_data["timestamp"],
                    msg_data.get("tokens", 0)
                ))

            conn.commit()

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def backup_json_conversations(self) -> Path:
        """
        Create a backup of JSON conversations before migration.

        Returns:
            Path to backup directory
        """
        if not self.conversations_dir.exists():
            logger.info("No conversations to backup")
            return None

        backup_dir = self.base_dir / "conversations_backup"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"backup_{timestamp}"
        backup_path.mkdir()

        # Copy all JSON files
        count = 0
        for json_file in self.conversations_dir.glob("*.json"):
            target = backup_path / json_file.name
            target.write_text(json_file.read_text())
            count += 1

        logger.info(f"Backed up {count} conversation files to {backup_path}")
        return backup_path

    def verify_migration(self) -> Dict[str, Any]:
        """
        Verify that migration was successful.

        Returns:
            Verification results
        """
        results = {
            "status": "success",
            "json_count": 0,
            "db_count": 0,
            "current_matches": False,
            "message_counts_match": []
        }

        # Count JSON files
        if self.conversations_dir.exists():
            json_files = list(self.conversations_dir.glob("conv_*.json"))
            results["json_count"] = len(json_files)
            if (self.conversations_dir / "current.json").exists():
                results["json_count"] += 1

        # Count database conversations
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM conversations")
        results["db_count"] = cursor.fetchone()[0]

        # Check current conversation
        cursor.execute("SELECT id FROM conversations WHERE is_current = 1")
        current_db = cursor.fetchone()

        current_json_path = self.conversations_dir / "current.json"
        if current_json_path.exists():
            with open(current_json_path, 'r') as f:
                current_json = json.load(f)
                results["current_matches"] = (
                    current_db and current_db[0] == current_json["id"]
                )

        # Verify message counts
        cursor.execute("""
            SELECT c.id, COUNT(m.id)
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conversation_id
            GROUP BY c.id
        """)

        for conv_id, msg_count in cursor.fetchall():
            results["message_counts_match"].append({
                "conversation_id": conv_id,
                "message_count": msg_count
            })

        conn.close()

        # Overall status
        if results["db_count"] < results["json_count"]:
            results["status"] = "incomplete"
        elif results["db_count"] == 0 and results["json_count"] > 0:
            results["status"] = "failed"

        return results


def migrate_conversations(env: str = "dev", backup: bool = True) -> Dict[str, Any]:
    """
    Convenience function to migrate conversations.

    Args:
        env: Environment name
        backup: Whether to backup JSON files first

    Returns:
        Migration summary
    """
    migrator = ConversationMigrator(env=env)

    # Backup first
    if backup:
        backup_path = migrator.backup_json_conversations()
        if backup_path:
            logger.info(f"Backup created at: {backup_path}")

    # Migrate
    summary = migrator.migrate_all()

    # Verify
    verification = migrator.verify_migration()

    return {
        "migration": summary,
        "verification": verification
    }


if __name__ == "__main__":
    # Run migration
    import sys

    env = sys.argv[1] if len(sys.argv) > 1 else "dev"

    print(f"Migrating conversations for environment: {env}")
    print("=" * 60)

    results = migrate_conversations(env=env, backup=True)

    print("\n📊 Migration Summary:")
    print(f"  Migrated: {results['migration']['migrated']}")
    print(f"  Skipped: {results['migration']['skipped']}")
    print(f"  Errors: {len(results['migration']['errors'])}")

    if results['migration']['errors']:
        print("\n❌ Errors:")
        for error in results['migration']['errors']:
            print(f"  - {error}")

    print("\n✓ Verification:")
    print(f"  JSON files: {results['verification']['json_count']}")
    print(f"  DB conversations: {results['verification']['db_count']}")
    print(f"  Current matches: {results['verification']['current_matches']}")
    print(f"  Status: {results['verification']['status']}")

    print("\n" + "=" * 60)
    print("Migration complete!")
