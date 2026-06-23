from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from switchyard.mcp import handle_request


class McpTests(unittest.TestCase):
    def test_initialize_returns_tools_capability(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )

        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", response["result"]["capabilities"])
        self.assertIn("instructions", response["result"])

    def test_tools_list_includes_brief_and_up(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("switchyard_brief", names)
        self.assertIn("switchyard_up", names)
        self.assertIn("switchyard_down", names)

    def test_doctor_tool_returns_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / ".switchyard-home")}):
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "switchyard_doctor", "arguments": {"cwd": str(root)}},
                    }
                )

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["project"], "demo")
        self.assertEqual(result["structuredContent"]["services"], ["web"])


if __name__ == "__main__":
    unittest.main()
