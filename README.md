# Switchyard

[![CI](https://github.com/hwennnn/switchyard/actions/workflows/ci.yml/badge.svg)](https://github.com/hwennnn/switchyard/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio-5f43e9)](docs/MCP.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Local First](https://img.shields.io/badge/local--first-no%20cloud-0f766e)
![MCP Ready](https://img.shields.io/badge/MCP-ready-111827)

Run every AI coding task in its own local runtime, with isolated ports, logs, URLs, and agent-readable status.

Switchyard lets you run multiple AI coding agents against one repo without port fights, mystery processes, or lost terminal state. Each task gets an isolated git worktree plus its own services, URLs, logs, and runtime summary.

It is intentionally local-first:

- No cloud account.
- No Docker required for the default path.
- No UI lock-in.
- No public tunnels by default.
- One small `switchyard.toml`.

## Why

Git worktrees isolate code, but they do not isolate your local runtime. If two worktrees both want `localhost:3000`, `localhost:8080`, `.env.local`, and the same terminal scrollback, you are back to manual bookkeeping.

Without Switchyard, parallel agent work means babysitting ports, terminals, env files, and logs. With Switchyard, agents can ask the runtime where everything is.

Switchyard gives each branch a named runtime:

```txt
web.feature-login.entropic.localhost:7331 -> 127.0.0.1:41000
api.feature-login.entropic.localhost:7331 -> 127.0.0.1:41001
```

Agents can ask for the current state directly:

```sh
switchyard brief --json
switchyard where web feature/login --json
switchyard logs web --branch feature/login
switchyard mcp
```

Example output:

```json
{
  "services": [
    {
      "service": "web",
      "status": "running",
      "url": "http://web.feature-login.entropic.localhost:7331",
      "port": 41000
    }
  ],
  "recent_errors": []
}
```

## Install

Switchyard is pre-release. The PyPI package name is `switchyard-dev`; the installed commands are `switchyard` and `sy`.

Once published:

```sh
pipx install switchyard-dev
# or
uv tool install switchyard-dev
```

From source:

```sh
cd switchyard
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Or run from source:

```sh
PYTHONPATH=src python3 -m switchyard --help
```

## Quick Start

Inside a git repository:

```sh
switchyard init
switchyard create feature/login
switchyard up feature/login
switchyard open web feature/login
```

Typical `up` output:

```txt
started proxy on 127.0.0.1:7331
started web on :41000 -> http://web.feature-login.entropic.localhost:7331
```

View state:

```sh
switchyard doctor --json
switchyard status
switchyard brief
switchyard logs web --branch feature/login
```

Stop it:

```sh
switchyard down --branch feature/login
switchyard proxy stop
```

## MCP Setup

Switchyard ships a stdio MCP server for AI agents:

```sh
switchyard mcp
```

For Codex, run the setup helper from the project. It prints TOML and the
matching `codex mcp add` command with the real project root already filled in:

```sh
switchyard mcp config
```

Use `--name` if you want a different MCP server name, or `--cwd` when generating
config for another checkout:

```sh
switchyard mcp config --name switchyard-entropic
```

The MCP server exposes agent-friendly tools:

```txt
switchyard_doctor
switchyard_create
switchyard_list
switchyard_status
switchyard_brief
switchyard_where
switchyard_logs
switchyard_up
switchyard_down
```

Agents should usually call `switchyard_brief` first, then `switchyard_where` or
`switchyard_logs` for focused follow-up. `switchyard_create`, `switchyard_up`,
and `switchyard_down` change local state, so MCP clients should keep user
approval enabled for them.

## Agent Skill

Switchyard ships a Codex skill for agents that prefer skill-guided workflows:

```sh
switchyard skill install
```

Use it with prompts like:

```txt
Use $switchyard to inspect this project's local agent runtime.
```

## Config

```toml
[project]
name = "entropic"

[env]
link = [".env", ".env.local"]
copy = []

[proxy]
host = "127.0.0.1"
port = 7331
tld = "localhost"

[ports]
start = 41000
end = 49999

[services.web]
command = "npm run dev"
port = 3000

[services.api]
command = "npm run api -- --port {port}"
port = 8080
```

Desired ports are preferences. If `3000` is busy, Switchyard allocates a free port and injects:

```sh
PORT
HOST
CANONICAL_PORT
SWITCHYARD_URL
SWITCHYARD_BRANCH
SWITCHYARD_SERVICE
SWITCHYARD_WEB_URL
SWITCHYARD_API_URL
```

Commands may use tokens:

```txt
{port}
{host}
{url}
{service}
{branch}
{branch_slug}
{project}
{project_slug}
```

## When A Tool Requires localhost:3000

Some dev tools refuse dynamic ports. Checkout maps one branch back onto the canonical port while the rest stay isolated:

```sh
switchyard checkout feature/login web
```

Example:

```txt
localhost:3000 -> web.feature-login.entropic.localhost:7331 -> 127.0.0.1:41000
```

Undo:

```sh
switchyard uncheckout --branch feature/login web
```

Today, checkout is HTTP-focused. Raw TCP services such as Postgres and Redis are not yet managed by the built-in forwarder.

## Commands

```txt
switchyard init
switchyard doctor [--json]
switchyard create <branch>
switchyard list
switchyard up [branch] [services...]
switchyard down [--branch branch] [services...]
switchyard checkout <branch> [services...]
switchyard uncheckout [--branch branch] [services...]
switchyard status [--json]
switchyard logs [service] [--branch branch]
switchyard open <service> [branch]
switchyard where <service> [branch] [--json]
switchyard brief [branch] [--json]
switchyard mcp [--cwd path]
switchyard mcp config [--cwd path] [--name name]
switchyard skill show
switchyard skill install [--target dir] [--force]
switchyard proxy stop
```

## State And Logs

By default, Switchyard writes machine state to:

```txt
~/.switchyard/state.json
~/.switchyard/logs/
~/.switchyard/worktrees/
```

Override with:

```sh
SWITCHYARD_HOME=/tmp/switchyard switchyard status
```

## Safety Defaults

- Binds to `127.0.0.1` by default.
- Stops only recorded service PIDs whose command still matches the registry.
- Does not edit tracked `.env` files.
- Rejects env paths outside the project/worktree.
- Keeps generated state outside the repo by default.
- No public sharing, ngrok, Tailscale, or LAN exposure in v0.

## Current Limits

- Built-in proxy is HTTP, not TLS.
- Built-in proxy is not a full WebSocket/HMR replacement yet.
- Canonical checkout forwards HTTP only.
- Docker Compose, Caddy, Portless, and Worktrunk adapters are planned, not shipped.
