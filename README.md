# Switchyard

[![CI](https://github.com/hwennnn/switchyard/actions/workflows/ci.yml/badge.svg)](https://github.com/hwennnn/switchyard/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio-5f43e9)](docs/MCP.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Local First](https://img.shields.io/badge/local--first-no%20cloud-0f766e)
![Agent Native](https://img.shields.io/badge/agent--native-brief%20%2B%20MCP-111827)

Local runtimes for parallel agent worktrees.

Switchyard is a lightweight local control plane for developers running multiple AI coding agents against the same repository. Each task gets an isolated git worktree, its own service processes, dynamic ports, stable local URLs, logs, status, and an agent-readable summary.

It is intentionally local-first:

- No cloud account.
- No Docker required for the default path.
- No UI lock-in.
- No public tunnels by default.
- One small `switchyard.toml`.

## Why

Git worktrees isolate code, but they do not isolate your local runtime. If two worktrees both want `localhost:3000`, `localhost:8080`, `.env.local`, and the same terminal scrollback, you are back to manual bookkeeping.

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

## Install For Development

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

View state:

```sh
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
switchyard mcp --cwd /path/to/project
```

For Codex, add a project-scoped `.codex/config.toml` in a trusted project:

```toml
[mcp_servers.switchyard]
command = "switchyard"
args = ["mcp", "--cwd", "/path/to/project"]
startup_timeout_sec = 10
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

Or add it with the Codex CLI:

```sh
codex mcp add switchyard -- switchyard mcp --cwd /path/to/project
```

The MCP server exposes agent-friendly tools:

```txt
switchyard_doctor
switchyard_status
switchyard_brief
switchyard_where
switchyard_logs
switchyard_up
switchyard_down
```

Agents should usually call `switchyard_brief` first, then `switchyard_where` or
`switchyard_logs` for focused follow-up. `switchyard_up` and `switchyard_down`
start or stop local processes, so MCP clients should keep user approval enabled.

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

## Canonical Port Checkout

Some tools hard-code `localhost:3000`. If Switchyard had to move a service to a dynamic port, you can map one branch back to canonical ports:

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

The built-in checkout forwarder is HTTP-focused. Raw TCP services like Postgres/Redis should use a future `socat`/Compose adapter.

## Commands

```txt
switchyard init
switchyard doctor
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
- Kills only PIDs it launched and recorded.
- Does not edit tracked `.env` files.
- Keeps generated state outside the repo by default.
- No public sharing, ngrok, Tailscale, or LAN exposure in v0.

## Current Limits

- Built-in proxy is HTTP, not TLS.
- Built-in proxy is not a full WebSocket/HMR replacement yet.
- Canonical checkout forwards HTTP only.
- Docker Compose, Caddy, Portless, and Worktrunk adapters are planned, not shipped.
