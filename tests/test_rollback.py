import os
import shutil
import unittest
from pathlib import Path

from merlya.remediation.rollback import RollbackManager


class TestRollbackManager(unittest.TestCase):
    def setUp(self):
        self.env = "test_env"
        self.manager = RollbackManager(self.env)
        self.test_file = Path("test_file.txt")
        with open(self.test_file, "w") as f:
            f.write("original content")

    def tearDown(self):
        if self.test_file.exists():
            os.remove(self.test_file)
        if self.manager.backup_dir.exists():
            shutil.rmtree(self.manager.backup_dir)

    def test_backup_and_restore(self):
        # 1. Create Backup
        details = {"path": str(self.test_file)}
        plan = self.manager.prepare_rollback("local", "edit_file", details)

        self.assertEqual(plan["type"], "restore_file")
        self.assertTrue(Path(plan["source"]).exists())

        # 2. Modify File
        with open(self.test_file, "w") as f:
            f.write("modified content")

        # 3. Restore
        success = self.manager.execute_rollback(plan)
        self.assertTrue(success)

        with open(self.test_file, "r") as f:
            content = f.read()
        self.assertEqual(content, "original content")

if __name__ == '__main__':
    unittest.main()
