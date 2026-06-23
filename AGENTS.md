# Switchyard Agent Guide

Switchyard is a local runtime control plane for parallel agent worktrees.

## Default Workflow

Use compact state before broad shell exploration:

```sh
switchyard brief --json
switchyard status --json
switchyard where web feature/name --json
switchyard logs web --branch feature/name -n 120
```

For MCP clients, prefer:

```txt
switchyard_brief -> switchyard_where -> switchyard_logs
```

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
- Keep MCP approval enabled for `switchyard_up` and `switchyard_down`.
- Keep local-only research, scratch harnesses, and competitive notes out of
  public commits.

## Verification

Before committing Switchyard changes:

```sh
python3 -m compileall src
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/e2e_smoke.py
```
