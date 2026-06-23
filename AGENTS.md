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

Use compact state before broad shell exploration:

```sh
switchyard brief --json
switchyard status --json
switchyard where web feature/name --json
switchyard logs web --branch feature/name -n 120 --json
```

For MCP clients, prefer:

```txt
switchyard_brief -> switchyard_where -> switchyard_logs
```

Use `switchyard_create` only when the user asked for a missing branch runtime.

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

- Do not edit tracked `.env` files.
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
