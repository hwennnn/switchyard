from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from switchyard.config import default_config_text, detect_default_service, load_config


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

    def test_detects_package_json_dev_command_with_dynamic_port(self) -> None:
        cases = [
            (None, "npm run dev -- --port {port}"),
            ("pnpm-lock.yaml", "pnpm run dev -- --port {port}"),
            ("yarn.lock", "yarn run dev --port {port}"),
        ]
        for lockfile, expected in cases:
            with self.subTest(lockfile=lockfile), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / "package.json").write_text('{"scripts":{"dev":"vite"}}')
                if lockfile:
                    (root / lockfile).write_text("")

                command, port = detect_default_service(root)

            self.assertEqual(command, expected)
            self.assertEqual(port, 3000)

    def test_default_config_text_explains_dynamic_port_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "package.json").write_text('{"scripts":{"dev":"vite"}}')

            text = default_config_text(root)

        self.assertIn("Commands should honor PORT/HOST", text)
        self.assertIn('command = "npm run dev -- --port {port}"', text)

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

    def test_loads_profiles_with_services_and_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[services.api]
command = "api --db {postgres_port}"

[services.web]
command = "web --api {api_url}"

[profiles.shared]
services = ["api", "web"]
[profiles.shared.env]
POSTGRES_PORT = "5432"
"""
            )

            config = load_config(config_path)

        self.assertEqual(config.profiles["shared"].services, ["api", "web"])
        self.assertEqual(config.profiles["shared"].env, {"POSTGRES_PORT": "5432"})

    def test_rejects_profiles_with_unknown_services(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "switchyard.toml"
            config_path.write_text(
                """
[services.web]
command = "web"

[profiles.shared]
services = ["api"]
"""
            )

            with self.assertRaisesRegex(ValueError, "unknown service"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
