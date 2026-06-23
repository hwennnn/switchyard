from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import venv
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
    require("switchyard mcp config" in readme, "README should document copy-paste MCP setup")
    require("switchyard-dev" in readme, "README should document publish package name")
    require("brief --json" in readme, "README should show agent-readable state")
    require("No public tunnels" in readme, "README should state local-first safety")
    require((ROOT / "docs/MCP.md").exists(), "docs/MCP.md missing")
    require((ROOT / "docs/RELEASE.md").exists(), "docs/RELEASE.md missing")
    require((ROOT / "AGENTS.md").exists(), "AGENTS.md missing")
    require((ROOT / ".github/workflows/release.yml").exists(), "release workflow missing")
    require(not (ROOT / "docs/COMPETITIVE_RESEARCH.md").exists(), "internal competitive research should not be public")
    for path in ["README.md", "docs/MCP.md", "docs/AGENT_INTERFACE.md"]:
        require("/path/to/project" not in read(path), f"{path} should use generated MCP setup, not path placeholders")
    ok("public docs")


def check_security_docs() -> None:
    security = read("SECURITY.md")
    for needle in ["127.0.0.1", "Does not expose services publicly", "Checks recorded service commands", "switchyard.toml"]:
        require(needle in security, f"SECURITY.md missing {needle!r}")
    ok("security docs")


def check_skill() -> None:
    skill = ROOT / "skills/switchyard/SKILL.md"
    agent = ROOT / "skills/switchyard/agents/openai.yaml"
    require(skill.exists(), "Switchyard skill missing")
    require(agent.exists(), "Switchyard skill openai.yaml missing")
    text = skill.read_text()
    require(text.startswith("---\n"), "skill frontmatter missing")
    require("name: switchyard" in text, "skill name missing")
    require("description:" in text and "Switchyard" in text.split("---", 2)[1], "skill description missing")
    require("switchyard_brief" in text, "skill should teach MCP tool order")
    require("switchyard mcp config" in text, "skill should teach generated MCP setup")
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
        payload = "\n".join(
            [
                '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}',
                '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
                '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"switchyard_doctor","arguments":{}}}',
                "",
            ]
        )
        result = run([sys.executable, "-m", "switchyard", "mcp", "--cwd", str(root)], env=env, input_text=payload)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(lines[0]["result"]["serverInfo"]["name"] == "switchyard", "MCP initialize failed")
        tool_names = {tool["name"] for tool in lines[1]["result"]["tools"]}
        require("switchyard_brief" in tool_names and "switchyard_up" in tool_names, "MCP tool list incomplete")
        require(lines[2]["result"]["structuredContent"]["project"] == "demo", "MCP doctor failed")
    ok("MCP smoke")


def check_benchmark() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = run([sys.executable, "scripts/benchmark.py", "--json"], env=env)
    data = json.loads(result.stdout)
    metrics = {item["name"]: item for item in data["metrics"]}
    require(metrics["mcp_initialize_and_doctor"]["median_ms"] < 2500, "MCP smoke benchmark is too slow")
    require(metrics["up_web"]["median_ms"] < 5000, "service startup benchmark is too slow")
    require(metrics["brief_json"]["bytes"] < 12000, "brief output is too large for agent context")
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
        install_dir = root / "install"
        install_dir.mkdir()
        wheel = next(path for path in artifacts if path.suffix == ".whl")
        run([str(python), "-m", "pip", "install", "--target", str(install_dir), str(wheel)], cwd=root)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(install_dir)
        result = run([str(python), "-m", "switchyard", "--version"], cwd=root, env=env)
        require("switchyard 0.1.0" in result.stdout, "installed package version check failed")
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
