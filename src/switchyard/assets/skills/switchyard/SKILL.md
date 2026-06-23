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
switchyard logs web --branch feature/name -n 120
```

Start or stop services only when the user asked or verification requires it:

```sh
switchyard up feature/name web api --json
switchyard checkout feature/name web --json
switchyard down --branch feature/name web --json
```

Action JSON returns an `ok` field and a JSON error envelope on failure.

## MCP Setup

For a trusted project, install the local stdio MCP server from inside the repo:

```sh
switchyard mcp install
switchyard mcp config
```

`switchyard mcp install` detects the project root and runs `codex mcp add`.
`switchyard mcp config` prints the trusted config snippet and equivalent command
with the detected project root already filled in. Keep approval enabled for
tools that create worktrees, start port forwarders, or start/stop services.

## Safety

- Treat `switchyard.toml` commands as executable project code.
- Do not edit tracked `.env` files.
- Do not kill processes that Switchyard did not launch.
- Prefer targeted service actions over broad runtime changes.
- Treat `switchyard_create` as a visible filesystem/git action.
- Treat `switchyard_checkout` as a visible local port-forwarding action.
- Treat `switchyard_uncheckout` as a visible local port-forwarding action.
- Keep local scratch/research notes out of public commits.
