from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from switchyard.config import EnvConfig
from switchyard.envsync import sync_env_files


class EnvSyncTests(unittest.TestCase):
    def test_links_and_copies_env_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            worktree = Path(temp) / "worktree"
            root.mkdir()
            worktree.mkdir()
            (root / ".env").write_text("TOKEN=source\n")
            (root / ".env.local").write_text("LOCAL=source\n")

            actions = sync_env_files(root, worktree, EnvConfig(link=[".env"], copy=[".env.local"]))

            self.assertIn("linked .env", actions)
            self.assertIn("copied .env.local", actions)
            self.assertTrue((worktree / ".env").is_symlink())
            self.assertEqual((worktree / ".env.local").read_text(), "LOCAL=source\n")


if __name__ == "__main__":
    unittest.main()

