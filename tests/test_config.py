from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from switchyard.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_services_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[project]
name = "Entropic Clock"

[services.web]
command = "npm run dev -- --port {port}"
port = 3000
"""
            )

            config = load_config(config_path)

            self.assertEqual(config.name, "Entropic Clock")
            self.assertEqual(config.slug, "entropic-clock")
            self.assertEqual(config.proxy.port, 7331)
            self.assertEqual(config.services["web"].port, 3000)

    def test_loads_project_worktree_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[project]
name = "Entropic Clock"
worktree_root = ".worktrees/switchyard"

[services.web]
command = "npm run dev -- --port {port}"
"""
            )

            config = load_config(config_path)

        self.assertEqual(config.worktree_root, ".worktrees/switchyard")

    def test_rejects_invalid_worktree_root(self) -> None:
        cases = [
            ("worktree_root = 123", "worktree_root must be a string"),
            ('worktree_root = ""', "worktree_root must be a non-empty path"),
            ('worktree_root = " nested"', "worktree_root must be a non-empty path"),
        ]
        for setting, message in cases:
            with self.subTest(setting=setting), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config_path = root / "switchyard.toml"
                config_path.write_text(
                    f"""
[project]
name = "Entropic Clock"
{setting}

[services.web]
command = "npm run dev -- --port {{port}}"
"""
                )

                with self.assertRaisesRegex(ValueError, message):
                    load_config(config_path)

    def test_requires_service_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[services.web]
port = 3000
"""
            )

            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_rejects_env_paths_that_escape_project(self) -> None:
        bad_paths = ["../secret", "/tmp/secret", ".", "..", " nested"]
        for bad_path in bad_paths:
            with self.subTest(bad_path=bad_path), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config_path = root / "switchyard.toml"
                config_path.write_text(
                    f"""
[env]
link = ["{bad_path}"]

[services.web]
command = "python -m http.server {{port}}"
port = 8000
"""
                )

                with self.assertRaises(ValueError):
                    load_config(config_path)

    def test_rejects_service_slug_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[services."api/server"]
command = "one"

[services."api-server"]
command = "two"
"""
            )

            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_rejects_non_loopback_proxy_and_service_hosts(self) -> None:
        cases = [
            """
[proxy]
host = "0.0.0.0"

[services.web]
command = "python -m http.server {port}"
""",
            """
[services.web]
host = "192.168.1.5"
command = "python -m http.server {port}"
""",
        ]
        for text in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                config_path = root / "switchyard.toml"
                config_path.write_text(text)

                with self.assertRaisesRegex(ValueError, "loopback host"):
                    load_config(config_path)

    def test_allows_loopback_hosts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[proxy]
host = "::1"

[services.web]
host = "localhost"
command = "python -m http.server {port}"
"""
            )

            config = load_config(config_path)

        self.assertEqual(config.proxy.host, "::1")
        self.assertEqual(config.services["web"].host, "localhost")


if __name__ == "__main__":
    unittest.main()
