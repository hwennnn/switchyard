# Release

Switchyard is packaged on PyPI as `switchyard-dev` because `switchyard` is
already occupied by another Python project. The installed console commands are
still:

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
2. Configure a Trusted Publisher for `hwennnn/switchyard`.
3. Set the workflow name to `release.yml`.
4. Finalize the changelog entry for the package version.
5. Tag the release as `v<version>` from `src/switchyard/__init__.py`.
6. Run the `Release` workflow manually from that tag with `publish_target` set
   to `testpypi`.
7. Install from TestPyPI and smoke test the CLI.
8. Run the same workflow from the tag with `publish_target` set to `pypi`.

The workflow rejects branch runs, mismatched tags, and changelog entries that
still say `Unreleased`.

Manual install smoke:

```sh
pipx install switchyard-dev
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
! (cd "$project" && switchyard mcp config | grep -F "cwd =")
(cd "$project" && switchyard mcp install --dry-run | grep -F "# Would update:")
printf '%s\n\n' '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"switchyard_doctor","arguments":{}}}' \
  | switchyard mcp --project switchyard \
  | grep release-smoke
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
