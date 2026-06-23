from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(REPO_ROOT / "src")
CONFIG_NAME = "switchyard.toml"


def fail(message: str) -> None:
    raise SystemExit(message)


def switchyard_root(cwd: Path) -> Path:
    current = cwd.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / CONFIG_NAME).exists():
            return candidate
    fail(f"could not find {CONFIG_NAME} from {cwd}")


def run_switchyard(args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "switchyard", *args],
        cwd=str(cwd),
        env=env,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail(
            f"switchyard {' '.join(args)} failed with exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def rpc_smoke() -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "switchyard-project-smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "switchyard://project/brief"},
        },
    ]
    return "\n".join(json.dumps(message) for message in messages) + "\n"


def smoke(project: Path, nested: str | None, name: str) -> dict[str, object]:
    cwd = (project / nested).resolve() if nested else project.resolve()
    if not cwd.is_dir():
        fail(f"smoke cwd is not a directory: {cwd}")
    root = switchyard_root(cwd)

    with tempfile.TemporaryDirectory(prefix="switchyard-mcp-project-smoke-") as temp:
        temp_path = Path(temp)
        env = os.environ.copy()
        env["PYTHONPATH"] = PYTHONPATH
        env["SWITCHYARD_HOME"] = str((temp_path / "switchyard-home").resolve())
        env["CODEX_HOME"] = str((temp_path / "codex-home").resolve())

        config = json.loads(run_switchyard(["mcp", "config", "--json", "--name", name], cwd, env))
        require(config["ok"] is True, "mcp config --json should succeed")
        require(config["args"][-2:] == ["--project", name], "generated MCP args should use the local alias")
        require("cwd =" not in config["config_text"], "generated MCP config should not use Codex cwd")
        require("--cwd" not in config["config_text"], "generated MCP config should not use --cwd")
        require(str(root) not in config["config_text"], "generated MCP config should not embed the project root")
        require(
            config["env"].get("SWITCHYARD_HOME") == env["SWITCHYARD_HOME"],
            "generated MCP config should preserve SWITCHYARD_HOME",
        )

        projects = json.loads(run_switchyard(["mcp", "projects", "--json"], temp_path, env))
        require(projects["home"] == env["SWITCHYARD_HOME"], "mcp projects should report the Switchyard home")
        require(
            projects["state_path"] == str((Path(env["SWITCHYARD_HOME"]) / "state.json").resolve()),
            "mcp projects should report the state path",
        )
        require(projects["projects"], "mcp projects should list the registered alias")
        alias = projects["projects"][0]
        require(alias["name"] == name, "mcp projects should list the requested alias")
        require(alias["root"] == str(root), "mcp projects should register the detected project root")
        require(alias["config"] == str(root / CONFIG_NAME), "mcp projects should register the exact project config")
        require(alias["status"] == "ok", "mcp projects should report a healthy alias")

        dry_run = json.loads(run_switchyard(["mcp", "install", "--dry-run", "--json", "--name", name], cwd, env))
        require(dry_run["ok"] is True and dry_run["dry_run"] is True, "mcp install dry-run JSON should succeed")
        require(dry_run["registered"] is False, "mcp install dry-run should not claim registration")
        require("cwd =" not in dry_run["config_text"], "dry-run MCP config should not use Codex cwd")
        require(str(root) not in dry_run["config_text"], "dry-run MCP config should not embed the project root")

        install = json.loads(run_switchyard(["mcp", "install", "--json", "--name", name], cwd, env))
        require(install["ok"] is True and install["registered"] is True, "mcp install JSON should succeed")
        codex_config = Path(env["CODEX_HOME"]) / "config.toml"
        config_text = codex_config.read_text()
        require(f'"--project", "{name}"' in config_text, "installed Codex config should use alias args")
        require("cwd =" not in config_text, "installed Codex config should not use Codex cwd")
        require("--cwd" not in config_text, "installed Codex config should not use --cwd")
        require(str(root) not in config_text, "installed Codex config should not embed the project root")

        mcp_output = run_switchyard(["mcp", "--project", name], temp_path, env, rpc_smoke())
        require("switchyard://project/brief" in mcp_output, "MCP server should return the project brief resource")
        require("configured_services" in mcp_output, "project brief should include configured services")

        return {
            "ok": True,
            "project": str(root),
            "cwd": str(cwd),
            "name": name,
            "home": projects["home"],
            "state_path": projects["state_path"],
            "alias": alias,
            "used_python": sys.executable,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke a Switchyard project's path-free MCP setup.")
    parser.add_argument("project", nargs="?", default=".", help="Project checkout or child directory to smoke.")
    parser.add_argument("--nested", help="Optional child directory, relative to the project argument, to run setup from.")
    parser.add_argument("--name", default="switchyard-smoke", help="Temporary MCP alias name.")
    parser.add_argument("--json", action="store_true", help="Print the smoke summary as JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = smoke(Path(args.project).expanduser(), args.nested, args.name)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("OK   MCP project smoke")
        print(f"project: {result['project']}")
        print(f"cwd: {result['cwd']}")
        print(f"alias: {result['name']}")
        print(f"home: {result['home']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
