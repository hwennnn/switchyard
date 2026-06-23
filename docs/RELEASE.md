# Release

Switchyard will be published on PyPI as `switchyard-dev` because `switchyard`
is already occupied by another Python project. The installed console commands
are still:

```sh
switchyard
sy
```

## Local Readiness

Run the full release gate:

```sh
python3 scripts/release_check.py
```

For offline development, skip the networked package build tools:

```sh
python3 scripts/release_check.py --skip-package
```

Run benchmarks:

```sh
python3 scripts/benchmark.py --runs 3
```

## Build

```sh
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine check dist/*
```

## Publish

Use PyPI Trusted Publishing through GitHub Actions. This avoids long-lived PyPI
API tokens in repository secrets.

1. Create or claim the `switchyard-dev` project on PyPI/TestPyPI.
2. Configure Trusted Publishers for `hwennnn/switchyard`.
3. Set the workflow name to `release.yml`.
4. Set the environment to `testpypi` for TestPyPI and `pypi` for PyPI.
5. Finalize the changelog entry for the package version.
6. Tag the release as `v<version>` from `src/switchyard/__init__.py`.
7. Run the `Release` workflow manually from that tag with `publish_target` set
   to `testpypi`.
8. Install from TestPyPI and smoke test the CLI.
9. Run the same workflow from the tag with `publish_target` set to `pypi`
   and `testpypi_smoke_confirmed` checked.

The workflow rejects branch runs, mismatched tags, and changelog entries that
still say `Unreleased`.

If TestPyPI fails with `invalid-publisher`, create or update the TestPyPI
trusted publisher so it matches these claims:

```txt
repository: hwennnn/switchyard
workflow: release.yml
environment: testpypi
ref: refs/tags/v0.1.0
```

For PyPI, use the same repository and workflow with environment `pypi`.

After publishing to TestPyPI, run an install smoke against the TestPyPI index:

```sh
version=0.1.0
python3 -m venv /tmp/switchyard-testpypi-smoke
. /tmp/switchyard-testpypi-smoke/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "switchyard-dev==$version"
```

After publishing to PyPI, run the same smoke from the public index:

```sh
pipx install switchyard-dev
```

Then smoke the installed command from inside a temporary project. The MCP setup
commands must infer the project from the current checkout and must not require
`cwd`, `--cwd`, or an absolute project path:

```sh
switchyard --version
switchyard mcp --help
switchyard skill show

tmp="$(mktemp -d)"
export SWITCHYARD_HOME="$tmp/switchyard-home"
export CODEX_HOME="$tmp/codex-home"
project="$tmp/project"
mkdir -p "$project"
cat > "$project/switchyard.toml" <<'EOF'
[project]
name = "release-smoke"

[services.web]
command = "python -m http.server {port}"
EOF
(cd "$project" && switchyard doctor --json | grep '"env_warnings": \[\]')
(cd "$project" && switchyard mcp config | grep -F 'args = ["mcp", "--project", "switchyard"]')
(cd "$project" && switchyard mcp config --json > "$tmp/mcp-config.json")
PROJECT="$project" TMP="$tmp" python3 - <<'PY'
import json
import os
from pathlib import Path

project = Path(os.environ["PROJECT"]).resolve()
text = Path(os.environ["TMP"], "mcp-config.json").read_text()
data = json.loads(text)
assert data["ok"] is True
assert data["registered"] is True
assert data["args"][-2:] == ["--project", "switchyard"]
assert data["env"]["SWITCHYARD_HOME"] == str(Path(os.environ["SWITCHYARD_HOME"]).resolve())
assert "[mcp_servers.switchyard.env]" in data["config_text"]
assert "cwd =" not in data["config_text"]
assert str(project) not in data["config_text"]
PY
(cd "$project" && switchyard mcp projects --json | grep '"name": "switchyard"')
(cd "$project" && switchyard mcp projects --json | grep '"status": "ok"')
(cd "$project" && switchyard mcp smoke --json > "$tmp/mcp-smoke.json")
grep '"ok": true' "$tmp/mcp-smoke.json"
! (cd "$project" && switchyard mcp config | grep -F "cwd =")
(cd "$project" && switchyard mcp install --dry-run | grep -F "# Would update:")
(cd "$project" && switchyard mcp install --dry-run --json > "$tmp/mcp-install-dry-run.json")
PROJECT="$project" TMP="$tmp" python3 - <<'PY'
import json
import os
from pathlib import Path

project = Path(os.environ["PROJECT"]).resolve()
text = Path(os.environ["TMP"], "mcp-install-dry-run.json").read_text()
data = json.loads(text)
assert data["ok"] is True
assert data["dry_run"] is True
assert data["registered"] is False
assert data["args"][-2:] == ["--project", "switchyard"]
assert data["env"]["SWITCHYARD_HOME"] == str(Path(os.environ["SWITCHYARD_HOME"]).resolve())
assert "[mcp_servers.switchyard.env]" in data["config_text"]
assert "cwd =" not in data["config_text"]
assert str(project) not in data["config_text"]
PY
(cd "$project" && switchyard mcp install --json > "$tmp/mcp-install.json")
PROJECT="$project" CODEX_HOME="$CODEX_HOME" TMP="$tmp" python3 - <<'PY'
import json
import os
from pathlib import Path

project = Path(os.environ["PROJECT"]).resolve()
codex_config = Path(os.environ["CODEX_HOME"], "config.toml")
text = Path(os.environ["TMP"], "mcp-install.json").read_text()
data = json.loads(text)
config_text = codex_config.read_text()
assert data["ok"] is True
assert data["dry_run"] is False
assert data["registered"] is True
assert data["args"][-2:] == ["--project", "switchyard"]
assert data["codex_config_path"] == str(codex_config)
assert data["env"]["SWITCHYARD_HOME"] == str(Path(os.environ["SWITCHYARD_HOME"]).resolve())
assert "[mcp_servers.switchyard.env]" in data["config_text"]
assert "[mcp_servers.switchyard.env]" in config_text
assert "cwd =" not in data["config_text"]
assert "cwd =" not in config_text
assert str(project) not in data["config_text"]
assert str(project) not in config_text
PY
printf '%s\n\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"switchyard_doctor","arguments":{}}}' \
  | switchyard mcp --project switchyard \
  | grep release-smoke
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"resources/read","params":{"uri":"switchyard://project/brief"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"prompts/get","params":{"name":"switchyard_branch_runtime","arguments":{"branch":"feature/release","services":"web"}}}' \
  | switchyard mcp --project switchyard > "$tmp/mcp-smoke.jsonl"
grep -F 'switchyard://project/brief' "$tmp/mcp-smoke.jsonl"
grep -F 'feature/release' "$tmp/mcp-smoke.jsonl"
```

## Versioning

Update:

- `src/switchyard/__init__.py`
- `CHANGELOG.md`

Then tag:

```sh
git tag v0.1.0
git push origin v0.1.0
```
