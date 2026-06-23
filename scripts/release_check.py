from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import tomllib
import venv
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CheckError(RuntimeError):
    pass


def run(args: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise CheckError(
            "command failed: "
            + " ".join(args)
            + "\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )
    return result


def ok(name: str) -> None:
    print(f"OK   {name}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def read(path: str) -> str:
    return (ROOT / path).read_text(errors="replace")


def check_metadata() -> None:
    data = tomllib.loads(read("pyproject.toml"))
    project = data["project"]
    require(project["name"] == "switchyard-dev", "PyPI package name should be switchyard-dev")
    require(project["requires-python"] == ">=3.11", "requires-python should be >=3.11")
    require(project["license"] == "MIT", "license should be MIT")
    scripts = project["scripts"]
    require(scripts["switchyard"] == "switchyard.cli:main", "switchyard console script missing")
    require(scripts["sy"] == "switchyard.cli:main", "sy console script missing")
    require(project["dependencies"] == [], "runtime dependencies should stay empty for now")
    ok("package metadata")


def check_public_docs() -> None:
    readme = read("README.md")
    require("switchyard mcp" in readme, "README should document MCP")
    require("switchyard mcp install" in readme, "README should document one-command MCP setup")
    require("switchyard mcp config" in readme, "README should document copy-paste MCP setup")
    require("Codex's `cwd` field" in readme, "README should document pathless MCP config args")
    require("switchyard_create" in readme and "switchyard_list" in readme, "README should document MCP worktree tools")
    require("switchyard_checkout" in readme and "switchyard_uncheckout" in readme, "README should document MCP checkout tools")
    require("switchyard skill install" in readme, "README should document bundled skill install")
    require("switchyard init [--dry-run] [--json]" in readme, "README should document machine-readable init")
    require("switchyard doctor --json" in readme, "README should document machine-readable doctor")
    require("switchyard list [--json]" in readme, "README should document machine-readable worktree list")
    require("switchyard logs [service] [--branch branch] [--json]" in readme, "README should document machine-readable logs")
    require("tool annotations" in readme, "README should document MCP tool annotations")
    require("switchyard-dev" in readme, "README should document publish package name")
    require("brief --json" in readme, "README should show agent-readable state")
    require('"checkouts"' in readme, "README should show checkout state in brief output")
    require("No public tunnels" in readme, "README should state local-first safety")
    require(
        "Rejects proxy and service hosts outside loopback" in readme,
        "README should document loopback host enforcement",
    )
    require((ROOT / "docs/MCP.md").exists(), "docs/MCP.md missing")
    require((ROOT / "docs/RELEASE.md").exists(), "docs/RELEASE.md missing")
    require((ROOT / "AGENTS.md").exists(), "AGENTS.md missing")
    require((ROOT / ".github/workflows/ci.yml").exists(), "CI workflow missing")
    require((ROOT / ".github/workflows/release.yml").exists(), "release workflow missing")
    ci_workflow = read(".github/workflows/ci.yml")
    require("python-version: ${{ matrix.python-version }}" in ci_workflow, "CI workflow should test Python matrix")
    require("python scripts/release_check.py --skip-package" in ci_workflow, "CI workflow should run release smoke gate")
    require("permissions:\n  contents: read" in ci_workflow, "CI workflow should use read-only permissions")
    release_workflow = read(".github/workflows/release.yml")
    require("switchyard skill show" in release_workflow, "release workflow should smoke bundled skill from wheel")
    require("switchyard doctor --json" in release_workflow, "release workflow should smoke doctor JSON from wheel")
    require("Validate release tag" in release_workflow, "release workflow should validate release tag")
    require("GITHUB_REF_TYPE" in release_workflow, "release workflow should require a tag ref")
    require("CHANGELOG.md must finalize" in release_workflow, "release workflow should require finalized changelog")
    require(
        "python scripts/release_check.py --skip-package" not in release_workflow,
        "release workflow should run package checks",
    )
    for workflow_name, workflow_text in [("CI", ci_workflow), ("release", release_workflow)]:
        for floating_ref in ["@v4", "@v5", "@release/v1"]:
            require(floating_ref not in workflow_text, f"{workflow_name} workflow should pin actions instead of {floating_ref}")
    require(not (ROOT / "docs/COMPETITIVE_RESEARCH.md").exists(), "internal competitive research should not be public")
    for path in ["README.md", "docs/MCP.md", "docs/AGENT_INTERFACE.md", "SECURITY.md"]:
        require("/path/to/project" not in read(path), f"{path} should use generated MCP setup, not path placeholders")
    ok("public docs")


def check_security_docs() -> None:
    security = read("SECURITY.md")
    for needle in [
        "127.0.0.1",
        "Does not expose services publicly",
        "Rejects proxy and service bind hosts",
        "Checks recorded service commands",
        "switchyard.toml",
    ]:
        require(needle in security, f"SECURITY.md missing {needle!r}")
    require("switchyard mcp install" in security, "SECURITY.md should document one-command MCP setup")
    require("switchyard mcp config" in security, "SECURITY.md should document generated MCP setup")
    require("Codex's `cwd` field" in security, "SECURITY.md should document MCP cwd pinning")
    require("read-only/destructive/idempotent hints" in security, "SECURITY.md should document MCP safety hints")
    require("switchyard_create" in security, "SECURITY.md should mention MCP worktree creation")
    require("switchyard_checkout" in security, "SECURITY.md should mention MCP checkout forwarding")
    ok("security docs")


def check_skill() -> None:
    skill = ROOT / "skills/switchyard/SKILL.md"
    agent = ROOT / "skills/switchyard/agents/openai.yaml"
    packaged_skill = ROOT / "src/switchyard/assets/skills/switchyard/SKILL.md"
    packaged_agent = ROOT / "src/switchyard/assets/skills/switchyard/agents/openai.yaml"
    require(skill.exists(), "Switchyard skill missing")
    require(agent.exists(), "Switchyard skill openai.yaml missing")
    require(packaged_skill.exists(), "Packaged Switchyard skill missing")
    require(packaged_agent.exists(), "Packaged Switchyard skill openai.yaml missing")
    require(skill.read_text() == packaged_skill.read_text(), "Repo and packaged skill must match")
    require(agent.read_text() == packaged_agent.read_text(), "Repo and packaged skill agent config must match")
    text = skill.read_text()
    require(text.startswith("---\n"), "skill frontmatter missing")
    require("name: switchyard" in text, "skill name missing")
    require("description:" in text and "Switchyard" in text.split("---", 2)[1], "skill description missing")
    require("switchyard_brief" in text, "skill should teach MCP tool order")
    require("switchyard_create" in text, "skill should teach MCP worktree creation")
    require(
        "switchyard_checkout" in text and "switchyard_uncheckout" in text,
        "skill should teach MCP checkout forwarding",
    )
    require("switchyard mcp install" in text, "skill should teach one-command MCP setup")
    require("switchyard mcp config" in text, "skill should teach generated MCP setup")
    require("Codex's `cwd`" in text, "skill should teach pathless MCP config args")
    require("switchyard init --dry-run --json" in text, "skill should teach first-run setup preview")
    require("switchyard doctor --json" in text, "skill should teach machine-readable doctor")
    require("switchyard list --json" in text, "skill should teach machine-readable worktree list")
    require("switchyard logs web --branch feature/name -n 120 --json" in text, "skill should teach machine-readable logs")
    require("MCP tool annotations" in text, "skill should teach MCP safety annotations")
    require("/path/to/project" not in text, "skill should not ship path placeholders")
    agent_text = agent.read_text()
    require("default_prompt: \"Use $switchyard" in agent_text, "skill default prompt should mention $switchyard")
    ok("agent skill")


def check_no_internal_research() -> None:
    needles = ("just" + "rach", "Competitive" + " Research", "POLISH" + "_HARNESS", "runtime isolation" + " harness")
    for path in ROOT.rglob("*"):
        if path.is_dir() or ".git" in path.parts:
            continue
        if path.suffix in {".pyc", ".log"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for needle in needles:
            require(needle not in text, f"internal-only marker {needle!r} found in {path.relative_to(ROOT)}")
    ok("no internal research artifacts")


def check_mcp_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="switchyard-release-mcp-") as temp:
        root = Path(temp)
        run(["git", "init"], cwd=root)
        run(["git", "config", "user.email", "test@example.com"], cwd=root)
        run(["git", "config", "user.name", "Test User"], cwd=root)
        (root / "README.md").write_text("demo\n")
        run(["git", "add", "README.md"], cwd=root)
        run(["git", "commit", "-m", "init"], cwd=root)
        (root / "switchyard.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "demo"

                [services.web]
                command = "python -m http.server {port}"
                port = 8000
                """
            )
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["SWITCHYARD_HOME"] = str(root / "home")
        readonly_payload = "\n".join(
            [
                '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}',
                '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
                '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"switchyard_doctor","arguments":{}}}',
                '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"switchyard_status","arguments":{}}}',
                "",
            ]
        )
        result = run([sys.executable, "-m", "switchyard", "mcp", "--cwd", str(root)], env=env, input_text=readonly_payload)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(lines[0]["result"]["serverInfo"]["name"] == "switchyard", "MCP initialize failed")
        instructions = lines[0]["result"]["instructions"]
        require("switchyard_checkout" in instructions and "switchyard_uncheckout" in instructions, "MCP instructions incomplete")
        tools = {tool["name"]: tool for tool in lines[1]["result"]["tools"]}
        tool_names = set(tools)
        require(
            {
                "switchyard_brief",
                "switchyard_create",
                "switchyard_list",
                "switchyard_up",
                "switchyard_checkout",
                "switchyard_uncheckout",
            }.issubset(tool_names),
            "MCP tool list incomplete",
        )
        require(all("annotations" in tool for tool in tools.values()), "MCP tools should include safety annotations")
        require(tools["switchyard_brief"]["annotations"]["readOnlyHint"] is True, "switchyard_brief should be read-only")
        require(tools["switchyard_up"]["annotations"]["destructiveHint"] is True, "switchyard_up should be conservative")
        require(tools["switchyard_up"]["annotations"]["openWorldHint"] is True, "switchyard_up should account for configured commands")
        require(tools["switchyard_down"]["annotations"]["destructiveHint"] is True, "switchyard_down should be destructive")
        require(all("outputSchema" in tool for tool in tools.values()), "MCP tools should include output schemas")
        require(
            "services" in tools["switchyard_status"]["outputSchema"]["properties"],
            "switchyard_status should describe services output",
        )
        require(
            "logs" in tools["switchyard_logs"]["outputSchema"]["properties"],
            "switchyard_logs should describe logs output",
        )
        require(lines[2]["result"]["structuredContent"]["project"] == "demo", "MCP doctor failed")
        require(lines[3]["result"]["structuredContent"] == {"services": []}, "MCP status should return services envelope")
        require(not (root / "home").exists(), "read-only MCP doctor should not initialize Switchyard state")

        action_payload = "\n".join(
            [
                '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"switchyard_create","arguments":{"branch":"feature/mcp"}}}',
                '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"switchyard_list","arguments":{}}}',
                "",
            ]
        )
        result = run([sys.executable, "-m", "switchyard", "mcp", "--cwd", str(root)], env=env, input_text=action_payload)
        action_lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(action_lines[0]["result"]["structuredContent"]["created"] is True, "MCP create failed")
        require(action_lines[1]["result"]["structuredContent"]["worktrees"][0]["branch"] == "feature/mcp", "MCP list failed")
    ok("MCP smoke")


def check_cli_json_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="switchyard-release-cli-") as temp:
        root = Path(temp)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["SWITCHYARD_HOME"] = str(root / "home")
        result = run([sys.executable, "-m", "switchyard", "init", "--dry-run", "--json"], cwd=root, env=env)
        init_data = json.loads(result.stdout)
        require(init_data["ok"] is True, "init --dry-run --json should report ok")
        require(init_data["dry_run"] is True and init_data["written"] is False, "init dry run should not write")
        require(init_data["would_fail"] is False, "fresh init dry run should not report a blocker")
        require(init_data["created_config"] is False, "init dry run should not report created config")
        require("[services.web]" in init_data["config_text"], "init dry run should include generated config")
        require(not (root / "switchyard.toml").exists(), "init dry run should not write switchyard.toml")
        require(not (root / ".switchyard").exists(), "init dry run should not create local state")
        (root / "switchyard.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "demo"

                [services.web]
                command = "python -m http.server {port}"
                port = 8000
                """
            )
        )
        result = run([sys.executable, "-m", "switchyard", "doctor", "--json"], cwd=root, env=env)
        data = json.loads(result.stdout)
        require(data["ok"] is True, "doctor --json should report ok")
        require(data["project"]["name"] == "demo", "doctor --json project name mismatch")
        require(data["services"] == ["web"], "doctor --json service list mismatch")
        result = run([sys.executable, "-m", "switchyard", "list", "--json"], cwd=root, env=env)
        data = json.loads(result.stdout)
        require(data == {"worktrees": []}, "list --json should report empty worktrees")
        result = run([sys.executable, "-m", "switchyard", "mcp", "install", "--dry-run"], cwd=root, env=env)
        require("# Would update:" in result.stdout, "mcp install dry run should print target config path")
        require('args = ["mcp"]' in result.stdout, "mcp install dry run should keep server args pathless")
        require(f'cwd = "{root.resolve()}"' in result.stdout, "mcp install dry run should use Codex cwd field")
        require("/path/to/project" not in result.stdout, "mcp install dry run should not use path placeholders")
        result = run([sys.executable, "-m", "switchyard", "mcp", "config"], cwd=root, env=env)
        require('args = ["mcp"]' in result.stdout, "mcp config should keep server args pathless")
        require(f'cwd = "{root.resolve()}"' in result.stdout, "mcp config should use Codex cwd field")
        require("/path/to/project" not in result.stdout, "mcp config should not use path placeholders")
        env["CODEX_HOME"] = str(root / "codex-home")
        run([sys.executable, "-m", "switchyard", "mcp", "install"], cwd=root, env=env)
        config_text = (Path(env["CODEX_HOME"]) / "config.toml").read_text()
        require('args = ["mcp"]' in config_text, "mcp install should write pathless server args")
        require(f'cwd = "{root.resolve()}"' in config_text, "mcp install should write Codex cwd field")
        require("--cwd" not in config_text, "mcp install should not write cwd into server args")
    ok("CLI JSON smoke")


def check_benchmark() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = run([sys.executable, "scripts/benchmark.py", "--runs", "3", "--json"], env=env)
    data = json.loads(result.stdout)
    require(data["runs"] == 3, "benchmark gate should use multiple runs")
    metrics = {item["name"]: item for item in data["metrics"]}
    require(metrics["mcp_initialize_and_doctor"]["median_ms"] < 2500, "MCP smoke benchmark is too slow")
    require(metrics["up_web"]["median_ms"] < 5000, "service startup benchmark is too slow")
    require(metrics["brief_json"]["bytes"] < 12000, "brief output is too large for agent context")
    require(metrics["brief_json"]["has_checkouts"] is True, "brief output should include checkout state")
    require(data["repo_bytes"] < 2_000_000, "repository payload is unexpectedly large")
    require(data["source_bytes"] < 250_000, "source tree is unexpectedly large")
    ok("benchmark thresholds")


def build_and_check_package() -> None:
    with tempfile.TemporaryDirectory(prefix="switchyard-release-package-") as temp:
        root = Path(temp)
        venv_dir = root / "venv"
        dist = root / "dist"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python), "-m", "pip", "install", "--upgrade", "pip", "build", "twine"], cwd=root)
        run([str(python), "-m", "build", "--sdist", "--wheel", "--outdir", str(dist)], cwd=ROOT)
        artifacts = list(dist.iterdir())
        run([str(python), "-m", "twine", "check", *[str(path) for path in artifacts]], cwd=ROOT)
        require(any(path.suffix == ".whl" for path in artifacts), "wheel not built")
        require(any(path.name.endswith(".tar.gz") for path in artifacts), "sdist not built")
        for artifact in artifacts:
            size = artifact.stat().st_size
            limit = 350_000 if artifact.suffix == ".whl" else 600_000
            require(size < limit, f"{artifact.name} is too large: {size} bytes")
        sdist = next(path for path in artifacts if path.name.endswith(".tar.gz"))
        with tarfile.open(sdist) as archive:
            sdist_names = archive.getnames()
        forbidden_sdist_roots = {".github", "tests", "docs", "scripts", "skills"}
        forbidden_sdist_files = {"AGENTS.md"}
        for name in sdist_names:
            relative_parts = Path(name).parts[1:]
            normalized = "/" + "/".join(relative_parts)
            top_level = relative_parts[0] if relative_parts else ""
            require(
                top_level not in forbidden_sdist_roots and top_level not in forbidden_sdist_files,
                f"sdist includes non-runtime file: {normalized}",
            )
        wheel = next(path for path in artifacts if path.suffix == ".whl")
        with zipfile.ZipFile(wheel) as archive:
            wheel_names = archive.namelist()
        require(
            any(name.startswith("switchyard/assets/skills/switchyard/") for name in wheel_names),
            "wheel should include packaged Switchyard skill",
        )
        install_dir = root / "install"
        install_dir.mkdir()
        run([str(python), "-m", "pip", "install", "--target", str(install_dir), str(wheel)], cwd=root)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(install_dir)
        result = run([str(python), "-m", "switchyard", "--version"], cwd=root, env=env)
        require("switchyard 0.1.0" in result.stdout, "installed package version check failed")
        smoke_project = root / "smoke-project"
        smoke_project.mkdir()
        (smoke_project / "switchyard.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "installed-demo"

                [services.web]
                command = "python -m http.server {port}"
                """
            )
        )
        result = run([str(python), "-m", "switchyard", "doctor", "--json"], cwd=smoke_project, env=env)
        require(json.loads(result.stdout)["project"]["name"] == "installed-demo", "installed doctor --json failed")
        result = run([str(python), "-m", "switchyard", "skill", "show"], cwd=root, env=env)
        require("switchyard_brief" in result.stdout, "installed package missing bundled skill")
        skill_target = root / "skills"
        run([str(python), "-m", "switchyard", "skill", "install", "--target", str(skill_target)], cwd=root, env=env)
        require((skill_target / "switchyard" / "SKILL.md").exists(), "installed package could not install skill")
    ok("package build, size, and install")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Switchyard release readiness checks.")
    parser.add_argument("--skip-package", action="store_true", help="Skip networked build/twine package checks.")
    args = parser.parse_args()
    if not shutil.which("git"):
        raise SystemExit("git is required")
    checks = [
        check_metadata,
        check_public_docs,
        check_security_docs,
        check_skill,
        check_no_internal_research,
        lambda: run([sys.executable, "-m", "compileall", "src"]) and ok("compile"),
        lambda: run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], env={**os.environ, "PYTHONPATH": "src"}) and ok("unit tests"),
        lambda: run([sys.executable, "scripts/e2e_smoke.py"]) and ok("e2e smoke"),
        lambda: run([sys.executable, "scripts/concurrency_smoke.py"]) and ok("concurrency smoke"),
        check_mcp_smoke,
        check_cli_json_smoke,
        check_benchmark,
    ]
    if not args.skip_package:
        checks.append(build_and_check_package)
    for check in checks:
        check()
    print("\nRelease readiness passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        raise SystemExit(1)
