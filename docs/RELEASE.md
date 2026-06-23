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
4. Run the `Release` workflow manually with `publish_target` set to `testpypi`.
5. Install from TestPyPI and smoke test the CLI.
6. Run the same workflow with `publish_target` set to `pypi`.

Manual install smoke:

```sh
pipx install switchyard-dev
switchyard --version
switchyard mcp --help
switchyard mcp config
switchyard skill show

tmp="$(mktemp -d)"
cat > "$tmp/switchyard.toml" <<'EOF'
[project]
name = "release-smoke"

[services.web]
command = "python -m http.server {port}"
EOF
(cd "$tmp" && switchyard doctor --json)
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
