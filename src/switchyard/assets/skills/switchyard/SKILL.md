---
name: switchyard
description: Use when Codex is working in a repository that uses Switchyard, or when the user asks to inspect, start, stop, debug, or configure local runtimes for parallel agent worktrees, localhost port conflicts, service URLs, logs, MCP setup, or agent-readable runtime state.
---

# Switchyard

## Overview

Switchyard gives every agent worktree its own local runtime identity: services,
dynamic ports, stable URLs, logs, changed files, and recent errors. Use its
compact state before broad shell exploration.

## First Move

If the project has no `switchyard.toml`, preview first-run setup without writing
files:

```sh
switchyard init --dry-run --json
```

Prefer the smallest state query that answers the question:

```sh
switchyard doctor --json
switchyard brief --json
```

Read `env_warnings` from `switchyard doctor --json` or `switchyard_doctor`
before creating worktrees; missing env sources should be fixed or reported.

If MCP tools are available, use this order:

1. `switchyard_brief`
2. `switchyard_where`
3. `switchyard_logs`
4. `switchyard_create` only when a missing branch runtime is needed
5. `switchyard_up`, `switchyard_checkout`, `switchyard_uncheckout`, or `switchyard_down` only when runtime changes are needed

MCP tool annotations mark discovery tools as read-only, `switchyard_up` as a
conservative project-command action, and runtime tools as mutations; still keep
user approval enabled for mutation tools.

## CLI Workflow

Inspect state:

```sh
switchyard list --json
switchyard status --json
switchyard where web feature/name --json
switchyard logs web --branch feature/name -n 120 --json
```

Start or stop services only when the user asked or verification requires it:

```sh
switchyard up feature/name web api --json
switchyard checkout feature/name web --json
switchyard down --branch feature/name web --json
```

Action JSON returns an `ok` field and a JSON error envelope on failure.

In `switchyard.toml`, service commands can reference their own `{port}` and
peer placeholders such as `{api_url}`, `{api_port}`, or `{db_main_port}` for a
hyphenated `db-main` service.

## MCP Setup

For a trusted project, install the local stdio MCP server from inside the repo:

```sh
switchyard mcp install
switchyard mcp config
```

If the server is launched directly, run `switchyard mcp` from the project or any
child directory; it resolves the nearest `switchyard.toml` automatically. Avoid
hard-coded project path args in normal setup.

`switchyard mcp install` detects the project root, registers a local project alias,
and writes the full server block to `~/.codex/config.toml`.
`switchyard mcp config` registers the same alias and prints the trusted config
snippet with `args = ["mcp", "--project", "name"]`, keeping setup free of
hard-coded project paths. Keep approval enabled for tools that create
worktrees, start port forwarders, or start/stop services.
Use `switchyard mcp projects --json` to inspect registered aliases.

## Safety

- Treat `switchyard.toml` commands as executable project code.
- Do not edit tracked `.env` files.
- Do not kill processes that Switchyard did not launch.
- Prefer targeted service actions over broad runtime changes.
- Treat `switchyard_create` as a visible filesystem/git action.
- Treat `switchyard_checkout` as a visible local port-forwarding action.
- Treat `switchyard_uncheckout` as a visible local port-forwarding action.
- When calling MCP stop tools from a registered worktree `cwd`, omit `branch`
  only when you intend to target that worktree's branch.
- Keep local scratch/research notes out of public commits.
