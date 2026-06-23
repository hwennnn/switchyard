# Switchyard

[![CI](https://github.com/hwennnn/switchyard/actions/workflows/ci.yml/badge.svg)](https://github.com/hwennnn/switchyard/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio-5f43e9)](https://github.com/hwennnn/switchyard/blob/main/docs/MCP.md)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/hwennnn/switchyard/blob/main/LICENSE)
![Local First](https://img.shields.io/badge/local--first-no%20cloud-0f766e)
![MCP Ready](https://img.shields.io/badge/MCP-ready-111827)

Give each AI agent worktree its own local HTTP runtime: ports, URLs, logs, and agent-readable status.

Switchyard lets you run multiple AI coding agents against one repo without port fights, mystery processes, or lost terminal state. Each task gets an isolated git worktree plus its own services, branch-scoped URLs, logs, and runtime summary.

It is intentionally local-first:

- No cloud account.
- No Docker required for the default path.
- No UI lock-in.
- No public tunnels by default.
- One small `switchyard.toml`.

## Local Trust Model

- No telemetry.
- No cloud account or hosted control plane.
- Binds to loopback by default and rejects non-loopback service/proxy hosts.
- Does not expose public tunnels, LAN sharing, ngrok, or Tailscale endpoints.
- Treats `switchyard.toml` service commands as executable local project code.
- Links or copies only configured env paths, and rejects env paths outside the project/worktree.

## Status

Alpha, but usable for local agent runtime coordination.

What works today:

- Git worktree creation with env link/copy preflight.
- Dynamic loopback ports and branch-scoped `.localhost` URLs.
- Agent-readable JSON for setup, logs, runtime state, and checkout mappings.
- Stdio MCP tools, resources, and prompts with schemas, annotations, and local mutation boundaries.
- One-command Codex MCP setup using local project aliases, not path args.
- Bundled Codex skill for agent workflow guidance.

Release readiness is enforced with unit, e2e, concurrency, MCP, benchmark, and
package gates. Current benchmark guardrails include:

| Check | Gate |
| --- | --- |
| MCP initialize + doctor | median under 2500 ms |
| service startup smoke | median under 5000 ms |
| `brief --json` payload | under 12000 bytes / 3000 estimated tokens |
| source tree | under 250 KB |

The full release gate also builds and install-smokes the wheel, and keeps the
wheel artifact under 350 KB.

From a repository checkout:

```sh
python3 scripts/benchmark.py --runs 3
python3 scripts/release_check.py
```

Reference docs:

- [API reference](https://github.com/hwennnn/switchyard/blob/main/docs/API.md)
- [MCP guide](https://github.com/hwennnn/switchyard/blob/main/docs/MCP.md)
- [Local publishing and CI/CD guide](https://github.com/hwennnn/switchyard/blob/main/docs/PUBLISHING_LOCAL.md)

To smoke path-free MCP setup from a project that has `switchyard.toml`:

```sh
switchyard mcp smoke --json
```

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
switchyard logs web --branch feature/login --json
switchyard mcp
```

Example output:

```json
{
  "configured_services": ["api", "web"],
  "services": [
    {
      "service": "web",
      "status": "running",
      "url": "http://web.feature-login.entropic.localhost:7331",
      "port": 41000
    }
  ],
  "checkouts": [],
  "env_warnings": [],
  "recent_errors": []
}
```

## Install

Install the CLI from PyPI:

```sh
pipx install switchyard-dev
```

Or with pip:

```sh
python3 -m pip install switchyard-dev
```

The package distribution name is `switchyard-dev`; the installed commands are
`switchyard` and `sy`.

For source development:

```sh
git clone https://github.com/hwennnn/switchyard.git
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
switchyard init --dry-run
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
switchyard logs web --branch feature/login --json
```

`brief --json` and `switchyard://project/brief` include
`configured_services`, so agents can discover valid service names before
starting or querying runtime state. They also include `env_warnings` for
missing configured env link/copy sources, so agents can catch setup gaps before
creating a worktree.

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

When launched from a project or any child directory, `switchyard mcp` pins
itself to the nearest `switchyard.toml`. You should not need to hand-write a
project path argument for normal setup.
When launched from a Switchyard-registered worktree, it keeps the parent
project as the server boundary while defaulting requests to that worktree's
branch.

For Codex, run the installer from inside the project. It detects the real
project root once, stores it as a local Switchyard alias, and writes MCP config
without making you type or maintain a path:

```sh
switchyard mcp install
```

The generated Codex block uses a stable project alias:

```toml
args = ["mcp", "--project", "name"]
```

If the `switchyard` executable is not visible to the current shell, the helper
prints a commented fallback that launches the current Python interpreter with
`args = ["-m", "switchyard", "mcp", "--project", "name"]`. Either way, the
project is resolved through the local alias, and the generated block does not
emit `cwd`, `--cwd`, or an absolute project path.
If `SWITCHYARD_HOME` is set during setup, the generated block includes an
`[mcp_servers.name.env]` table so the MCP server can find the same local alias
state when Codex launches it later.

To inspect the config first, use the setup helper. It registers the same local
alias and prints ready-to-paste TOML:

```sh
switchyard mcp config
switchyard mcp config --json
switchyard mcp install --dry-run --json
```

Use `--json` when an agent or script needs the generated TOML, launch command,
alias state, or setup error envelope without scraping prose.

To see registered aliases:

```sh
switchyard mcp projects --json
```

The JSON includes `home` and `state_path` so agents can tell which local
Switchyard registry they are inspecting.

Use `--name` if you want a different MCP server name. If an alias already
points at another project, Switchyard refuses to repoint it unless you pass
`--force`. Start from the checkout you are configuring so setup stays path-free:

```sh
switchyard mcp install --name switchyard-entropic
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
switchyard_checkout
switchyard_uncheckout
switchyard_down
```

Agents should usually read `switchyard://project/brief` first, or call
`switchyard_brief` when resources are unavailable. Then use `switchyard_where`
or `switchyard_logs` for focused follow-up. `switchyard_create`,
`switchyard_up`, `switchyard_checkout`, `switchyard_uncheckout`, and
`switchyard_down` change local state, so MCP clients should keep user approval
enabled for them.
Switchyard marks read-only discovery tools and local mutation tools with MCP
tool annotations so clients can present safer approval UI.

MCP clients that prefer resources can read stable, read-only context first:

```txt
switchyard://project/brief
switchyard://project/doctor
switchyard://agent/guide
```

These MCP resources do not initialize Switchyard state.

MCP clients that expose prompts can offer ready-made agent workflows:

```txt
switchyard_runtime_handoff
switchyard_branch_runtime
```

Shell-only agents can run `switchyard brief --json` from a registered worktree;
Switchyard resolves the parent project and current branch automatically.

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
# Optional: keep Switchyard-created worktrees inside the repo.
# worktree_root = ".worktrees/switchyard"

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
command = "npm run dev -- --port {port}"
port = 3000

[services.api]
command = "npm run api -- --port {port}"
port = 8080
```

See the
[examples directory](https://github.com/hwennnn/switchyard/tree/main/examples)
for fuller configs, including a multi-service app with Docker backing services
and peer placeholders.

Desired ports are preferences. If `3000` is busy, Switchyard allocates a free port and injects:

```sh
PORT
HOST
CANONICAL_PORT
SWITCHYARD_URL
SWITCHYARD_BRANCH
SWITCHYARD_SERVICE
SWITCHYARD_WEB_URL
SWITCHYARD_WEB_PORT
SWITCHYARD_API_URL
SWITCHYARD_API_PORT
```

Service commands should either honor `PORT`/`HOST` or include placeholders such
as `{port}` and `{host}`. Otherwise the process may ignore Switchyard's assigned
port and bind its own default.

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
{web_url}
{web_port}
{api_url}
{api_port}
```

Peer tokens are based on service names. Hyphens are available as underscores,
so a `db-main` service can be referenced as `{db_main_port}` and
`{db_main_url}`.

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
switchyard init [--dry-run] [--json]
switchyard doctor [--json]
switchyard create <branch> [--json]
switchyard list [--json]
switchyard up [branch] [services...] [--json]
switchyard down [--branch branch] [services...] [--json]
switchyard checkout <branch> [services...] [--json]
switchyard uncheckout [--branch branch] [services...] [--json]
switchyard status [--json]
switchyard logs [service] [--branch branch] [--json]
switchyard open <service> [branch]
switchyard where <service> [branch] [--json]
switchyard brief [branch] [--json]
switchyard mcp [--project name]
switchyard mcp config [--name name] [--force] [--json]
switchyard mcp install [--name name] [--dry-run] [--force] [--json]
switchyard mcp projects [--json]
switchyard mcp smoke [project] [--nested path] [--name name] [--json]
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
- Rejects proxy and service hosts outside loopback addresses.
- Stops only recorded service PIDs whose command still matches the registry.
- Scopes stop actions to the current registered worktree branch when run inside one.
- Does not replace existing env targets by default; `--force-env` is explicit.
- Rejects env paths outside the project/worktree.
- Keeps generated state outside the repo by default.
- No public sharing, ngrok, Tailscale, or LAN exposure in v0.

## Current Limits

- Built-in proxy is HTTP, not TLS.
- Built-in proxy is not a full WebSocket/HMR replacement yet.
- Canonical checkout forwards HTTP only.
- Docker Compose, Caddy, Portless, and Worktrunk adapters are planned, not shipped.
