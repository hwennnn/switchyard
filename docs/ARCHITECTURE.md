# Architecture

Switchyard has five small pieces:

1. CLI
2. Project config
3. Registry
4. Process runner
5. Local proxy

## CLI

The CLI is `switchyard` and `sy`.

It is implemented with Python stdlib `argparse` so the runtime has no mandatory package dependencies.

## Project Config

`switchyard.toml` describes the local runtime:

- Project name.
- Env files to link or copy.
- Proxy host/port/TLD.
- Port allocation range.
- Services and commands.

Service commands are parsed with shell-like quoting and executed without a
shell. Put pipes, redirects, `&&`, or other shell behavior in a script and call
that script from `command`.

## Registry

The registry is JSON at:

```txt
~/.switchyard/state.json
```

It records:

- Known projects.
- Worktree paths.
- Running service PIDs.
- Dynamic ports.
- Stable hostnames.
- Log paths.
- Proxy PIDs.
- Canonical checkout forwarders.

This file is deliberately easy for agents and other tools to read.

## Process Runner

`switchyard up` starts services with:

- `start_new_session=True`, so process groups can be stopped safely.
- stdout/stderr appended to per-service log files.
- Dynamic `PORT` and Switchyard metadata env vars.

Switchyard only stops processes it launched and recorded.

## Local Proxy

The built-in proxy listens on one local port, usually `127.0.0.1:7331`.

It routes by Host header:

```txt
web.feature-login.entropic.localhost:7331 -> 127.0.0.1:41000
```

The proxy is intentionally simple in v0:

- HTTP only.
- No TLS.
- Not a full WebSocket proxy yet.

The adapter boundary should allow future backends:

- Portless
- Caddy
- Traefik
- Nginx

## Canonical Checkout

`switchyard checkout <branch>` starts fixed-target HTTP forwarders for services that had to move away from their desired canonical ports.

Example:

```txt
127.0.0.1:3000 -> 127.0.0.1:41000
```

This is useful for tools that hard-code `localhost:3000`.

## Adapter Roadmap

Switchyard should integrate instead of replacing good tools:

- Worktrunk adapter for worktree creation.
- Portless or Caddy adapter for production-grade local URL/TLS/WebSocket routing.
- Docker Compose adapter for container stacks.
- process-compose or Overmind adapter for advanced process supervision.
- `socat` adapter for raw TCP canonical port checkout.

## MCP Compatibility

MCP client compatibility fixtures live in `tests/fixtures/mcp_*.jsonl`.
`scripts/release_check.py` replays those JSON-RPC request streams against the
stdio server so tools, resources, prompts, validation errors, and read-only
state behavior stay compatible as the server evolves.
