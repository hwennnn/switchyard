# Switchyard Agent Guide

This file is for coding agents working on Switchyard itself.

Switchyard gives agents a compact runtime map before they touch the shell:
services, URLs, ports, logs, changed files, and recent errors.

## Default Workflow

For a repository that has not been initialized, preview the generated config
without writing files:

```sh
switchyard init --dry-run --json
```

The Switchyard source checkout does not ship a root `switchyard.toml`; use the
release gate below for this repo. In target projects that do have
`switchyard.toml`, use compact state before broad shell exploration:

```sh
switchyard brief --json
switchyard status --json
switchyard where web feature/name --json
switchyard logs web --branch feature/name -n 120 --json
```

For MCP clients, prefer:

```txt
switchyard://project/brief -> switchyard_where -> switchyard_logs
```

Use `configured_services` from the brief to choose valid service names. If MCP
resources are unavailable, call `switchyard_brief` first. If MCP prompts
are available, `switchyard_runtime_handoff` starts the same read-only workflow
and `switchyard_branch_runtime` guides branch runtime setup.

Use `switchyard_create` only when the user asked for a missing branch runtime.

## MCP Setup

For a trusted checkout, install or inspect Codex MCP setup from inside the
repository:

```sh
switchyard mcp install
switchyard mcp config --json
switchyard mcp install --dry-run --json
```

The generated config uses a local project alias with
`args = ["mcp", "--project", "name"]`. Do not hand-write `cwd`, `--cwd`, an
absolute project path, or placeholder project paths in MCP client config.
If `SWITCHYARD_HOME` is set, setup JSON/config should include
`[mcp_servers.name.env]` so the alias remains resolvable when the MCP client
launches later.
Use `switchyard mcp projects --json` to inspect local aliases and confirm the
`home`/`state_path` used for alias lookup.

## Runtime Actions

Starting and stopping services are visible local actions:

```sh
switchyard up feature/name
switchyard down --branch feature/name
```

Only run them when the user asked for runtime changes or when verification
requires it. Prefer targeted services when possible:

```sh
switchyard up feature/name web api
switchyard down --branch feature/name web
```

## Safety

- Do not replace existing env targets unless the user explicitly asked for
  `--force-env`; never add tracked secret files.
- Do not kill processes that Switchyard did not launch.
- Treat service commands in `switchyard.toml` as project code.
- Keep MCP approval enabled for `switchyard_create`, `switchyard_up`, `switchyard_checkout`, `switchyard_uncheckout`, and `switchyard_down`.
- Keep local-only research, scratch harnesses, and competitive notes out of
  public commits.

## Verification

Before committing Switchyard changes:

```sh
python3 -m compileall src
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/e2e_smoke.py
python3 scripts/release_check.py --skip-package
```
