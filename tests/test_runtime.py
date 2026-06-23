from __future__ import annotations

import unittest

from switchyard.config import EnvConfig, PortsConfig, ProjectConfig, ProxyConfig, ServiceConfig
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


if __name__ == "__main__":
    unittest.main()

