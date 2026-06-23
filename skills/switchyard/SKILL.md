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

Prefer the smallest state query that answers the question:

```sh
switchyard brief --json
```

If MCP tools are available, use this order:

1. `switchyard_brief`
2. `switchyard_where`
3. `switchyard_logs`
4. `switchyard_up` or `switchyard_down` only when runtime changes are needed

## CLI Workflow

Inspect state:

```sh
switchyard status --json
switchyard where web feature/name --json
switchyard logs web --branch feature/name -n 120
```

Start or stop services only when the user asked or verification requires it:

```sh
switchyard up feature/name web api
switchyard down --branch feature/name web
```

## MCP Setup

For a trusted project, configure a local stdio MCP server:

```toml
[mcp_servers.switchyard]
command = "switchyard"
args = ["mcp", "--cwd", "/path/to/project"]
default_tools_approval_mode = "prompt"
```

Keep approval enabled for tools that start or stop services.

## Safety

- Treat `switchyard.toml` commands as executable project code.
- Do not edit tracked `.env` files.
- Do not kill processes that Switchyard did not launch.
- Prefer targeted service actions over broad runtime changes.
- Keep local scratch/research notes out of public commits.
