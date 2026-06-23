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


if __name__ == "__main__":
    unittest.main()

