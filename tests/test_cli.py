from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from switchyard.cli import install_mcp_config, main, mcp_config_text, resolve_mcp_config_root, skill_text
from switchyard.config import load_config
from switchyard.registry import Registry


@contextmanager
def chdir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class CliTests(unittest.TestCase):
    def write_config(self, root: Path) -> None:
        (root / "switchyard.toml").write_text(
            """
[project]
name = "demo"

[services.web]
command = "python -m http.server {port}"
port = 8000
"""
        )

    def test_init_dry_run_json_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            stdout = StringIO()
            with chdir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["init", "--dry-run", "--json"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(data["ok"])
            self.assertEqual(data["action"], "init")
            self.assertTrue(data["dry_run"])
            self.assertFalse(data["written"])
            self.assertFalse(data["created_config"])
            self.assertFalse(data["overwrote_config"])
            self.assertFalse(data["created_local_state"])
            self.assertFalse(data["would_fail"])
            self.assertEqual(data["root"], str(root))
            self.assertEqual(data["detected_service"]["name"], "web")
            self.assertIn("[services.web]", data["config_text"])
            self.assertFalse((root / "switchyard.toml").exists())
            self.assertFalse((root / ".switchyard").exists())

    def test_init_json_writes_repo_root_from_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            app = root / "packages" / "web"
            app.mkdir(parents=True)
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            stdout = StringIO()
            with chdir(app), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["init", "--json"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertFalse(data["dry_run"])
            self.assertTrue(data["written"])
            self.assertTrue(data["created_config"])
            self.assertFalse(data["overwrote_config"])
            self.assertTrue(data["created_local_state"])
            self.assertEqual(data["root"], str(root))
            self.assertEqual(data["config"], str(root / "switchyard.toml"))
            self.assertTrue((root / "switchyard.toml").exists())
            self.assertTrue((root / ".switchyard" / ".gitignore").exists())

    def test_init_json_existing_config_failure_stays_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "switchyard.toml").write_text("already here\n")

            stdout = StringIO()
            with chdir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["init", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertIn("already exists", data["error"])

    def test_init_dry_run_json_reports_existing_config_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "switchyard.toml").write_text("already here\n")

            stdout = StringIO()
            with chdir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["init", "--dry-run", "--json"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(data["ok"])
            self.assertTrue(data["would_fail"])
            self.assertIn("already exists", data["failure_reason"])
            self.assertFalse(data["would_write_config"])
            self.assertFalse(data["would_create_local_state"])
            self.assertFalse((root / ".switchyard").exists())

    def test_init_force_json_reports_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "switchyard.toml").write_text("already here\n")

            stdout = StringIO()
            with chdir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["init", "--force", "--json"])

            data = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(data["written"])
            self.assertFalse(data["created_config"])
            self.assertTrue(data["overwrote_config"])
            self.assertIn("[services.web]", (root / "switchyard.toml").read_text())

    def test_doctor_json_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.write_config(root)

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["doctor", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertTrue(data["ok"])
        self.assertEqual(data["project"]["name"], "demo")
        self.assertEqual(data["services"], ["web"])
        self.assertEqual(data["proxy"]["url"], "http://127.0.0.1:7331")

    def test_doctor_json_failure_stays_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["doctor", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertIn("switchyard.toml", data["error"])

    def test_mcp_config_text_uses_codex_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()

            text = mcp_config_text("switchyard", root)

        self.assertIn('args = ["mcp"]', text)
        self.assertIn(f'cwd = "{root}"', text)
        self.assertIn(str(root), text)
        self.assertNotIn("/path/to/project", text)

    def test_mcp_config_root_discovers_project_from_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subdir = root / "app" / "web"
            subdir.mkdir(parents=True)
            self.write_config(root)

            resolved, found_config = resolve_mcp_config_root(str(subdir))

        self.assertTrue(found_config)
        self.assertEqual(resolved, root)

    def test_mcp_config_name_must_be_toml_safe(self) -> None:
        with self.assertRaises(ValueError):
            mcp_config_text("bad name", Path.cwd())

    def test_mcp_install_dry_run_detects_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            subdir = root / "app"
            subdir.mkdir()
            self.write_config(root)

            stdout = StringIO()
            with chdir(subdir), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["mcp", "install", "--dry-run", "--name", "switchyard-demo"])

        self.assertEqual(code, 0)
        self.assertIn("# Would update:", stdout.getvalue())
        self.assertIn('args = ["mcp"]', stdout.getvalue())
        self.assertIn(f'cwd = "{root}"', stdout.getvalue())
        self.assertIn(str(root), stdout.getvalue())
        self.assertNotIn("/path/to/project", stdout.getvalue())

    def test_mcp_parent_cwd_applies_to_setup_subcommands(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp).resolve()
            root = workspace / "project"
            other = workspace / "other"
            root.mkdir()
            other.mkdir()
            self.write_config(root)

            install_stdout = StringIO()
            config_stdout = StringIO()
            with chdir(other), redirect_stderr(StringIO()):
                with redirect_stdout(install_stdout):
                    install_code = main(["mcp", "--cwd", str(root), "install", "--dry-run"])
                with redirect_stdout(config_stdout):
                    config_code = main(["mcp", "--cwd", str(root), "config"])

        self.assertEqual(install_code, 0)
        self.assertEqual(config_code, 0)
        self.assertIn(str(root), install_stdout.getvalue())
        self.assertIn('args = ["mcp"]', install_stdout.getvalue())
        self.assertIn(f"# Generated for: {root}", config_stdout.getvalue())
        self.assertNotIn(str(other), install_stdout.getvalue())
        self.assertNotIn(str(other), config_stdout.getvalue())

    def test_mcp_install_writes_codex_config_with_detected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            codex_home = root / "codex-home"
            self.write_config(root)

            stdout = StringIO()
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}):
                with chdir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["mcp", "install", "--name", "switchyard-demo"])
            config_text = (codex_home / "config.toml").read_text()

        self.assertEqual(code, 0)
        self.assertIn("[mcp_servers.switchyard-demo]", config_text)
        self.assertIn('args = ["mcp"]', config_text)
        self.assertIn(f'cwd = "{root}"', config_text)
        self.assertIn("Codex MCP server", stdout.getvalue())

    def test_mcp_install_updates_existing_server_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config_path = root / "config.toml"
            config_path.write_text(
                """
model = "gpt-5.5"

[mcp_servers.switchyard]
command = "old"
args = ["mcp", "--cwd", "/old"]

[mcp_servers.switchyard.tools.switchyard_up]
approval_mode = "approve"

[mcp_servers.other]
command = "other"
"""
            )

            _, action = install_mcp_config("switchyard", root, config_path)
            text = config_path.read_text()

        self.assertEqual(action, "updated")
        self.assertIn('model = "gpt-5.5"', text)
        self.assertIn("[mcp_servers.other]", text)
        self.assertIn('args = ["mcp"]', text)
        self.assertIn(f'cwd = "{root}"', text)
        self.assertNotIn("--cwd", text)
        self.assertNotIn("[mcp_servers.switchyard.tools.switchyard_up]", text)
        self.assertNotIn('approval_mode = "approve"', text)

    def test_list_json_returns_registered_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.write_config(root)
            worktree = root / "worktrees" / "feature-demo"
            worktree.mkdir(parents=True)

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_worktree(config, "feature/demo", worktree)
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["list", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(data["worktrees"][0]["branch"], "feature/demo")
        self.assertEqual(data["worktrees"][0]["path"], str(worktree))

    def test_brief_uses_registered_worktree_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            worktree = root / ".worktrees" / "feature-demo"
            self.write_config(root)
            worktree.mkdir(parents=True)
            (worktree / "switchyard.toml").write_text((root / "switchyard.toml").read_text())

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}):
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_worktree(config, "feature/demo", worktree)
                with chdir(worktree), redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["brief", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(data["branch"], "feature/demo")
        self.assertEqual(Path(data["project_root"]).resolve(), root)
        self.assertEqual(data["changed_files"], [])

    def test_status_uses_registered_worktree_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            worktree = root / ".worktrees" / "feature-demo"
            log_file = root / "web.log"
            log_file.write_text("ok\n")
            self.write_config(root)
            worktree.mkdir(parents=True)
            (worktree / "switchyard.toml").write_text((root / "switchyard.toml").read_text())

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}):
                config = load_config(root / "switchyard.toml")
                registry = Registry()
                registry.ensure_project(config)
                registry.upsert_worktree(config, "feature/demo", worktree)
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
                registry.upsert_service(
                    config,
                    {
                        "project": config.name,
                        "branch": "other/branch",
                        "service": "web",
                        "pid": 456,
                        "command": "python -m http.server",
                        "port": 41001,
                        "url": "http://web.other-branch.demo.localhost:7331",
                        "log_file": str(log_file),
                    },
                )
                with chdir(worktree), redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["status", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual([record["branch"] for record in data], ["feature/demo"])

    def test_runtime_action_commands_can_return_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.write_config(root)

            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
                with patch("switchyard.cli.start_services", return_value=["started web"]) as start:
                    stdout = StringIO()
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        code = main(["up", "--json"])
                    up_data = json.loads(stdout.getvalue())

                with patch("switchyard.cli.stop_services", return_value=["stopped web"]) as stop:
                    stdout = StringIO()
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        code_down = main(["down", "--branch", "feature/demo", "web", "--json"])
                    down_data = json.loads(stdout.getvalue())

                with patch("switchyard.cli.start_checkouts", return_value=["checked out web"]) as checkout:
                    stdout = StringIO()
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        code_checkout = main(["checkout", "feature/demo", "web", "--json"])
                    checkout_data = json.loads(stdout.getvalue())

                with patch("switchyard.cli.stop_checkouts", return_value=["unchecked web"]) as uncheckout:
                    stdout = StringIO()
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        code_uncheckout = main(["uncheckout", "--branch", "feature/demo", "web", "--json"])
                    uncheckout_data = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertTrue(up_data["ok"])
        self.assertEqual(up_data["action"], "up")
        self.assertEqual(up_data["branch"], "current")
        self.assertEqual(up_data["worktree"], str(root))
        self.assertEqual(up_data["services"], [])
        self.assertEqual(up_data["messages"], ["started web"])
        start.assert_called_once()

        self.assertEqual(code_down, 0)
        self.assertEqual(
            down_data,
            {
                "ok": True,
                "action": "down",
                "branch": "feature/demo",
                "scope": "branch",
                "services": ["web"],
                "messages": ["stopped web"],
            },
        )
        self.assertEqual(stop.call_args.args[3], ["web"])

        self.assertEqual(code_checkout, 0)
        self.assertEqual(
            checkout_data,
            {
                "ok": True,
                "action": "checkout",
                "branch": "feature/demo",
                "scope": "branch",
                "services": ["web"],
                "messages": ["checked out web"],
            },
        )
        self.assertEqual(checkout.call_args.args[3], ["web"])

        self.assertEqual(code_uncheckout, 0)
        self.assertEqual(
            uncheckout_data,
            {
                "ok": True,
                "action": "uncheckout",
                "branch": "feature/demo",
                "scope": "branch",
                "services": ["web"],
                "messages": ["unchecked web"],
            },
        )
        self.assertEqual(uncheckout.call_args.args[3], ["web"])

    def test_action_json_failure_stays_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.write_config(root)

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
                with patch("switchyard.cli.stop_services", side_effect=RuntimeError("boom")):
                    with redirect_stdout(stdout), redirect_stderr(StringIO()):
                        code = main(["down", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertEqual(data, {"ok": False, "error": "boom"})

    def test_logs_json_returns_structured_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.write_config(root)
            log_file = root / "web.log"
            log_file.write_text("one\ntwo\nthree\n")

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
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
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["logs", "web", "--branch", "feature/demo", "-n", "2", "--json"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 0)
        self.assertEqual(data["lines"], 2)
        self.assertEqual(data["logs"][0]["service"], "web")
        self.assertEqual(data["logs"][0]["branch"], "feature/demo")
        self.assertEqual(data["logs"][0]["lines"], ["two", "three"])

    def test_logs_json_rejects_follow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            self.write_config(root)

            stdout = StringIO()
            with patch.dict(os.environ, {"SWITCHYARD_HOME": str(root / "home")}), chdir(root):
                with redirect_stdout(stdout), redirect_stderr(StringIO()):
                    code = main(["logs", "--json", "--follow"])

            data = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertFalse(data["ok"])
        self.assertIn("--follow", data["error"])

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
