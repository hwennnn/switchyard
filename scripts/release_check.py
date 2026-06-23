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
CONFIG_NAME = "switchyard.toml"


class CheckError(RuntimeError):
    pass


def run(
    args: list[str],
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
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


def project_version() -> str:
    namespace: dict[str, str] = {}
    exec(read("src/switchyard/__init__.py"), namespace)
    return namespace["__version__"]


def check_metadata() -> None:
    data = tomllib.loads(read("pyproject.toml"))
    project = data["project"]
    require(project["name"] == "switchyard-dev", "PyPI package name should be switchyard-dev")
    require(project["description"] == "Local HTTP runtimes for parallel AI agent worktrees.", "package description should be launch-specific")
    require(project["requires-python"] == ">=3.11", "requires-python should be >=3.11")
    require(project["license"] == "MIT", "license should be MIT")
    keywords = set(project["keywords"])
    require({"agents", "ai-agents", "mcp", "git-worktree", "localhost"}.issubset(keywords), "package keywords should cover agent/MCP/localhost positioning")
    classifiers = project["classifiers"]
    require("Programming Language :: Python :: 3.13" in classifiers, "classifiers should advertise Python 3.13")
    urls = project["urls"]
    require(urls["Repository"] == "https://github.com/hwennnn/switchyard", "repository URL missing")
    require(urls["Documentation"].endswith("#readme"), "documentation URL should point at README")
    scripts = project["scripts"]
    require(scripts["switchyard"] == "switchyard.cli:main", "switchyard console script missing")
    require(scripts["sy"] == "switchyard.cli:main", "sy console script missing")
    require(project["dependencies"] == [], "runtime dependencies should stay empty for now")
    ok("package metadata")


def check_public_docs() -> None:
    readme = read("README.md")
    require(
        "[![MCP](https://img.shields.io/badge/MCP-stdio-5f43e9)](https://github.com/hwennnn/switchyard/blob/main/docs/MCP.md)" in readme,
        "README MCP badge should use an absolute GitHub URL",
    )
    require(
        "[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/hwennnn/switchyard/blob/main/LICENSE)" in readme,
        "README license badge should use an absolute GitHub URL",
    )
    require(
        "Give each AI agent worktree its own local HTTP runtime" in readme,
        "README headline should focus on the shipped local HTTP runtime",
    )
    require("Run every AI coding task" not in readme, "README headline should not overclaim task coverage")
    require("## Local Trust Model" in readme, "README should put the local trust model near the top")
    for needle in [
        "No telemetry.",
        "No cloud account or hosted control plane.",
        "Binds to loopback by default and rejects non-loopback service/proxy hosts.",
        "Does not expose public tunnels, LAN sharing, ngrok, or Tailscale endpoints.",
        "Treats `switchyard.toml` service commands as executable local project code.",
        "Links or copies only configured env paths, and rejects env paths outside the project/worktree.",
    ]:
        require(needle in readme, f"README local trust model missing {needle!r}")
    require("Switchyard is pre-release. Install from source today:" in readme, "README should be source-first before PyPI publish")
    require("git clone https://github.com/hwennnn/switchyard.git" in readme, "README source install should include clone URL")
    require("The PyPI package name is reserved as `switchyard-dev`" in readme, "README should avoid implying PyPI publish is live")
    require("Once published:" not in readme, "README install section should not lead with unpublished commands")
    require(
        "[examples directory](https://github.com/hwennnn/switchyard/tree/main/examples)" in readme,
        "README examples link should use an absolute GitHub URL",
    )
    require("](docs/MCP.md)" not in readme, "README should not use relative MCP badge links")
    require("](LICENSE)" not in readme, "README should not use relative license badge links")
    require("See `examples/`" not in readme, "README should not use a relative examples link in PyPI-facing copy")
    require("switchyard mcp" in readme, "README should document MCP")
    require("switchyard mcp install" in readme, "README should document one-command MCP setup")
    require("switchyard mcp config" in readme, "README should document copy-paste MCP setup")
    require(
        "switchyard mcp config [--name name] [--force] [--json]" in readme,
        "README command reference should keep MCP config path-free",
    )
    require(
        "switchyard mcp install [--name name] [--dry-run] [--force] [--json]" in readme,
        "README command reference should keep MCP install path-free",
    )
    require("[--cwd other-checkout]" not in readme, "README command reference should not advertise cwd setup")
    require("switchyard mcp config --json" in readme, "README should document machine-readable MCP config setup")
    require("switchyard mcp install --dry-run --json" in readme, "README should document machine-readable MCP install dry run")
    require("[mcp_servers.name.env]" in readme and "SWITCHYARD_HOME" in readme, "README should document MCP setup env preservation")
    require("switchyard mcp projects --json" in readme, "README should document MCP alias inspection")
    require("`home` and `state_path`" in readme, "README should document MCP alias registry metadata")
    require("unless you pass\n`--force`" in readme, "README should document MCP alias collision safety")
    require('args = ["mcp", "--project", "name"]' in readme, "README should document alias-based MCP config args")
    require('args = ["-m", "switchyard", "mcp", "--project", "name"]' in readme, "README should document Python MCP launch fallback")
    require("current" in readme and "Python" in readme and "interpreter" in readme, "README should explain the MCP launch fallback")
    require("nearest `switchyard.toml`" in readme, "README should document pathless MCP launch")
    require(
        "Switchyard-registered worktree" in readme and "parent\nproject as the server boundary" in readme,
        "README should document MCP startup from registered worktrees",
    )
    require(
        "does not" in readme and "emit `cwd`, `--cwd`, or an absolute project path" in readme,
        "README should explicitly reject path-based MCP client setup",
    )
    require("switchyard_create" in readme and "switchyard_list" in readme, "README should document MCP worktree tools")
    require("switchyard_checkout" in readme and "switchyard_uncheckout" in readme, "README should document MCP checkout tools")
    require("switchyard skill install" in readme, "README should document bundled skill install")
    require("switchyard init [--dry-run] [--json]" in readme, "README should document machine-readable init")
    require("switchyard doctor --json" in readme, "README should document machine-readable doctor")
    require("env_warnings" in readme, "README should document doctor env warnings")
    require("switchyard list [--json]" in readme, "README should document machine-readable worktree list")
    require("switchyard logs [service] [--branch branch] [--json]" in readme, "README should document machine-readable logs")
    require("tool annotations" in readme, "README should document MCP tool annotations")
    require("MCP clients that prefer resources" in readme, "README should document MCP resources")
    require("switchyard://project/brief" in readme, "README should document project brief resource")
    require("switchyard://project/doctor" in readme, "README should document project doctor resource")
    require("switchyard://agent/guide" in readme, "README should document agent guide resource")
    require("These MCP resources do not initialize Switchyard state" in readme, "README should document read-only resource state behavior")
    require("MCP clients that expose prompts" in readme, "README should document MCP prompts")
    require("switchyard_runtime_handoff" in readme, "README should document runtime handoff prompt")
    require("switchyard_branch_runtime" in readme, "README should document branch runtime prompt")
    require("Agents should usually read `switchyard://project/brief` first" in readme, "README should teach resource-first MCP flow")
    require("Agents should usually call `switchyard_brief` first" not in readme, "README should not teach tool-first MCP flow")
    require("## Status" in readme, "README should include current project status")
    require("Stdio MCP tools, resources, and prompts" in readme, "README status should mention shipped MCP resources and prompts")
    require("MCP initialize + doctor" in readme, "README should document benchmark guardrails")
    require("The full release gate also builds and install-smokes the wheel" in readme, "README should separate package gate from benchmark table")
    require("wheel artifact under 350 KB" in readme, "README should document wheel size gate")
    require("From a repository checkout:" in readme, "README should qualify repo-only release scripts")
    require("python3 scripts/benchmark.py --runs 3" in readme, "README should document benchmark reproduction")
    require("python3 scripts/release_check.py" in readme, "README should document release readiness reproduction")
    require("python3 scripts/mcp_project_smoke.py ." in readme, "README should document reusable MCP project smoke harness")
    require("switchyard-dev" in readme, "README should document publish package name")
    require("brief --json" in readme, "README should show agent-readable state")
    require("`configured_services`" in readme, "README should document configured services in brief output")
    require(
        "`brief --json` and `switchyard://project/brief` include" in readme,
        "README should document configured services in brief/resource output",
    )
    require("They also include `env_warnings`" in readme, "README should document brief env warnings")
    require('command = "npm run dev -- --port {port}"' in readme, "README should show explicit dynamic port command")
    require("Service commands should either honor `PORT`/`HOST`" in readme, "README should document service port contract")
    require("Does not replace existing env targets by default" in readme, "README should document env replacement default")
    require("registered worktree" in readme, "README should document registered worktree context")
    require('worktree_root = ".worktrees/switchyard"' in readme, "README should document optional worktree_root")
    require('"configured_services"' in readme, "README should show configured service names in brief output")
    require('"checkouts"' in readme, "README should show checkout state in brief output")
    require('"env_warnings"' in readme, "README should show env warnings in brief output")
    require("No public tunnels" in readme, "README should state local-first safety")
    require(
        "Rejects proxy and service hosts outside loopback" in readme,
        "README should document loopback host enforcement",
    )
    require("Scopes stop actions to the current registered worktree branch" in readme, "README should document scoped stop safety")
    require((ROOT / "docs/MCP.md").exists(), "docs/MCP.md missing")
    require((ROOT / "docs/RELEASE.md").exists(), "docs/RELEASE.md missing")
    require((ROOT / "AGENTS.md").exists(), "AGENTS.md missing")
    require((ROOT / "scripts/mcp_project_smoke.py").exists(), "MCP project smoke harness missing")
    architecture = read("docs/ARCHITECTURE.md")
    mcp_doc = read("docs/MCP.md")
    agent_interface = read("docs/AGENT_INTERFACE.md")
    release_doc = read("docs/RELEASE.md")
    changelog = read("CHANGELOG.md")
    contributing = read("CONTRIBUTING.md")
    agents = read("AGENTS.md")
    require("will be published on PyPI as `switchyard-dev`" in release_doc, "release docs should not imply unpublished PyPI package is live")
    require("Switchyard is packaged on PyPI" not in release_doc, "release docs should avoid live PyPI wording before publish")
    require("MCP resources expose project brief" in changelog, "CHANGELOG should mention MCP resources")
    require("MCP prompts expose read-only" in changelog, "CHANGELOG should mention MCP prompts")
    require("Compact `brief` output lists configured service names" in changelog, "CHANGELOG should mention configured services in brief")
    require("Compact `brief` output reports missing configured env sources" in changelog, "CHANGELOG should mention brief env warnings")
    require(
        "MCP help hides the `--cwd` compatibility escape hatch" in changelog,
        "CHANGELOG should mention path-free MCP setup help",
    )
    require(
        "MCP help shows setup subcommands as optional" in changelog,
        "CHANGELOG should mention optional MCP setup subcommands in help",
    )
    require("MCP setup chooses a launchable server command" in changelog, "CHANGELOG should mention generated MCP launch command behavior")
    require("MCP setup commands expose machine-readable JSON" in changelog, "CHANGELOG should mention MCP setup JSON")
    require("MCP setup JSON returns `ok: false`" in changelog, "CHANGELOG should mention MCP setup JSON errors")
    require("MCP aliases require an exact registered" in changelog, "CHANGELOG should mention exact MCP alias pinning")
    require("MCP tool calls stay pinned to the server project" in changelog, "CHANGELOG should mention nested MCP config boundary")
    require("MCP setup preserves explicit `SWITCHYARD_HOME`" in changelog, "CHANGELOG should mention MCP env preservation")
    require("MCP alias inspection JSON reports the local registry `home` and `state_path`" in changelog, "CHANGELOG should mention MCP alias registry metadata")
    require("Agent docs clarify explicit env replacement safety with `--force-env`" in changelog, "CHANGELOG should mention env safety docs")
    require("Internal proxy/forward serve commands reject non-loopback hosts" in changelog, "CHANGELOG should mention internal serve host validation")
    require("Generated JS first-run configs pass `{port}`" in changelog, "CHANGELOG should mention port-aware JS init defaults")
    require(
        "MCP startup from registered worktrees now uses the parent project" in changelog,
        "CHANGELOG should mention MCP registered-worktree startup",
    )
    require("switchyard://project/brief" in agents, "AGENTS.md should teach MCP resource-first workflow")
    require("switchyard_runtime_handoff" in agents, "AGENTS.md should teach MCP runtime handoff prompt")
    require("switchyard_branch_runtime" in agents, "AGENTS.md should teach MCP branch runtime prompt")
    require("switchyard mcp install" in agents, "AGENTS.md should teach one-command MCP setup")
    require("switchyard mcp config --json" in agents, "AGENTS.md should teach machine-readable MCP setup")
    require("switchyard mcp install --dry-run --json" in agents, "AGENTS.md should teach dry-run MCP setup JSON")
    require('args = ["mcp", "--project", "name"]' in agents, "AGENTS.md should teach alias-based MCP config")
    require("[mcp_servers.name.env]" in agents and "SWITCHYARD_HOME" in agents, "AGENTS.md should teach MCP setup env preservation")
    require("`home`/`state_path`" in agents, "AGENTS.md should teach MCP alias registry metadata")
    require("placeholder project paths" in agents and "Do not hand-write" in agents, "AGENTS.md should reject path placeholder setup")
    require("Do not replace existing env targets unless" in agents, "AGENTS.md should teach env replacement safety")
    require("Do not edit tracked `.env` files." not in agents, "AGENTS.md should not forbid explicit env replacement")
    for doc_name, doc_text in [("docs/MCP.md", mcp_doc), ("docs/AGENT_INTERFACE.md", agent_interface)]:
        require("switchyard://project/brief" in doc_text, f"{doc_name} should document MCP project brief resource")
        require("switchyard://project/doctor" in doc_text, f"{doc_name} should document MCP project doctor resource")
        require("switchyard://agent/guide" in doc_text, f"{doc_name} should document MCP agent guide resource")
        require("configured_services" in doc_text, f"{doc_name} should document configured services in brief")
        require("env_warnings" in doc_text, f"{doc_name} should document brief env warnings")
        require("registered worktree" in doc_text and "parent project" in doc_text, f"{doc_name} should document MCP worktree startup")
        require("switchyard mcp config --json" in doc_text, f"{doc_name} should document machine-readable MCP config setup")
        require("`home`" in doc_text and "`state_path`" in doc_text, f"{doc_name} should document MCP alias registry metadata")
        require("setup error" in doc_text or "setup errors" in doc_text, f"{doc_name} should document MCP setup JSON errors")
        require("[mcp_servers.name.env]" in doc_text and "SWITCHYARD_HOME" in doc_text, f"{doc_name} should document MCP setup env preservation")
        require("current" in doc_text and "Python" in doc_text and "interpreter" in doc_text, f"{doc_name} should document Python MCP launch fallback")
        require("absolute project path" in doc_text and "`--cwd`" in doc_text, f"{doc_name} should reject path-based MCP setup")
        require("does not initialize Switchyard state" in doc_text, f"{doc_name} should document read-only MCP resources")
        require("switchyard_runtime_handoff" in doc_text, f"{doc_name} should document MCP runtime handoff prompt")
        require("switchyard_branch_runtime" in doc_text, f"{doc_name} should document MCP branch runtime prompt")
        require("read-only templates" in doc_text, f"{doc_name} should document MCP prompts as read-only")
        require("switchyard://project/brief" in doc_text.split("switchyard_where", 1)[0], f"{doc_name} should teach resource-first flow before service lookup")
    require("Call `switchyard_brief` for compact state" not in mcp_doc, "docs/MCP.md should not teach tool-first flow")
    require("Use `switchyard_brief` before reading logs" not in agent_interface, "docs/AGENT_INTERFACE.md should not teach tool-first flow")
    require((ROOT / "tests/fixtures/mcp_readonly_smoke.jsonl").exists(), "MCP read-only compatibility fixture missing")
    require((ROOT / "tests/fixtures/mcp_action_smoke.jsonl").exists(), "MCP action compatibility fixture missing")
    require("tests/fixtures/mcp_*.jsonl" in contributing, "CONTRIBUTING should point MCP work at compatibility fixtures")
    require("python3 scripts/release_check.py --skip-package" in contributing, "CONTRIBUTING should document normal PR release gate")
    require("python3 scripts/release_check.py" in contributing, "CONTRIBUTING should document full release gate")
    require("tests/fixtures/mcp_*.jsonl" in architecture, "architecture docs should point at MCP compatibility fixtures")
    require("MCP Compatibility" in architecture, "architecture should document MCP compatibility fixtures")
    require("MCP server wrapper" not in architecture + contributing, "public roadmap should not imply MCP server is missing")
    require("python3 scripts/release_check.py --skip-package" in agents, "AGENTS.md should point agents at release smoke gate")
    require((ROOT / ".github/workflows/ci.yml").exists(), "CI workflow missing")
    require((ROOT / ".github/workflows/release.yml").exists(), "release workflow missing")
    ci_workflow = read(".github/workflows/ci.yml")
    require("python-version: ${{ matrix.python-version }}" in ci_workflow, "CI workflow should test Python matrix")
    require("python scripts/release_check.py --skip-package" in ci_workflow, "CI workflow should run release smoke gate")
    require("permissions:\n  contents: read" in ci_workflow, "CI workflow should use read-only permissions")
    release_workflow = read(".github/workflows/release.yml")
    require("switchyard skill show" in release_workflow, "release workflow should smoke bundled skill from wheel")
    require("switchyard doctor --json" in release_workflow, "release workflow should smoke doctor JSON from wheel")
    require("switchyard mcp config" in release_workflow, "release workflow should smoke MCP config from wheel")
    require("switchyard mcp config --json" in release_workflow, "release workflow should smoke MCP config JSON from wheel")
    require("mcp-config.json" in release_workflow, "release workflow should validate MCP config JSON output")
    require("switchyard mcp projects --json" in release_workflow, "release workflow should smoke MCP project aliases from wheel")
    require('"status": "ok"' in release_workflow, "release workflow should require healthy MCP alias status")
    require("switchyard mcp install --dry-run" in release_workflow, "release workflow should smoke MCP install dry run")
    require("switchyard mcp install --dry-run --json" in release_workflow, "release workflow should smoke MCP install dry-run JSON")
    require("mcp-install-dry-run.json" in release_workflow, "release workflow should validate MCP install dry-run JSON output")
    require("switchyard mcp install --json >" in release_workflow, "release workflow should smoke real MCP install JSON")
    require("mcp-install.json" in release_workflow, "release workflow should validate real MCP install JSON output")
    require('"config.toml"' in release_workflow, "release workflow should verify written Codex MCP config")
    require('SMOKE_PROJECT="$smoke_project" python' in release_workflow, "release workflow should pass smoke project to JSON validators")
    require("resources/read" in release_workflow, "release workflow should smoke MCP resources from wheel")
    require("prompts/get" in release_workflow, "release workflow should smoke MCP prompts from wheel")
    require("switchyard://project/brief" in release_workflow, "release workflow should smoke project brief resource")
    require("switchyard_branch_runtime" in release_workflow, "release workflow should smoke branch runtime prompt")
    require("testpypi_smoke_confirmed" in release_workflow, "release workflow should gate PyPI promotion on TestPyPI confirmation")
    require("TestPyPI install smoke" in release_workflow, "release workflow should install-smoke TestPyPI publish")
    require('switchyard mcp --help | grep -F "[config|install|projects]"' in release_workflow, "release workflow should smoke optional MCP help usage")
    require('switchyard mcp --help | grep -F "commands:"' in release_workflow, "release workflow should smoke MCP help command section")
    require('! switchyard mcp --help | grep -F "positional arguments:"' in release_workflow, "release workflow should reject required-looking MCP help")
    require('! switchyard mcp --help | grep -F -- "--cwd"' in release_workflow, "release workflow should reject cwd in MCP help")
    require('switchyard mcp config --help | grep -F "usage: switchyard mcp config"' in release_workflow, "release workflow should smoke clean MCP config help")
    require('! switchyard mcp config --help | grep -F "[config|install|projects]"' in release_workflow, "release workflow should reject parent usage in MCP config help")
    require('! switchyard mcp config --help | grep -F -- "--cwd"' in release_workflow, "release workflow should reject cwd in MCP config help")
    require('switchyard mcp install --help | grep -F "usage: switchyard mcp install"' in release_workflow, "release workflow should smoke clean MCP install help")
    require('! switchyard mcp install --help | grep -F "[config|install|projects]"' in release_workflow, "release workflow should reject parent usage in MCP install help")
    require('! switchyard mcp install --help | grep -F -- "--cwd"' in release_workflow, "release workflow should reject cwd in MCP install help")
    require('smoke_project="$smoke_root/project"' in release_workflow, "release workflow should keep smoke project separate from state")
    require('export SWITCHYARD_HOME="$smoke_root/switchyard-home"' in release_workflow, "release workflow should isolate Switchyard state")
    require('export CODEX_HOME="$smoke_root/codex-home"' in release_workflow, "release workflow should isolate Codex config")
    require('args = ["mcp", "--project", "switchyard"]' in release_workflow, "release workflow should smoke alias MCP config")
    require('data["env"]["SWITCHYARD_HOME"]' in release_workflow, "release workflow should verify generated MCP SWITCHYARD_HOME env")
    require("[mcp_servers.switchyard.env]" in release_workflow, "release workflow should verify generated MCP env table")
    require('cwd = "$smoke_project"' not in release_workflow, "release workflow should not expect Codex cwd MCP config")
    require('export SWITCHYARD_HOME="$tmp/switchyard-home"' in release_doc, "release docs should isolate Switchyard state")
    require('export CODEX_HOME="$tmp/codex-home"' in release_doc, "release docs should isolate Codex config")
    require('args = ["mcp", "--project", "switchyard"]' in release_doc, "release docs should smoke alias MCP config")
    require("switchyard mcp config --json" in release_doc, "release docs should smoke MCP config JSON")
    require("switchyard mcp install --dry-run --json" in release_doc, "release docs should smoke MCP install dry-run JSON")
    require("switchyard mcp install --json >" in release_doc, "release docs should smoke real MCP install JSON")
    require("mcp-install.json" in release_doc, "release docs should validate real MCP install JSON output")
    require('data["env"]["SWITCHYARD_HOME"]' in release_doc, "release docs should validate generated MCP SWITCHYARD_HOME env")
    require("[mcp_servers.switchyard.env]" in release_doc, "release docs should validate generated MCP env table")
    require('PROJECT="$project" TMP="$tmp" python3' in release_doc, "release docs should pass temp paths to JSON validators")
    require("switchyard mcp projects --json" in release_doc, "release docs should smoke MCP project aliases")
    require('"status": "ok"' in release_doc, "release docs should require healthy MCP alias status")
    require("switchyard mcp --project switchyard" in release_doc, "release docs should smoke alias MCP startup")
    require("resources/read" in release_doc, "release docs should smoke MCP resources")
    require("prompts/get" in release_doc, "release docs should smoke MCP prompts")
    require("switchyard://project/brief" in release_doc, "release docs should smoke project brief resource")
    require("switchyard_branch_runtime" in release_doc, "release docs should smoke branch runtime prompt")
    require("testpypi_smoke_confirmed" in release_doc, "release docs should document PyPI promotion confirmation")
    require("cwd =" in release_doc, "release docs should explicitly reject cwd MCP config")
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
    for path in ["README.md", "docs/MCP.md", "docs/AGENT_INTERFACE.md", "docs/RELEASE.md", "SECURITY.md"]:
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
    require("local project alias" in security, "SECURITY.md should document MCP alias pinning")
    require("current" in security and "Python" in security and "interpreter" in security, "SECURITY.md should document MCP launch fallback")
    require("nearest" in security and "`switchyard.toml`" in security, "SECURITY.md should document pathless MCP launch")
    require("registered worktree" in security and "parent\nproject as its boundary" in security, "SECURITY.md should document MCP worktree startup boundary")
    require(
        "hard-coded path arguments, `cwd`, or `--cwd`" in security,
        "SECURITY.md should reject path-based MCP client setup",
    )
    require("[mcp_servers.name.env]" in security and "SWITCHYARD_HOME" in security, "SECURITY.md should document MCP setup env preservation")
    require("read-only/destructive/idempotent hints" in security, "SECURITY.md should document MCP safety hints")
    require("switchyard://project/brief" in security, "SECURITY.md should document read-only MCP resources")
    require("do not initialize Switchyard state" in security, "SECURITY.md should document MCP resource state behavior")
    require("switchyard_runtime_handoff" in security, "SECURITY.md should document read-only MCP prompts")
    require("read-only templates" in security, "SECURITY.md should document MCP prompt safety behavior")
    require("switchyard_create" in security, "SECURITY.md should mention MCP worktree creation")
    require("switchyard_checkout" in security, "SECURITY.md should mention MCP checkout forwarding")
    require("worktree_root` must be a non-empty string path" in security, "SECURITY.md should document worktree_root validation")
    require("Service commands inherit the environment" in security, "SECURITY.md should document inherited service environment")
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
    require("switchyard mcp config --json" in text, "skill should teach machine-readable MCP config setup")
    require("switchyard mcp install --dry-run --json" in text, "skill should teach machine-readable MCP install dry run")
    require("[mcp_servers.name.env]" in text and "SWITCHYARD_HOME" in text, "skill should teach MCP setup env preservation")
    require("setup errors" in text, "skill should teach machine-readable MCP setup errors")
    require("switchyard mcp projects --json" in text, "skill should teach MCP alias inspection")
    require("`home`/`state_path`" in text, "skill should teach MCP alias registry metadata")
    require("use `--force` only when intentionally" in text, "skill should teach cautious MCP alias replacement")
    require("Do not replace existing env targets unless" in text, "skill should teach env replacement safety")
    require("Do not edit tracked `.env` files." not in text, "skill should not forbid explicit env replacement")
    require("local project alias" in text, "skill should teach alias-based MCP config args")
    require("current" in text and "Python" in text and "interpreter" in text, "skill should teach Python MCP launch fallback")
    require("nearest `switchyard.toml`" in text, "skill should teach pathless MCP launch")
    require("registered worktree" in text and "parent project as the server boundary" in text, "skill should teach MCP worktree startup")
    require(
        "Generated MCP client" in text and "config should not contain" in text and "`--cwd`" in text and "absolute project path" in text,
        "skill should reject path-based MCP client setup",
    )
    require("switchyard init --dry-run --json" in text, "skill should teach first-run setup preview")
    require("switchyard doctor --json" in text, "skill should teach machine-readable doctor")
    require("env_warnings" in text, "skill should teach doctor env warnings")
    require("configured_services" in text, "skill should teach configured services in brief")
    require("switchyard brief --json" in text, "skill should teach brief env warnings")
    require("switchyard list --json" in text, "skill should teach machine-readable worktree list")
    require("switchyard logs web --branch feature/name -n 120 --json" in text, "skill should teach machine-readable logs")
    require("MCP tool annotations" in text, "skill should teach MCP safety annotations")
    require("switchyard://project/brief" in text, "skill should teach MCP resource brief")
    require("switchyard://project/doctor" in text, "skill should teach MCP resource doctor")
    require("switchyard://agent/guide" in text, "skill should teach MCP resource guide")
    require("switchyard_runtime_handoff" in text, "skill should teach MCP runtime handoff prompt")
    require("switchyard_branch_runtime" in text, "skill should teach MCP branch runtime prompt")
    require("/path/to/project" not in text, "skill should not ship path placeholders")
    agent_text = agent.read_text()
    require("default_prompt: \"Use $switchyard" in agent_text, "skill default prompt should mention $switchyard")
    ok("agent skill")


def check_examples() -> None:
    examples = sorted((ROOT / "examples").glob("*.toml"))
    require(examples, "example configs missing")
    require('command = "npm run dev -- --port {port}"' in read("examples/switchyard.toml"), "basic example should show explicit dynamic port command")
    code = """
from pathlib import Path
from switchyard.config import load_config

for path in sorted(Path("examples").glob("*.toml")):
    config = load_config(path)
    if not config.services:
        raise SystemExit(f"{path} has no services")
    print(path)
"""
    result = run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    for example in examples:
        require(str(example.relative_to(ROOT)) in result.stdout, f"example config not validated: {example.name}")
    ok("example configs")


def check_no_internal_research() -> None:
    needles = ("just" + "rach", "Competitive" + " Research", "POLISH" + "_HARNESS", "runtime isolation" + " harness")
    forbidden_parts = {"scratch", "research", "harness", "outputs", "work"}
    forbidden_docs = {"competitive_research", "competitive-research"}
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        relative_parts = path.relative_to(ROOT).parts
        normalized = path.name.lower()
        require(
            not any(part in forbidden_parts for part in relative_parts)
            and not any(marker in normalized for marker in forbidden_docs),
            f"local-only artifact path should not be committed: {path.relative_to(ROOT)}",
        )
        if path.is_dir():
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
        server_cwd = root / "apps" / "web"
        server_cwd.mkdir(parents=True)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["SWITCHYARD_HOME"] = str(root / "home")
        readonly_payload = read("tests/fixtures/mcp_readonly_smoke.jsonl") + "\n"
        result = run([sys.executable, "-m", "switchyard", "mcp"], cwd=server_cwd, env=env, input_text=readonly_payload)
        lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(lines[0]["result"]["serverInfo"]["name"] == "switchyard", "MCP initialize failed")
        require("switchyard://project/brief" in lines[0]["result"]["instructions"], "MCP instructions should teach resource-first flow")
        require("switchyard_runtime_handoff" in lines[0]["result"]["instructions"], "MCP instructions should mention handoff prompt")
        require("Prefer switchyard_brief first" not in lines[0]["result"]["instructions"], "MCP instructions should not teach stale tool-first flow")
        require("resources" in lines[0]["result"]["capabilities"], "MCP initialize should advertise resources")
        require("prompts" in lines[0]["result"]["capabilities"], "MCP initialize should advertise prompts")
        instructions = lines[0]["result"]["instructions"]
        require("configured_services" in instructions, "MCP instructions should teach configured service discovery")
        require("env_warnings" in instructions, "MCP instructions should teach env warning checks")
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
        for name in ["switchyard_status", "switchyard_uncheckout", "switchyard_down"]:
            branch_description = tools[name]["inputSchema"]["properties"]["branch"]["description"]
            require(
                "registered worktree branch" in branch_description and "project root" in branch_description,
                f"{name} should describe worktree-scoped branch defaults",
            )
        require(all("outputSchema" in tool for tool in tools.values()), "MCP tools should include output schemas")
        cwd_description = tools["switchyard_brief"]["inputSchema"]["properties"]["cwd"]["description"]
        require("Defaults to the server launch cwd" in cwd_description, "MCP cwd schema should document launch cwd default")
        require("registered worktree" in cwd_description, "MCP cwd schema should document worktree default")
        require(
            "services" in tools["switchyard_status"]["outputSchema"]["properties"],
            "switchyard_status should describe services output",
        )
        require(
            "logs" in tools["switchyard_logs"]["outputSchema"]["properties"],
            "switchyard_logs should describe logs output",
        )
        require(
            "env_warnings" in tools["switchyard_brief"]["outputSchema"]["properties"],
            "switchyard_brief should describe env warning output",
        )
        require(
            "configured_services" in tools["switchyard_brief"]["outputSchema"]["properties"],
            "switchyard_brief should describe configured services output",
        )
        resources = {resource["uri"]: resource for resource in lines[2]["result"]["resources"]}
        require("switchyard://project/brief" in resources, "MCP resources should include project brief")
        require("switchyard://agent/guide" in resources, "MCP resources should include agent guide")
        require(
            json.loads(lines[3]["result"]["contents"][0]["text"])["project"] == "demo",
            "MCP project brief resource failed",
        )
        require(
            "env_warnings" in json.loads(lines[3]["result"]["contents"][0]["text"]),
            "MCP project brief resource should include env warnings",
        )
        require(
            json.loads(lines[3]["result"]["contents"][0]["text"])["configured_services"] == ["web"],
            "MCP project brief resource should include configured services",
        )
        require(
            "switchyard_brief" in lines[4]["result"]["contents"][0]["text"],
            "MCP agent guide resource should teach switchyard_brief",
        )
        prompts = {prompt["name"]: prompt for prompt in lines[5]["result"]["prompts"]}
        require("switchyard_runtime_handoff" in prompts, "MCP prompts should include runtime handoff")
        require("switchyard_branch_runtime" in prompts, "MCP prompts should include branch runtime")
        require(
            "feature/mcp" in lines[6]["result"]["messages"][0]["content"]["text"],
            "MCP branch runtime prompt should render branch argument",
        )
        require(lines[7]["result"]["structuredContent"]["project"] == "demo", "MCP doctor failed")
        require(lines[7]["result"]["structuredContent"]["env_warnings"] == [], "MCP doctor should include env warnings")
        require(lines[8]["result"]["structuredContent"] == {"services": []}, "MCP status should return services envelope")
        require(lines[9]["result"]["isError"] is True, "MCP tools should reject unknown arguments")
        require("unexpected argument(s): servies" in lines[9]["result"]["content"][0]["text"], "MCP typo error should be clear")
        require(lines[10]["result"]["isError"] is True, "MCP tools should reject non-string cwd")
        require("cwd must be a string" in lines[10]["result"]["content"][0]["text"], "MCP cwd type error should be clear")
        require(lines[11]["error"]["code"] == -32602, "MCP tools should reject non-object arguments")
        require("arguments must be an object" in lines[11]["error"]["message"], "MCP arguments type error should be clear")
        require(lines[12]["error"]["code"] == -32602, "MCP initialize should reject non-string protocolVersion")
        require(
            "protocolVersion must be a string" in lines[12]["error"]["message"],
            "MCP protocolVersion type error should be clear",
        )
        require(not (root / "home").exists(), "read-only MCP context should not initialize Switchyard state")

        action_payload = read("tests/fixtures/mcp_action_smoke.jsonl") + "\n"
        result = run([sys.executable, "-m", "switchyard", "mcp"], cwd=server_cwd, env=env, input_text=action_payload)
        action_lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(action_lines[0]["result"]["structuredContent"]["created"] is True, "MCP create failed")
        require(action_lines[1]["result"]["structuredContent"]["worktrees"][0]["branch"] == "feature/mcp", "MCP list failed")
        require(action_lines[2]["result"]["structuredContent"]["branch"] == "feature/mcp", "MCP up failed")
        require(action_lines[3]["result"]["structuredContent"]["service"] == "web", "MCP where failed")
        require(action_lines[4]["result"]["structuredContent"]["logs"][0]["service"] == "web", "MCP logs failed")
        require(action_lines[5]["result"]["structuredContent"]["branch"] == "feature/mcp", "MCP checkout failed")
        require(action_lines[6]["result"]["structuredContent"]["branch"] == "feature/mcp", "MCP uncheckout failed")
        require(action_lines[7]["result"]["structuredContent"]["branch"] == "feature/mcp", "MCP down failed")
        worktree = Path(action_lines[0]["result"]["structuredContent"]["worktree"])
        result = run(
            [sys.executable, "-m", "switchyard", "mcp"],
            cwd=worktree,
            env=env,
            input_text='{"jsonrpc":"2.0","id":21,"method":"resources/read","params":{"uri":"switchyard://project/brief"}}\n',
        )
        worktree_brief = json.loads(json.loads(result.stdout)["result"]["contents"][0]["text"])
        require(worktree_brief["project"] == "demo", "MCP worktree launch should use parent project")
        require(
            Path(worktree_brief["project_root"]).resolve() == root.resolve(),
            "MCP worktree launch should keep parent project root",
        )
        require(worktree_brief["branch"] == "feature/mcp", "MCP worktree launch should default to worktree branch")
        require(worktree_brief["configured_services"] == ["web"], "MCP worktree launch should keep configured services")
        run([sys.executable, "-m", "switchyard", "mcp", "config", "--name", "demo"], cwd=root, env=env)
        result = run(
            [sys.executable, "-m", "switchyard", "mcp", "--project", "demo"],
            cwd=worktree,
            env=env,
            input_text='{"jsonrpc":"2.0","id":22,"method":"resources/read","params":{"uri":"switchyard://project/brief"}}\n',
        )
        alias_worktree_brief = json.loads(json.loads(result.stdout)["result"]["contents"][0]["text"])
        require(
            alias_worktree_brief["branch"] == "feature/mcp",
            "MCP alias launch from a registered worktree should keep the worktree branch",
        )
    ok("MCP smoke")


def check_cli_json_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="switchyard-release-cli-") as temp:
        workspace = Path(temp)
        root = workspace / "project"
        root.mkdir()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["SWITCHYARD_HOME"] = str(workspace / "home")
        result = run([sys.executable, "-m", "switchyard", "init", "--dry-run", "--json"], cwd=root, env=env)
        init_data = json.loads(result.stdout)
        require(init_data["ok"] is True, "init --dry-run --json should report ok")
        require(init_data["dry_run"] is True and init_data["written"] is False, "init dry run should not write")
        require(init_data["would_fail"] is False, "fresh init dry run should not report a blocker")
        require(init_data["created_config"] is False, "init dry run should not report created config")
        require("[services.web]" in init_data["config_text"], "init dry run should include generated config")
        require("Commands should honor PORT/HOST" in init_data["config_text"], "init dry run should explain dynamic port contract")
        require(not (root / "switchyard.toml").exists(), "init dry run should not write switchyard.toml")
        (root / "package.json").write_text('{"scripts":{"dev":"vite"}}')
        result = run([sys.executable, "-m", "switchyard", "init", "--dry-run", "--json"], cwd=root, env=env)
        package_init_data = json.loads(result.stdout)
        require(
            'command = "npm run dev -- --port {port}"' in package_init_data["config_text"],
            "init dry run should generate port-aware npm dev command",
        )
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
        (root / "app").mkdir()
        result = run([sys.executable, "-m", "switchyard", "doctor", "--json"], cwd=root, env=env)
        data = json.loads(result.stdout)
        require(data["ok"] is True, "doctor --json should report ok")
        require(data["project"]["name"] == "demo", "doctor --json project name mismatch")
        require(data["services"] == ["web"], "doctor --json service list mismatch")
        require(data["env_warnings"] == [], "doctor --json should include env warnings")
        result = run([sys.executable, "-m", "switchyard", "list", "--json"], cwd=root, env=env)
        data = json.loads(result.stdout)
        require(data == {"worktrees": []}, "list --json should report empty worktrees")
        with tempfile.TemporaryDirectory(prefix="switchyard-missing-config-") as missing:
            result = run([sys.executable, "-m", "switchyard", "mcp", "config", "--json"], cwd=Path(missing), env=env, check=False)
            missing_config = json.loads(result.stdout)
            require(result.returncode == 1, "mcp config --json should fail outside a project")
            require(missing_config["ok"] is False and CONFIG_NAME in missing_config["error"], "mcp config --json failure should be machine-readable")
        result = run([sys.executable, "-m", "switchyard", "mcp", "install", "--help"], cwd=root, env=env)
        require(
            "Print the Codex config update without writing it" in result.stdout,
            "mcp install help should describe TOML config dry run",
        )
        require("codex mcp add" not in result.stdout, "mcp install help should not mention obsolete codex mcp add")
        result = run([sys.executable, "-m", "switchyard", "mcp", "--help"], cwd=root, env=env)
        require("[config|install|projects]" in result.stdout, "mcp help usage should show setup subcommands as optional")
        require("commands:" in result.stdout, "mcp help should label setup subcommands as commands")
        require("positional arguments:" not in result.stdout, "mcp help should not make setup subcommands look required")
        require("Run inside a project" in result.stdout, "mcp help should point users at path-free project setup")
        require("switchyard mcp install" in result.stdout, "mcp help should point users at generated setup")
        require("--project" in result.stdout, "mcp help should point users at alias setup")
        require("Run without a subcommand to start the stdio MCP server" in result.stdout, "mcp help should explain no-subcommand server start")
        require("--cwd" not in result.stdout, "mcp help should not advertise cwd setup")
        require("Escape hatch" not in result.stdout, "mcp help should not make cwd setup first-class")
        require("/path/to/project" not in result.stdout, "mcp help should not use path placeholders")
        for subcommand in ["config", "install"]:
            result = run([sys.executable, "-m", "switchyard", "mcp", subcommand, "--help"], cwd=root, env=env)
            require(f"usage: switchyard mcp {subcommand}" in result.stdout, f"mcp {subcommand} help should use a clean prog")
            require("[config|install|projects]" not in result.stdout, f"mcp {subcommand} help should not include parent usage noise")
            require("--cwd" not in result.stdout, f"mcp {subcommand} help should not advertise cwd setup")
            require("/path/to/project" not in result.stdout, f"mcp {subcommand} help should not use path placeholders")
        result = run([sys.executable, "-m", "switchyard", "mcp", "install", "--dry-run"], cwd=root, env=env)
        require("# Would update:" in result.stdout, "mcp install dry run should print target config path")
        require('"--project", "switchyard"' in result.stdout, "mcp install dry run should use project alias args")
        require("Dry run only: the alias is not registered" in result.stdout, "mcp install dry run should explain alias is not registered")
        require("cwd =" not in result.stdout, "mcp install dry run should not require Codex cwd field")
        require(str(root.resolve()) not in result.stdout, "mcp install dry run should not print project paths into setup")
        require("/path/to/project" not in result.stdout, "mcp install dry run should not use path placeholders")
        result = run([sys.executable, "-m", "switchyard", "mcp", "install", "--dry-run", "--json"], cwd=root, env=env)
        install_json = json.loads(result.stdout)
        require(install_json["ok"] is True and install_json["dry_run"] is True, "mcp install dry-run --json should report dry run")
        require(install_json["registered"] is False, "mcp install dry-run --json should not claim registration")
        require(install_json["args"][-2:] == ["--project", "switchyard"], "mcp install dry-run --json should use project alias args")
        require(
            install_json["env"].get("SWITCHYARD_HOME") == str(Path(env["SWITCHYARD_HOME"]).resolve()),
            "mcp install dry-run --json should preserve SWITCHYARD_HOME",
        )
        require("[mcp_servers.switchyard.env]" in install_json["config_text"], "mcp install dry-run --json should emit MCP env table")
        require("cwd =" not in install_json["config_text"], "mcp install dry-run --json should not require Codex cwd field")
        require(str(root.resolve()) not in result.stdout, "mcp install dry-run --json should not print project paths")
        result = run([sys.executable, "-m", "switchyard", "mcp", "config"], cwd=root, env=env)
        require('"--project", "switchyard"' in result.stdout, "mcp config should use project alias args")
        require(str(Path(env["SWITCHYARD_HOME"]).resolve()) in result.stdout, "mcp config should preserve SWITCHYARD_HOME for alias lookup")
        require("cwd =" not in result.stdout, "mcp config should not require Codex cwd field")
        require(str(root.resolve()) not in result.stdout, "mcp config should not print project paths into setup")
        require("/path/to/project" not in result.stdout, "mcp config should not use path placeholders")
        result = run([sys.executable, "-m", "switchyard", "mcp", "config", "--json"], cwd=root, env=env)
        config_json = json.loads(result.stdout)
        require(config_json["ok"] is True and config_json["registered"] is True, "mcp config --json should register alias")
        require(config_json["args"][-2:] == ["--project", "switchyard"], "mcp config --json should use project alias args")
        require(
            config_json["env"].get("SWITCHYARD_HOME") == str(Path(env["SWITCHYARD_HOME"]).resolve()),
            "mcp config --json should preserve SWITCHYARD_HOME",
        )
        require("cwd =" not in config_json["config_text"], "mcp config --json should not require Codex cwd field")
        require(str(root.resolve()) not in result.stdout, "mcp config --json should not print project paths")
        result = run([sys.executable, "-m", "switchyard", "mcp", "projects", "--json"], cwd=root, env=env)
        projects_json = json.loads(result.stdout)
        require(
            projects_json["home"] == str(Path(env["SWITCHYARD_HOME"]).resolve()),
            "mcp projects --json should report Switchyard home",
        )
        require(
            projects_json["state_path"] == str((Path(env["SWITCHYARD_HOME"]).resolve() / "state.json")),
            "mcp projects --json should report Switchyard state path",
        )
        projects = projects_json["projects"]
        require(projects and projects[0]["name"] == "switchyard", "mcp projects should list registered alias")
        require(projects[0]["status"] == "ok", "mcp projects should report healthy alias")
        result = run(
            [
                sys.executable,
                str(ROOT / "scripts/mcp_project_smoke.py"),
                "--json",
                "--nested",
                "app",
                "--name",
                "release-smoke",
                str(root),
            ],
            cwd=ROOT,
        )
        project_smoke = json.loads(result.stdout)
        require(project_smoke["ok"] is True, "MCP project smoke harness should pass")
        require(project_smoke["cwd"] == str((root / "app").resolve()), "MCP project smoke harness should run from the nested cwd")
        require(project_smoke["alias"]["name"] == "release-smoke", "MCP project smoke harness should use the requested alias")
        require(project_smoke["alias"]["status"] == "ok", "MCP project smoke harness should report a healthy alias")
        env["CODEX_HOME"] = str(root / "codex-home")
        result = run([sys.executable, "-m", "switchyard", "mcp", "install", "--json"], cwd=root, env=env)
        install_result = json.loads(result.stdout)
        require(install_result["ok"] is True and install_result["registered"] is True, "mcp install --json should report registration")
        require(install_result["dry_run"] is False, "mcp install --json should report real install")
        config_text = (Path(env["CODEX_HOME"]) / "config.toml").read_text()
        require('"--project", "switchyard"' in config_text, "mcp install should write project alias args")
        require("[mcp_servers.switchyard.env]" in config_text, "mcp install should write MCP env table")
        require(str(Path(env["SWITCHYARD_HOME"]).resolve()) in config_text, "mcp install should preserve SWITCHYARD_HOME")
        require("cwd =" not in config_text, "mcp install should not write Codex cwd field")
        require(str(root.resolve()) not in config_text, "mcp install should not write project paths")
        require("--cwd" not in config_text, "mcp install should not write cwd into server args")
        collision_root = root / "collision"
        collision_root.mkdir()
        (collision_root / CONFIG_NAME).write_text(
            textwrap.dedent(
                """
                [project]
                name = "collision"

                [services.web]
                command = "python -m http.server {port}"
                """
            )
        )
        result = run(
            [sys.executable, "-m", "switchyard", "mcp", "install", "--json"],
            cwd=collision_root,
            env=env,
            check=False,
        )
        collision_error = json.loads(result.stdout)
        require(result.returncode == 1, "mcp install --json should fail on alias collision")
        require(
            collision_error["ok"] is False and "already points" in collision_error["error"],
            "mcp install --json alias collision should be machine-readable",
        )
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
    require(metrics["brief_json"]["has_configured_services"] is True, "brief output should include configured services")
    require(metrics["brief_json"]["has_checkouts"] is True, "brief output should include checkout state")
    require(metrics["brief_json"]["has_env_warnings"] is True, "brief output should include env warnings")
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
        require("switchyard/assets/skills/switchyard/SKILL.md" in wheel_names, "wheel should include packaged Switchyard skill")
        require(
            "switchyard/assets/skills/switchyard/agents/openai.yaml" in wheel_names,
            "wheel should include packaged Switchyard skill agent config",
        )
        install_dir = root / "install"
        install_dir.mkdir()
        run([str(python), "-m", "pip", "install", "--target", str(install_dir), str(wheel)], cwd=root)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(install_dir)
        env["SWITCHYARD_HOME"] = str(root / "home")
        result = run([str(python), "-m", "switchyard", "--version"], cwd=root, env=env)
        require(f"switchyard {project_version()}" in result.stdout, "installed package version check failed")
        smoke_project = root / "smoke-project"
        smoke_project.mkdir()
        run(["git", "init"], cwd=smoke_project)
        run(["git", "config", "user.email", "test@example.com"], cwd=smoke_project)
        run(["git", "config", "user.name", "Test User"], cwd=smoke_project)
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
        run(["git", "add", "switchyard.toml"], cwd=smoke_project)
        run(["git", "commit", "-m", "init"], cwd=smoke_project)
        result = run([str(python), "-m", "switchyard", "doctor", "--json"], cwd=smoke_project, env=env)
        require(json.loads(result.stdout)["project"]["name"] == "installed-demo", "installed doctor --json failed")
        result = run([str(python), "-m", "switchyard", "mcp", "config"], cwd=smoke_project, env=env)
        require('"--project", "switchyard"' in result.stdout, "installed mcp config should use project alias args")
        require("cwd =" not in result.stdout, "installed mcp config should not require Codex cwd field")
        require(str(smoke_project.resolve()) not in result.stdout, "installed mcp config should not print project paths")
        result = run([str(python), "-m", "switchyard", "mcp", "config", "--json"], cwd=smoke_project, env=env)
        config_json = json.loads(result.stdout)
        require(config_json["ok"] is True and config_json["registered"] is True, "installed mcp config --json should register alias")
        require(config_json["args"][-2:] == ["--project", "switchyard"], "installed mcp config --json should use project alias args")
        require("cwd =" not in config_json["config_text"], "installed mcp config --json should not require Codex cwd field")
        require(str(smoke_project.resolve()) not in result.stdout, "installed mcp config --json should not print project paths")
        result = run([str(python), "-m", "switchyard", "mcp", "projects", "--json"], cwd=smoke_project, env=env)
        projects_json = json.loads(result.stdout)
        require(
            projects_json["home"] == str(Path(env["SWITCHYARD_HOME"]).resolve()),
            "installed mcp projects --json should report Switchyard home",
        )
        require(
            projects_json["state_path"] == str((Path(env["SWITCHYARD_HOME"]).resolve() / "state.json")),
            "installed mcp projects --json should report Switchyard state path",
        )
        projects = projects_json["projects"]
        require(projects and projects[0]["name"] == "switchyard", "installed mcp projects should list registered alias")
        require(projects[0]["status"] == "ok", "installed mcp projects should report healthy alias")
        result = run([str(python), "-m", "switchyard", "mcp", "install", "--dry-run"], cwd=smoke_project, env=env)
        require("# Would update:" in result.stdout, "installed mcp install dry run should print target config path")
        require('"--project", "switchyard"' in result.stdout, "installed mcp install dry run should use project alias args")
        require("Dry run only: the alias is not registered" in result.stdout, "installed mcp install dry run should explain alias is not registered")
        result = run([str(python), "-m", "switchyard", "mcp", "install", "--dry-run", "--json"], cwd=smoke_project, env=env)
        install_json = json.loads(result.stdout)
        require(install_json["ok"] is True and install_json["dry_run"] is True, "installed mcp install dry-run --json should report dry run")
        require(install_json["registered"] is False, "installed mcp install dry-run --json should not claim registration")
        require(install_json["args"][-2:] == ["--project", "switchyard"], "installed mcp install dry-run --json should use alias args")
        nested = smoke_project / "apps" / "web"
        nested.mkdir(parents=True)
        mcp_payload = "\n".join(
            [
                '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"switchyard_doctor","arguments":{}}}',
                '{"jsonrpc":"2.0","id":2,"method":"resources/read","params":{"uri":"switchyard://project/brief"}}',
                '{"jsonrpc":"2.0","id":3,"method":"prompts/get","params":{"name":"switchyard_branch_runtime","arguments":{"branch":"feature/install","services":"web"}}}',
                "",
            ]
        )
        result = run([str(python), "-m", "switchyard", "mcp"], cwd=nested, env=env, input_text=mcp_payload)
        mcp_lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(
            mcp_lines[0]["result"]["structuredContent"]["project"] == "installed-demo",
            "installed mcp server should auto-detect project root",
        )
        require(
            json.loads(mcp_lines[1]["result"]["contents"][0]["text"])["project"] == "installed-demo",
            "installed mcp resources should auto-detect project root",
        )
        require(
            "feature/install" in mcp_lines[2]["result"]["messages"][0]["content"]["text"],
            "installed mcp prompts should render branch argument",
        )
        result = run([str(python), "-m", "switchyard", "create", "feature/installed-worktree", "--json"], cwd=smoke_project, env=env)
        create_data = json.loads(result.stdout)
        require(create_data["ok"] is True and create_data["branch"] == "feature/installed-worktree", "installed create --json failed")
        installed_worktree = Path(create_data["worktree"])
        result = run([str(python), "-m", "switchyard", "mcp"], cwd=installed_worktree, env=env, input_text=mcp_payload)
        mcp_lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(
            mcp_lines[0]["result"]["structuredContent"]["project"] == "installed-demo",
            "installed mcp server should use parent project from registered worktree",
        )
        worktree_brief = json.loads(mcp_lines[1]["result"]["contents"][0]["text"])
        require(
            Path(worktree_brief["project_root"]).resolve() == smoke_project.resolve(),
            "installed mcp resources should keep parent project root from registered worktree",
        )
        require(
            worktree_brief["branch"] == "feature/installed-worktree",
            "installed mcp resources should default to registered worktree branch",
        )
        result = run([str(python), "-m", "switchyard", "mcp", "--project", "switchyard"], cwd=root, env=env, input_text=mcp_payload)
        mcp_lines = [json.loads(line) for line in result.stdout.splitlines()]
        require(
            mcp_lines[0]["result"]["structuredContent"]["project"] == "installed-demo",
            "installed mcp server should resolve local project alias",
        )
        require(
            json.loads(mcp_lines[1]["result"]["contents"][0]["text"])["project"] == "installed-demo",
            "installed mcp resources should resolve local project alias",
        )
        require(
            "feature/install" in mcp_lines[2]["result"]["messages"][0]["content"]["text"],
            "installed mcp prompts should resolve local project alias",
        )
        result = run([str(python), "-m", "switchyard", "mcp", "--project", "switchyard"], cwd=installed_worktree, env=env, input_text=mcp_payload)
        mcp_lines = [json.loads(line) for line in result.stdout.splitlines()]
        alias_worktree_brief = json.loads(mcp_lines[1]["result"]["contents"][0]["text"])
        require(
            alias_worktree_brief["branch"] == "feature/installed-worktree",
            "installed mcp alias launch from a registered worktree should keep the worktree branch",
        )
        result = run([str(python), "-m", "switchyard", "skill", "show"], cwd=root, env=env)
        require("switchyard_brief" in result.stdout, "installed package missing bundled skill")
        skill_target = root / "skills"
        run([str(python), "-m", "switchyard", "skill", "install", "--target", str(skill_target)], cwd=root, env=env)
        require((skill_target / "switchyard" / "SKILL.md").exists(), "installed package could not install skill")
        require((skill_target / "switchyard" / "agents" / "openai.yaml").exists(), "installed package could not install skill agent config")
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
        check_examples,
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
