from __future__ import annotations

import json
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
        self.assertIn("resources", response["result"]["capabilities"])
        self.assertIn("prompts", response["result"]["capabilities"])
        self.assertIn("instructions", response["result"])
        self.assertIn("switchyard_checkout", response["result"]["instructions"])
        self.assertIn("switchyard_uncheckout", response["result"]["instructions"])
        self.assertIn("switchyard://project/brief", response["result"]["instructions"])
        self.assertIn("switchyard_runtime_handoff", response["result"]["instructions"])
        self.assertNotIn("Prefer switchyard_brief first", response["result"]["instructions"])

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

    def test_initialize_rejects_non_string_protocol_version(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": 20250618},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("protocolVersion must be a string", response["error"]["message"])

    def test_initialize_rejects_non_object_params(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": []})

        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("params must be an object", response["error"]["message"])

    def test_tools_call_rejects_malformed_envelope(self) -> None:
        cases = [
            ({"params": []}, "params must be an object"),
            ({"params": {"name": 123, "arguments": {}}}, "name must be a string"),
            ({"params": {"name": "switchyard_doctor", "arguments": []}}, "arguments must be an object"),
            ({"params": {"name": "switchyard_doctor", "arguments": False}}, "arguments must be an object"),
        ]

        for payload, expected in cases:
            with self.subTest(expected=expected):
                response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", **payload})

                self.assertEqual(response["error"]["code"], -32602)
                self.assertIn(expected, response["error"]["message"])

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

    def test_resources_list_includes_project_context_and_agent_guide(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})

        resources = {resource["uri"]: resource for resource in response["result"]["resources"]}
        self.assertEqual(resources["switchyard://project/brief"]["mimeType"], "application/json")
        self.assertEqual(resources["switchyard://project/doctor"]["mimeType"], "application/json")
        self.assertEqual(resources["switchyard://agent/guide"]["mimeType"], "text/markdown")

    def test_resources_read_project_context_without_initializing_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            home = Path(temp) / "home"
            root.mkdir()
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[env]
link = [".env.local"]

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(home)}):
                set_server_root(root)
                try:
                    doctor_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "resources/read",
                            "params": {"uri": "switchyard://project/doctor"},
                        }
                    )
                    brief_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 4,
                            "method": "resources/read",
                            "params": {"uri": "switchyard://project/brief"},
                        }
                    )
                    guide_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 5,
                            "method": "resources/read",
                            "params": {"uri": "switchyard://agent/guide"},
                        }
                    )
                finally:
                    set_server_root(None)

        doctor = json.loads(doctor_response["result"]["contents"][0]["text"])
        brief = json.loads(brief_response["result"]["contents"][0]["text"])
        guide = guide_response["result"]["contents"][0]["text"]
        self.assertEqual(doctor["project"], "demo")
        self.assertEqual(doctor["env_warnings"], ["missing link source .env.local"])
        self.assertEqual(brief["project"], "demo")
        self.assertEqual(brief["services"], [])
        self.assertEqual(brief["env_warnings"], ["missing link source .env.local"])
        self.assertIn("switchyard_brief", guide)
        self.assertFalse(home.exists())

    def test_resources_read_rejects_unknown_or_malformed_uri(self) -> None:
        cases = [
            ({}, "uri must be a string"),
            ({"uri": 123}, "uri must be a string"),
            ({"uri": "switchyard://missing"}, "unknown resource"),
        ]

        for params, expected in cases:
            with self.subTest(expected=expected):
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 6,
                        "method": "resources/read",
                        "params": params,
                    }
                )

                self.assertIn("error", response)
                self.assertIn(expected, response["error"]["message"])

    def test_prompts_list_and_get_agent_workflows(self) -> None:
        list_response = handle_request({"jsonrpc": "2.0", "id": 7, "method": "prompts/list"})
        prompts = {prompt["name"]: prompt for prompt in list_response["result"]["prompts"]}

        self.assertIn("switchyard_runtime_handoff", prompts)
        self.assertIn("switchyard_branch_runtime", prompts)
        self.assertEqual(prompts["switchyard_branch_runtime"]["arguments"][0]["name"], "branch")
        self.assertTrue(prompts["switchyard_branch_runtime"]["arguments"][0]["required"])

        handoff_response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "prompts/get",
                "params": {"name": "switchyard_runtime_handoff"},
            }
        )
        branch_response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "prompts/get",
                "params": {
                    "name": "switchyard_branch_runtime",
                    "arguments": {"branch": "feature/demo", "services": "web api"},
                },
            }
        )

        handoff_text = handoff_response["result"]["messages"][0]["content"]["text"]
        branch_text = branch_response["result"]["messages"][0]["content"]["text"]
        self.assertIn("switchyard://project/brief", handoff_text)
        self.assertIn("switchyard_create", handoff_text)
        self.assertIn("feature/demo", branch_text)
        self.assertIn("web api", branch_text)
        self.assertIn("switchyard_up", branch_text)

    def test_prompts_get_rejects_missing_branch_and_bad_arguments(self) -> None:
        cases = [
            ({"name": "switchyard_branch_runtime"}, "branch is required"),
            ({"name": "switchyard_branch_runtime", "arguments": {"branch": 123}}, "arguments must be an object of strings"),
            ({"name": "switchyard_runtime_handoff", "arguments": []}, "arguments must be an object"),
            ({"name": "missing"}, "unknown prompt"),
            ({}, "name must be a string"),
        ]

        for params, expected in cases:
            with self.subTest(expected=expected):
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 10,
                        "method": "prompts/get",
                        "params": params,
                    }
                )

                self.assertIn("error", response)
                self.assertIn(expected, response["error"]["message"])

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

    def test_tools_list_includes_output_schemas(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        for name, tool in tools.items():
            with self.subTest(name=name):
                self.assertIn("outputSchema", tool)
                self.assertEqual(tool["outputSchema"]["type"], "object")
        self.assertIn("services", tools["switchyard_status"]["outputSchema"]["properties"])
        self.assertIn("logs", tools["switchyard_logs"]["outputSchema"]["properties"])

    def test_tools_list_describes_worktree_scoped_branch_defaults(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

        tools = {tool["name"]: tool for tool in response["result"]["tools"]}
        for name in ["switchyard_status", "switchyard_uncheckout", "switchyard_down"]:
            with self.subTest(name=name):
                description = tools[name]["inputSchema"]["properties"]["branch"]["description"]
                self.assertIn("registered worktree branch", description)
                self.assertIn("project root", description)

    def test_doctor_tool_returns_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[env]
link = [".env.local"]

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
        self.assertEqual(result["structuredContent"]["env_warnings"], ["missing link source .env.local"])

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

    def test_status_tool_returns_object_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / ".switchyard-home"
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
                            "id": 4,
                            "method": "tools/call",
                            "params": {"name": "switchyard_status", "arguments": {}},
                        }
                    )
                finally:
                    set_server_root(None)

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"services": []})

    def test_status_tool_scopes_to_registered_worktree_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = workspace / "project"
            worktree = workspace / "feature-demo"
            root.mkdir()
            worktree.mkdir()
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(workspace / "home")}):
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_worktree(config, "feature/demo", worktree)
                for branch, port in [("feature/demo", 41000), ("feature/other", 41001)]:
                    branch_slug = branch.replace("/", "-")
                    registry.upsert_service(
                        config,
                        {
                            "project": config.name,
                            "branch": branch,
                            "service": "web",
                            "pid": 0,
                            "command": "python -m http.server",
                            "port": port,
                            "url": f"http://web.{branch_slug}.demo.localhost:7331",
                            "log_file": str(workspace / f"{branch_slug}.log"),
                        },
                    )
                set_server_root(root)
                try:
                    root_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 15,
                            "method": "tools/call",
                            "params": {"name": "switchyard_status", "arguments": {}},
                        }
                    )
                    worktree_response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 16,
                            "method": "tools/call",
                            "params": {"name": "switchyard_status", "arguments": {"cwd": str(worktree)}},
                        }
                    )
                finally:
                    set_server_root(None)

        self.assertFalse(root_response["result"]["isError"])
        self.assertFalse(worktree_response["result"]["isError"])
        root_branches = {item["branch"] for item in root_response["result"]["structuredContent"]["services"]}
        worktree_services = worktree_response["result"]["structuredContent"]["services"]
        self.assertEqual(root_branches, {"feature/demo", "feature/other"})
        self.assertEqual([item["branch"] for item in worktree_services], ["feature/demo"])

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

    def test_tools_reject_non_string_branch_and_service_arguments(self) -> None:
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
            cases = [
                ("switchyard_status", {"branch": 123}, "branch must be a string"),
                ("switchyard_brief", {"branch": 123}, "branch must be a string"),
                ("switchyard_where", {"service": 123}, "service must be a string"),
                ("switchyard_where", {"service": "web", "branch": 123}, "branch must be a string"),
                ("switchyard_logs", {"service": 123}, "service must be a string"),
                ("switchyard_logs", {"branch": 123}, "branch must be a string"),
                ("switchyard_up", {"branch": 123}, "branch must be a string"),
            ]

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / ".switchyard-home")}):
                set_server_root(root)
                try:
                    responses = [
                        (
                            name,
                            expected,
                            handle_request(
                                {
                                    "jsonrpc": "2.0",
                                    "id": index,
                                    "method": "tools/call",
                                    "params": {"name": name, "arguments": arguments},
                                }
                            ),
                        )
                        for index, (name, arguments, expected) in enumerate(cases, start=20)
                    ]
                finally:
                    set_server_root(None)

        for name, expected, response in responses:
            with self.subTest(name=name, expected=expected):
                result = response["result"]
                self.assertTrue(result["isError"])
                self.assertIn(expected, result["content"][0]["text"])

    def test_tools_reject_unknown_arguments_before_side_effects(self) -> None:
        for name, arguments in [
            ("switchyard_doctor", {"typo": True}),
            ("switchyard_up", {"branch": "feature/demo", "servies": ["web"]}),
        ]:
            with self.subTest(name=name):
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 30,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    }
                )

                result = response["result"]
                self.assertTrue(result["isError"])
                self.assertIn("unexpected argument(s)", result["content"][0]["text"])

    def test_tools_reject_non_string_cwd_before_project_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            set_server_root(root)
            try:
                response = handle_request(
                    {
                        "jsonrpc": "2.0",
                        "id": 31,
                        "method": "tools/call",
                        "params": {"name": "switchyard_doctor", "arguments": {"cwd": 123}},
                    }
                )
            finally:
                set_server_root(None)

        result = response["result"]
        self.assertTrue(result["isError"])
        self.assertIn("cwd must be a string", result["content"][0]["text"])

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
        self.assertIn("cwd must stay under MCP server root or a registered worktree", result["content"][0]["text"])

    def test_tool_cwd_may_use_registered_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = workspace / "project"
            worktree = workspace / "feature-demo"
            root.mkdir()
            git(root, "init")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test User")
            (root / "README.md").write_text("demo\n")
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )
            git(root, "add", "README.md", "switchyard.toml")
            git(root, "commit", "-m", "init")
            git(root, "worktree", "add", "-b", "feature/demo", str(worktree))

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(workspace / "home")}):
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_worktree(config, "feature/demo", worktree)
                set_server_root(root)
                try:
                    response = handle_request(
                        {
                            "jsonrpc": "2.0",
                            "id": 12,
                            "method": "tools/call",
                            "params": {
                                "name": "switchyard_brief",
                                "arguments": {"cwd": str(worktree)},
                            },
                        }
                    )
                finally:
                    set_server_root(None)

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["branch"], "feature/demo")
        self.assertEqual(Path(result["structuredContent"]["project_root"]).resolve(), root.resolve())

    def test_stop_tools_scope_to_registered_worktree_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            root = workspace / "project"
            worktree = workspace / "feature-demo"
            root.mkdir()
            worktree.mkdir()
            (root / "switchyard.toml").write_text(
                """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
            )

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(workspace / "home")}):
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_worktree(config, "feature/demo", worktree)
                set_server_root(root)
                try:
                    with patch("switchyard.mcp.stop_checkouts", return_value=["unchecked web"]) as stop_checkouts:
                        uncheckout_response = handle_request(
                            {
                                "jsonrpc": "2.0",
                                "id": 13,
                                "method": "tools/call",
                                "params": {
                                    "name": "switchyard_uncheckout",
                                    "arguments": {"cwd": str(worktree), "services": ["web"]},
                                },
                            }
                        )
                    with patch("switchyard.mcp.stop_services", return_value=["stopped web"]) as stop_services:
                        down_response = handle_request(
                            {
                                "jsonrpc": "2.0",
                                "id": 14,
                                "method": "tools/call",
                                "params": {
                                    "name": "switchyard_down",
                                    "arguments": {"cwd": str(worktree), "services": ["web"]},
                                },
                            }
                        )
                finally:
                    set_server_root(None)

        uncheckout_result = uncheckout_response["result"]["structuredContent"]
        down_result = down_response["result"]["structuredContent"]
        self.assertEqual(uncheckout_result["branch"], "feature/demo")
        self.assertEqual(uncheckout_result["messages"], ["unchecked web"])
        self.assertEqual(down_result["branch"], "feature/demo")
        self.assertEqual(down_result["messages"], ["stopped web"])
        self.assertEqual(stop_checkouts.call_args.args[2:], ("feature/demo", ["web"]))
        self.assertEqual(stop_services.call_args.args[2:], ("feature/demo", ["web"]))


if __name__ == "__main__":
    unittest.main()
