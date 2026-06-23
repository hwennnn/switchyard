from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from switchyard.config import load_config
from switchyard.mcp import handle_request, set_server_root
from switchyard.registry import Registry


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


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
        self.assertIn("switchyard_checkout", response["result"]["instructions"])
        self.assertIn("switchyard_uncheckout", response["result"]["instructions"])

    def test_initialize_falls_back_to_supported_protocol(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            }
        )

        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")

    def test_tools_list_includes_brief_and_up(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("switchyard_brief", names)
        self.assertIn("switchyard_create", names)
        self.assertIn("switchyard_list", names)
        self.assertIn("switchyard_up", names)
        self.assertIn("switchyard_checkout", names)
        self.assertIn("switchyard_uncheckout", names)
        self.assertIn("switchyard_down", names)

    def test_tools_list_includes_safety_annotations(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        for name in [
            "switchyard_doctor",
            "switchyard_status",
            "switchyard_list",
            "switchyard_brief",
            "switchyard_where",
            "switchyard_logs",
        ]:
            with self.subTest(name=name):
                self.assertTrue(tools[name]["annotations"]["readOnlyHint"])
                self.assertFalse(tools[name]["annotations"]["openWorldHint"])

        self.assertFalse(tools["switchyard_up"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["switchyard_up"]["annotations"]["destructiveHint"])
        self.assertTrue(tools["switchyard_up"]["annotations"]["idempotentHint"])
        self.assertTrue(tools["switchyard_up"]["annotations"]["openWorldHint"])
        self.assertFalse(tools["switchyard_checkout"]["annotations"]["destructiveHint"])
        self.assertTrue(tools["switchyard_checkout"]["annotations"]["idempotentHint"])
        self.assertFalse(tools["switchyard_checkout"]["annotations"]["openWorldHint"])

        self.assertFalse(tools["switchyard_create"]["annotations"]["readOnlyHint"])
        self.assertTrue(tools["switchyard_create"]["annotations"]["destructiveHint"])
        self.assertTrue(tools["switchyard_down"]["annotations"]["destructiveHint"])
        self.assertTrue(tools["switchyard_uncheckout"]["annotations"]["destructiveHint"])

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
                set_server_root(root)
                try:
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {"name": "switchyard_doctor", "arguments": {"cwd": str(root)}},
                        }
                    )
                finally:
                    set_server_root(None)

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["project"], "demo")
        self.assertEqual(result["structuredContent"]["services"], ["web"])

    def test_read_only_tools_do_not_initialize_switchyard_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            home = Path(temp) / "home"
            root.mkdir()
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(home)}):
                set_server_root(root)
                try:
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "tools/call",
                            "params": {"name": "switchyard_doctor", "arguments": {}},
                        }
                    )
                finally:
                    set_server_root(None)

        self.assertFalse(response["result"]["isError"])
        self.assertFalse(home.exists())

    def test_create_tool_creates_worktree_and_list_reports_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git(root, "init")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test User")
            (root / "README.md").write_text("demo\n")
            (root / ".env.local").write_text("secret=local\n")
            git(root, "add", "README.md", ".env.local")
            git(root, "commit", "-m", "init")
            (root / "switchyard.toml").write_text(
                """
[env]
copy = [".env.local"]

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / ".switchyard-home")}):
                set_server_root(root)
                try:
                    create_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 5,
                            "method": "tools/call",
                            "params": {"name": "switchyard_create", "arguments": {"branch": "feature/demo"}},
                        }
                    )
                    list_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 6,
                            "method": "tools/call",
                            "params": {"name": "switchyard_list", "arguments": {}},
                        }
                    )
                    collision_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 7,
                            "method": "tools/call",
                            "params": {"name": "switchyard_create", "arguments": {"branch": "feature-demo"}},
                        }
                    )
                finally:
                    set_server_root(None)

            create_result = create_response["result"]["structuredContent"]
            worktree = Path(create_result["worktree"])
            self.assertTrue(create_result["created"])
            self.assertEqual(create_result["branch"], "feature/demo")
            self.assertEqual((worktree / ".env.local").read_text(), "secret=local\n")
            self.assertEqual(list_response["result"]["structuredContent"]["worktrees"][0]["branch"], "feature/demo")
            self.assertTrue(collision_response["result"]["isError"])
            self.assertIn("branch names collide", collision_response["result"]["content"][0]["text"])

    def test_checkout_tool_maps_and_unmaps_canonical_port(self) -> None:
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
                set_server_root(root)
                try:
                    with patch("switchyard.mcp.start_checkouts", return_value=["checked out web"]) as start:
                        with patch("switchyard.mcp.stop_checkouts", return_value=["unchecked web"]) as stop:
                            checkout_response = handle_request(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 8,
                                    "method": "tools/call",
                                    "params": {
                                        "name": "switchyard_checkout",
                                        "arguments": {"branch": "feature/demo", "services": ["web"]},
                                    },
                                }
                            )
                            uncheckout_response = handle_request(
                                {
                                    "jsonrpc": "2.0",
                                    "id": 9,
                                    "method": "tools/call",
                                    "params": {
                                        "name": "switchyard_uncheckout",
                                        "arguments": {"branch": "feature/demo", "services": ["web"]},
                                    },
                                }
                            )
                finally:
                    set_server_root(None)

        checkout_result = checkout_response["result"]["structuredContent"]
        self.assertEqual(checkout_result["messages"], ["checked out web"])
        self.assertEqual(start.call_args.args[2:], ("feature/demo", ["web"]))
        self.assertEqual(uncheckout_response["result"]["structuredContent"]["messages"], ["unchecked web"])
        self.assertEqual(stop.call_args.args[2:], ("feature/demo", ["web"]))

    def test_logs_tool_returns_line_arrays_and_text_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log_file = root / "web.log"
            log_file.write_text("alpha\nbeta\ngamma\n")
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
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_service(
                    config,
                    {
                        "project": config.name,
                        "branch": "feature/demo",
                        "service": "web",
                        "pid": 123,
                        "command": "python -m http.server",
                        "port": 41000,
                        "url": "http://web.feature-demo.demo.localhost:7331",
                        "log_file": str(log_file),
                    },
                )
                set_server_root(root)
                try:
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 10,
                            "method": "tools/call",
                            "params": {
                                "name": "switchyard_logs",
                                "arguments": {"branch": "feature/demo", "service": "web", "lines": 2},
                            },
                        }
                    )
                finally:
                    set_server_root(None)

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["logs"][0]["lines"], ["beta", "gamma"])
        self.assertIn("beta\ngamma", result["content"][0]["text"])
        self.assertNotIn("b\ne\nt\na", result["content"][0]["text"])

    def test_logs_tool_rejects_non_integer_lines(self) -> None:
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
                set_server_root(root)
                try:
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 11,
                            "method": "tools/call",
                            "params": {
                                "name": "switchyard_logs",
                                "arguments": {"branch": "feature/demo", "service": "web", "lines": "2"},
                            },
                        }
                    )
                finally:
                    set_server_root(None)

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("lines must be an integer", result["content"][0]["text"])

    def test_tool_cwd_must_stay_under_server_root(self) -> None:
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as other:
            allowed_root = Path(allowed)
            other_root = Path(other)
            (allowed_root / "switchyard.toml").write_text(
                """
[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )
            (other_root / "switchyard.toml").write_text(
                """
[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            set_server_root(allowed_root)
            try:
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "switchyard_doctor", "arguments": {"cwd": str(other_root)}},
                    }
                )
            finally:
                set_server_root(None)

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("cwd must stay under MCP server root", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
