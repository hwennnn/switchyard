from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from switchyard.cli import mcp_config_text, resolve_mcp_config_root


class CliTests(unittest.TestCase):
    def test_mcp_config_text_pins_real_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            text = mcp_config_text("switchyard", root)

        self.assertIn('args = ["mcp", "--cwd", ', text)
        self.assertIn(str(root), text)
        self.assertNotIn("/path/to/project", text)

    def test_mcp_config_root_discovers_project_from_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subdir = root / "app" / "web"
            subdir.mkdir(parents=True)
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
"""
            )

            resolved, found_config = resolve_mcp_config_root(str(subdir))

        self.assertTrue(found_config)
        self.assertEqual(resolved, root)

    def test_mcp_config_name_must_be_toml_safe(self) -> None:
        with self.assertRaises(ValueError):
            mcp_config_text("bad name", Path.cwd())


if __name__ == "__main__":
    unittest.main()
