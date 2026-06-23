from __future__ import annotations

import unittest
import tempfile
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from switchyard.config import EnvConfig, PortsConfig, ProjectConfig, ProxyConfig, ServiceConfig
from switchyard.registry import Registry
from switchyard.runtime import start_services
from switchyard.runtime import brief_for
from switchyard.runtime import stop_checkouts
from switchyard.runtime import stop_services
from switchyard.runtime import service_hostname, service_url
from switchyard.utils import render_command, slugify
from pathlib import Path


class RuntimeTests(unittest.TestCase):
    def test_slugify_is_url_safe(self) -> None:
        self.assertEqual(slugify("Feature/Login Redesign"), "feature-login-redesign")

    def test_render_command_replaces_known_tokens_only(self) -> None:
        command = render_command("dev --port {port} --name {service}", {"port": 3001, "service": "web"})
        self.assertEqual(command, "dev --port 3001 --name web")

    def test_service_url(self) -> None:
        config = ProjectConfig(
            name="Entropic",
            root=Path("/tmp/repo"),
            path=Path("/tmp/repo/switchyard.toml"),
            worktree_root=None,
            env=EnvConfig(),
            proxy=ProxyConfig(port=7331),
            ports=PortsConfig(),
            services={"web": ServiceConfig(name="web", command="dev")},
        )

        self.assertEqual(service_hostname(config, "feature/login", "web"), "web.feature-login.entropic.localhost")
        self.assertEqual(
            service_url(config, "feature/login", "web"),
            "http://web.feature-login.entropic.localhost:7331",
        )

    def test_start_rejects_unknown_services_before_proxy_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            config = ProjectConfig(
                name="Demo",
                root=root,
                path=root / "switchyard.toml",
                worktree_root=None,
                env=EnvConfig(),
                proxy=ProxyConfig(port=7331),
                ports=PortsConfig(),
                services={"web": ServiceConfig(name="web", command="dev", port=3000)},
            )
            registry = Registry(home)

            with patch("switchyard.runtime.ensure_proxy") as ensure_proxy:
                with self.assertRaises(ValueError):
                    start_services(config, registry, "feature/demo", root, ["typo"])

            ensure_proxy.assert_not_called()

    def test_start_expands_peer_service_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            config = ProjectConfig(
                name="Demo",
                root=root,
                path=root / "switchyard.toml",
                worktree_root=None,
                env=EnvConfig(),
                proxy=ProxyConfig(port=7331),
                ports=PortsConfig(start=41000, end=41010),
                services={
                    "db-main": ServiceConfig(name="db-main", command="db --port {port}", port=5432),
                    "api": ServiceConfig(
                        name="api",
                        command="api --port {port} --db {db_main_port} --db-url {db_main_url}",
                        port=8000,
                    ),
                },
            )
            registry = Registry(home)

            with patch("switchyard.runtime.ensure_proxy", return_value="proxy ok"):
                with patch("switchyard.runtime.find_free_port", side_effect=[41000, 41001]):
                    with patch("switchyard.runtime.subprocess.Popen") as popen:
                        popen.side_effect = [SimpleNamespace(pid=1001), SimpleNamespace(pid=1002)]

                        messages = start_services(config, registry, "feature/demo", root)

            api_call = popen.call_args_list[1]
            api_command = api_call.args[0]
            api_env = api_call.kwargs["env"]
            self.assertIn("--db 41000", api_command)
            self.assertIn("--db-url http://db-main.feature-demo.demo.localhost:7331", api_command)
            self.assertEqual(api_env["SWITCHYARD_DB_MAIN_PORT"], "41000")
            self.assertEqual(
                api_env["SWITCHYARD_DB_MAIN_URL"],
                "http://db-main.feature-demo.demo.localhost:7331",
            )
            self.assertIn("started api on :41001 -> http://api.feature-demo.demo.localhost:7331", messages)

    def test_stop_removes_tampered_pid_record_without_killing_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            config = ProjectConfig(
                name="Demo",
                root=root,
                path=root / "switchyard.toml",
                worktree_root=None,
                env=EnvConfig(),
                proxy=ProxyConfig(port=7331),
                ports=PortsConfig(),
                services={"web": ServiceConfig(name="web", command="python app.py", port=3000)},
            )
            registry = Registry(home)
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
            try:
                registry.upsert_service(
                    config,
                    {
                        "project": config.name,
                        "branch": "feature/demo",
                        "service": "web",
                        "pid": process.pid,
                        "command": "definitely-not-this-process",
                        "port": 3000,
                        "url": "http://web.feature-demo.demo.localhost:7331",
                        "log_file": str(root / "web.log"),
                    },
                )

                messages = stop_services(config, registry, "feature/demo", ["web"])

                self.assertIsNone(process.poll())
                self.assertIn("removed stale record", messages[0])
                self.assertIsNone(registry.find_service(config.root, "web", "feature/demo"))
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_stop_checkout_does_not_kill_tampered_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            config = ProjectConfig(
                name="Demo",
                root=root,
                path=root / "switchyard.toml",
                worktree_root=None,
                env=EnvConfig(),
                proxy=ProxyConfig(port=7331),
                ports=PortsConfig(),
                services={"web": ServiceConfig(name="web", command="python app.py", port=3000)},
            )
            registry = Registry(home)
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
            try:
                registry.upsert_checkout(
                    config,
                    {
                        "project": config.name,
                        "branch": "feature/demo",
                        "service": "web",
                        "pid": process.pid,
                        "command": "definitely-not-this-process",
                        "listen_port": 3000,
                        "log_file": str(root / "checkout-web.log"),
                    },
                )

                messages = stop_services(config, registry, "feature/demo", ["web"])

                self.assertIsNone(process.poll())
                self.assertEqual(messages, ["no matching running services"])
                checkout_messages = stop_checkouts(config, registry, "feature/demo", ["web"])
                self.assertIsNone(process.poll())
                self.assertIn("removed stale checkout", checkout_messages[0])
                self.assertIsNone(registry.find_checkout(config.root, "web", "feature/demo"))
            finally:
                process.terminate()
                process.wait(timeout=5)

    def test_brief_includes_canonical_checkouts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            home = Path(temp) / "home"
            root.mkdir()
            config = ProjectConfig(
                name="Demo",
                root=root,
                path=root / "switchyard.toml",
                worktree_root=None,
                env=EnvConfig(),
                proxy=ProxyConfig(port=7331),
                ports=PortsConfig(),
                services={"web": ServiceConfig(name="web", command="python app.py", port=3000)},
            )
            registry = Registry(home)
            process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
            try:
                registry.ensure_project(config)
                registry.upsert_checkout(
                    config,
                    {
                        "project": config.name,
                        "branch": "feature/demo",
                        "service": "web",
                        "pid": process.pid,
                        "command": "definitely-not-this-process",
                        "listen_host": "127.0.0.1",
                        "listen_port": 3000,
                        "target_host": "127.0.0.1",
                        "target_port": 41000,
                        "log_file": str(root / "checkout-web.log"),
                    },
                )

                brief = brief_for(config, registry, "feature/demo", [])

                self.assertEqual(brief["checkouts"][0]["service"], "web")
                self.assertEqual(brief["checkouts"][0]["status"], "stale")
                self.assertEqual(brief["checkouts"][0]["listen_port"], 3000)
                self.assertEqual(brief["checkouts"][0]["target_port"], 41000)
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
