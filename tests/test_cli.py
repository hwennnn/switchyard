from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from switchyard.cli import main, mcp_config_text, resolve_mcp_config_root, skill_text


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

    def test_skill_text_is_bundled(self) -> None:
        text = skill_text()

        self.assertIn("name: switchyard", text)
        self.assertIn("switchyard_brief", text)

    def test_skill_install_refuses_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            existing = target / "switchyard"
            existing.mkdir()
            (existing / "SKILL.md").write_text("user copy")

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main(["skill", "install", "--target", str(target)])

            self.assertEqual(code, 1)
            self.assertEqual((existing / "SKILL.md").read_text(), "user copy")

    def test_skill_install_writes_skill_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main(["skill", "install", "--target", str(target)])

            self.assertEqual(code, 0)
            self.assertIn("switchyard_brief", (target / "switchyard" / "SKILL.md").read_text())
            self.assertTrue((target / "switchyard" / "agents" / "openai.yaml").exists())

    def test_skill_install_force_replaces_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            existing = target / "switchyard"
            existing.mkdir()
            (existing / "SKILL.md").write_text("stale copy")

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main(["skill", "install", "--target", str(target), "--force"])

            self.assertEqual(code, 0)
            self.assertIn("switchyard_brief", (existing / "SKILL.md").read_text())

    def test_skill_install_force_keeps_existing_skill_if_copy_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            existing = target / "switchyard"
            existing.mkdir()
            (existing / "SKILL.md").write_text("user copy")

            with patch("switchyard.cli.copy_resource_tree", side_effect=RuntimeError("boom")):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    code = main(["skill", "install", "--target", str(target), "--force"])

            self.assertEqual(code, 1)
            self.assertEqual((existing / "SKILL.md").read_text(), "user copy")


if __name__ == "__main__":
    unittest.main()
