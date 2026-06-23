from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import stat

from switchyard.config import EnvConfig, PortsConfig, ProjectConfig, ProxyConfig, ServiceConfig
from switchyard.registry import Registry
from switchyard.utils import private_append_binary


def project_config(root: Path) -> ProjectConfig:
    return ProjectConfig(
        name="Demo",
        root=root,
        path=root / "switchyard.toml",
        worktree_root=None,
        env=EnvConfig(),
        proxy=ProxyConfig(),
        ports=PortsConfig(),
        services={"web": ServiceConfig(name="web", command="python -m http.server {port}", port=8000)},
    )


class RegistryTests(unittest.TestCase):
    def test_records_worktrees_and_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            root = Path(temp) / "repo"
            root.mkdir()
            registry = Registry(home)
            config = project_config(root)

            registry.ensure_project(config)
            registry.upsert_worktree(config, "feature/login", Path(temp) / "wt")
            registry.upsert_service(
                config,
                {
                    "branch": "feature/login",
                    "service": "web",
                    "hostname": "web.feature-login.demo.localhost",
                    "port": 42123,
                    "pid": 123,
                },
            )

            self.assertEqual(registry.get_worktree(root, "feature-login")["branch"], "feature/login")
            self.assertEqual(registry.find_route("web.feature-login.demo.localhost:7331")["port"], 42123)

    def test_rejects_branch_slug_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            root = Path(temp) / "repo"
            root.mkdir()
            registry = Registry(home)
            config = project_config(root)

            registry.ensure_project(config)
            registry.upsert_worktree(config, "feature/login", Path(temp) / "one")

            with self.assertRaises(ValueError):
                registry.upsert_worktree(config, "feature-login", Path(temp) / "two")

    def test_default_paths_include_project_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            root_one = Path(temp) / "one"
            root_two = Path(temp) / "two"
            root_one.mkdir()
            root_two.mkdir()
            registry = Registry(home)

            one = project_config(root_one)
            two = project_config(root_two)

            self.assertNotEqual(
                registry.default_worktree_path(one, "feature/demo").parent,
                registry.default_worktree_path(two, "feature/demo").parent,
            )

    def test_state_and_log_paths_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            root = Path(temp) / "repo"
            root.mkdir()
            registry = Registry(home)
            config = project_config(root)

            registry.ensure_project(config)
            log_path = registry.log_path(config, "feature/demo", "web")
            with private_append_binary(log_path) as handle:
                handle.write(b"ok\n")

            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((home / "logs").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((home / "worktrees").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((home / "locks").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(registry.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
