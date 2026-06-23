# Local Publishing And CI/CD Guide

This guide is the local runbook for publishing the Switchyard Python CLI and
maintaining the GitHub Actions CI/CD setup.

Switchyard publishes the PyPI distribution `switchyard-dev`. The installed
console commands are `switchyard` and `sy`.

Official references:

- [Python Packaging: Packaging Python Projects](https://packaging.python.org/tutorials/packaging-projects/)
- [Python Packaging: GitHub Actions publishing guide](https://packaging.python.org/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
- [PyPI: Publishing with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/)
- [PyPI: Creating a project with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)

## One-Time Accounts

Create or verify:

1. GitHub repository: `hwennnn/switchyard`.
2. TestPyPI account with two-factor authentication enabled.
3. PyPI account with two-factor authentication enabled.

Use Trusted Publishing instead of long-lived API tokens. The release workflow
already grants `id-token: write` only on publish jobs.

## One-Time Trusted Publisher Setup

Create pending publishers on both TestPyPI and PyPI for:

```txt
project: switchyard-dev
owner/repository: hwennnn/switchyard
workflow: release.yml
environment: testpypi  # on TestPyPI
environment: pypi      # on PyPI
```

Use a pending publisher if the project page does not exist yet. After first
upload, verify the project pages exist and the publisher is attached to the
created project.

If GitHub reports `invalid-publisher`, compare the claims printed in the
workflow summary with the publisher form. For `v0.1.0`, the expected claims are:

```txt
repository: hwennnn/switchyard
workflow: release.yml
ref: refs/tags/v0.1.0
environment: testpypi or pypi
```

## GitHub Environments

Create GitHub environments:

- `testpypi`
- `pypi`

The workflow uses these environment names because PyPI validates the OIDC
environment claim. Optional but recommended:

- Require manual approval for `pypi`.
- Do not require approval for `testpypi` unless you want a slower release loop.

No PyPI token secrets are required.

## Local Development Setup

```sh
cd /Users/houman/projects/switchyard
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Run the normal fast gate:

```sh
python3 scripts/release_check.py --skip-package
```

Run the full release gate before publishing:

```sh
python3 scripts/release_check.py
```

The full gate builds the wheel and sdist, runs `twine check`, install-smokes the
wheel, executes both `switchyard --version` and `sy --version`, checks MCP setup,
and enforces release workflow guardrails.

## Local Build Smoke

Use this when you want a manual package sanity check:

```sh
rm -rf dist build *.egg-info
python3 -m pip install --upgrade build twine
python3 -m build
python3 -m twine check dist/*
python3 -m venv /tmp/switchyard-wheel-smoke
. /tmp/switchyard-wheel-smoke/bin/activate
python -m pip install dist/*.whl
switchyard --version
sy --version
```

Then smoke MCP setup from a throwaway project:

```sh
tmp="$(mktemp -d)"
export SWITCHYARD_HOME="$tmp/switchyard-home"
export CODEX_HOME="$tmp/codex-home"
project="$tmp/project"
mkdir -p "$project"
cat > "$project/switchyard.toml" <<'EOF'
[project]
name = "local-publish-smoke"

[services.web]
command = "python -m http.server {port}"
EOF

(cd "$project" && switchyard doctor --json)
(cd "$project" && switchyard mcp config --json)
(cd "$project" && switchyard mcp smoke --json)
```

The generated MCP config should use `args = ["mcp", "--project", "switchyard"]`
and should not contain `cwd`, `--cwd`, or the project path.

## CI

CI lives at `.github/workflows/ci.yml`.

It runs on pushes and pull requests to `main` and:

- Checks out the repo.
- Tests Python 3.11, 3.12, and 3.13.
- Runs `python -m unittest discover -s tests`.
- Runs `python scripts/release_check.py --skip-package`.

CI uses read-only repository permissions.

## Docs Publishing

Docs CD lives at `.github/workflows/docs.yml`.

One-time GitHub setup:

1. Open the repository on GitHub.
2. Go to `Settings` -> `Pages`.
3. Under `Build and deployment`, set `Source` to `GitHub Actions`.
4. Save the setting.

The workflow:

- Runs on pushes to `main` that change `docs/**`, `mkdocs.yml`, or the docs
  workflow.
- Can also be run manually with `workflow_dispatch`.
- Installs `mkdocs==1.6.1`.
- Runs `mkdocs build --strict`.
- Uploads the generated `site/` directory as a GitHub Pages artifact.
- Deploys with the official GitHub Pages deployment action.

The workflow needs:

```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

It deploys to the `github-pages` environment and should publish to:

```txt
https://hwennnn.github.io/switchyard/
```

Local docs smoke:

```sh
python3 -m venv /tmp/switchyard-docs
. /tmp/switchyard-docs/bin/activate
python -m pip install mkdocs==1.6.1
mkdocs build --strict
```

## Release Workflow

Release CD lives at `.github/workflows/release.yml` and is manual
(`workflow_dispatch`) on a tag.

Inputs:

- `publish_target`: `testpypi` or `pypi`.
- `testpypi_smoke_confirmed`: required for `pypi`.

The build job:

- Rejects branch runs.
- Requires tag `v<version>` from `src/switchyard/__init__.py`.
- Requires finalized `CHANGELOG.md`.
- Runs the full release gate.
- Builds wheel and sdist.
- Install-smokes the wheel, MCP setup, MCP resources/prompts, and bundled skill.
- Uploads distributions as a workflow artifact.

The TestPyPI job:

- Uses GitHub OIDC Trusted Publishing.
- Publishes to TestPyPI.
- Installs `switchyard-dev==$version` from TestPyPI with PyPI as dependency
  fallback.
- Runs help, `switchyard`, `sy`, MCP setup, MCP smoke, and skill install checks.

The PyPI job:

- Requires `testpypi_smoke_confirmed`.
- Runs `Verify TestPyPI install before PyPI`, which installs and smokes the
  same version from TestPyPI before publishing.
- Publishes to PyPI with GitHub OIDC Trusted Publishing.
- Installs and smokes the public PyPI package after publishing.

## Release Steps

1. Make sure `main` is clean and pushed.
2. Update `src/switchyard/__init__.py`.
3. Finalize `CHANGELOG.md`.
4. Run:

```sh
python3 scripts/release_check.py
```

5. Create an annotated tag:

```sh
version="$(python3 - <<'PY'
namespace = {}
exec(open("src/switchyard/__init__.py").read(), namespace)
print(namespace["__version__"])
PY
)"
git tag -a "v$version" -m "Switchyard $version"
git push origin "v$version"
```

6. In GitHub Actions, run `Release` from that tag with
   `publish_target=testpypi`.
7. Confirm the TestPyPI install smoke passes and the TestPyPI project page
   exists.
8. In GitHub Actions, run `Release` from the same tag with
   `publish_target=pypi` and `testpypi_smoke_confirmed=true`.
9. Confirm the PyPI install smoke passes and the PyPI project page exists.

Do not move a tag after publishing to TestPyPI or PyPI. Before any package has
been published, a release-candidate tag may be moved only for release-only fixes:

```sh
git tag -f -a "v$version" -m "Switchyard $version"
git push --force origin "v$version"
```

## Troubleshooting

### `invalid-publisher`

The PyPI or TestPyPI Trusted Publisher does not match the OIDC claims. Check:

- Repository is exactly `hwennnn/switchyard`.
- Workflow is exactly `release.yml`.
- Environment is exactly `testpypi` or `pypi`.
- The workflow is running from the expected tag.

### Package Not Found After Publish

PyPI indexes can lag briefly. The workflow retries installs five times with a
15-second delay. If it still fails, open the project page and confirm the
version exists.

### Wrong Long Description

`pyproject.toml` uses `README.md` as the package readme. Update README before
publishing, then rerun:

```sh
python3 scripts/release_check.py
```

### MCP Setup Smoke Fails

Run locally:

```sh
PYTHONPATH=src python3 -m switchyard mcp smoke examples --json
```

If generated config contains `cwd`, `--cwd`, or an absolute project path, treat
that as a release blocker.
