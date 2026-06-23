# API Reference

Switchyard exposes three public surfaces:

1. A local CLI: `switchyard` and `sy`.
2. Machine-readable CLI JSON for shell agents.
3. A stdio MCP server for agent clients.

The Python modules under `src/switchyard/` are implementation modules, not a
stable library API. Treat the CLI, JSON outputs, MCP resources, MCP tools, and
`switchyard.toml` as the supported integration contract.

## CLI

All commands run from a project containing `switchyard.toml`, a child directory
of that project, or a Switchyard-registered worktree unless noted.

```txt
switchyard init [--force] [--dry-run] [--json]
switchyard doctor [--json]
switchyard create <branch> [--base ref] [--path path] [--force-env] [--json]
switchyard list [--json]
switchyard up [branch] [services...] [--json]
switchyard down [--branch branch] [services...] [--json]
switchyard checkout <branch> [services...] [--json]
switchyard uncheckout [--branch branch] [services...] [--json]
switchyard status [--branch branch] [--json]
switchyard logs [service] [--branch branch] [-n lines] [-f] [--json]
switchyard open <service> [branch] [--print-only]
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

`sy` is an alias for `switchyard`.

## JSON Outputs

JSON commands return stable object envelopes so agents do not need to scrape
human text.

### `doctor --json`

```json
{
  "ok": true,
  "switchyard": "0.1.0",
  "home": "/Users/me/.switchyard",
  "project": {
    "name": "demo",
    "root": "/repo/demo",
    "config": "/repo/demo/switchyard.toml"
  },
  "proxy": {
    "host": "127.0.0.1",
    "port": 7331,
    "tld": "localhost"
  },
  "services": ["web"],
  "env_warnings": []
}
```

### `list --json`

```json
{
  "worktrees": [
    {
      "branch": "feature/demo",
      "slug": "feature-demo",
      "path": "/repo/demo/.worktrees/feature-demo",
      "updated_at": "2026-06-23T00:00:00Z"
    }
  ]
}
```

### `status --json`

```json
{
  "services": [
    {
      "service": "web",
      "branch": "feature/demo",
      "status": "running",
      "url": "http://web.feature-demo.demo.localhost:7331",
      "port": 41000,
      "pid": 12345,
      "log_file": "/Users/me/.switchyard/logs/demo/feature-demo/web.log",
      "recent_errors": []
    }
  ]
}
```

### `brief --json`

Use this first when an agent needs compact project/runtime context.

```json
{
  "project": "demo",
  "project_root": "/repo/demo",
  "branch": "feature/demo",
  "configured_services": ["web"],
  "services": [],
  "checkouts": [],
  "changed_files": [],
  "env_warnings": [],
  "recent_errors": []
}
```

### `where --json`

Returns one service record with URL, port, PID, log path, and recent errors.

### `logs --json`

```json
{
  "logs": [
    {
      "service": "web",
      "branch": "feature/demo",
      "log_file": "/Users/me/.switchyard/logs/demo/feature-demo/web.log",
      "lines": ["..."]
    }
  ]
}
```

### Setup Error Envelopes

Setup commands that support `--json` return `ok: false` instead of printing
only human stderr when they can represent the error safely:

```json
{
  "ok": false,
  "error": "could not find switchyard.toml from /repo/demo"
}
```

## MCP Server

Start directly from a project or child directory:

```sh
switchyard mcp
```

For Codex MCP setup, run from inside the project:

```sh
switchyard mcp install
```

Generated MCP client config uses a local project alias:

```toml
args = ["mcp", "--project", "name"]
```

Generated config should not contain `cwd`, `--cwd`, or an absolute project
path. Use `switchyard mcp projects --json` to inspect local aliases.

## MCP Resources

| URI | MIME type | Description |
| --- | --- | --- |
| `switchyard://project/brief` | `application/json` | Compact runtime context: configured services, current services, checkouts, env warnings, changed files, recent errors. |
| `switchyard://project/doctor` | `application/json` | Project setup, Switchyard home, proxy config, service names, env warnings. |
| `switchyard://agent/guide` | `text/markdown` | Short agent workflow guide. |

Resources are read-only and do not initialize Switchyard state.

## MCP Prompts

| Prompt | Arguments | Description |
| --- | --- | --- |
| `switchyard_runtime_handoff` | none | Read-only starter workflow that tells an agent to inspect the project brief first. |
| `switchyard_branch_runtime` | `branch` required, `services` optional | Read-only branch-runtime workflow for creating or starting a branch runtime. |

Prompts are templates. Runtime mutations still happen only through MCP tools or
CLI commands.

## MCP Tools

| Tool | Read-only | Mutates local state | Purpose |
| --- | --- | --- | --- |
| `switchyard_doctor` | yes | no | Return project setup, proxy, service names, and env warnings. |
| `switchyard_status` | yes | no | Return registered service state. |
| `switchyard_list` | yes | no | Return registered worktrees. |
| `switchyard_brief` | yes | no | Return compact agent runtime context. |
| `switchyard_where` | yes | no | Return one service URL, port, PID, and log path. |
| `switchyard_logs` | yes | no | Return recent log lines. |
| `switchyard_create` | no | yes | Create a git worktree and sync configured env files. |
| `switchyard_up` | no | yes | Start configured project service commands. |
| `switchyard_checkout` | no | yes | Start canonical-port HTTP forwarders. |
| `switchyard_uncheckout` | no | yes | Stop canonical-port HTTP forwarders. |
| `switchyard_down` | no | yes | Stop Switchyard-managed service processes. |

Common tool argument:

- `cwd`: optional path under the MCP server project root, or a registered
  worktree path. Defaults to the server launch cwd.

Branch behavior:

- From a registered worktree, omitted branch arguments default to that
  worktree's branch for scoped operations.
- From the project root, omitted branch filters include all matching
  Switchyard-managed state.

Keep MCP client approval enabled for mutation tools.

## `switchyard.toml`

Minimal config:

```toml
[project]
name = "demo"

[services.web]
command = "npm run dev -- --port {port}"
port = 3000
```

Useful sections:

```toml
[env]
link = [".env.local"]
copy = ["secrets/dev.env"]

[proxy]
host = "127.0.0.1"
port = 7331
tld = "localhost"

[ports]
start = 41000
end = 41999
```

Service command placeholders:

- `{port}` and `{host}` expand to the assigned loopback bind values.
- `{service_url}` and `{service_port}` expand peer services, such as
  `{api_url}` or `{db_main_port}`.

Service environment variables:

- `PORT`
- `HOST`
- `SWITCHYARD_SERVICE`
- `SWITCHYARD_BRANCH`
- `SWITCHYARD_PROJECT`
- `SWITCHYARD_URL`
- `SWITCHYARD_<SERVICE>_URL`
- `SWITCHYARD_<SERVICE>_PORT`

Env sync rules:

- `env.link` creates symlinks.
- `env.copy` copies files.
- Env sources must stay inside the project/worktree.
- Existing env targets are not replaced unless `--force-env` is explicit.

## Local State

Default state lives under `~/.switchyard`:

```txt
~/.switchyard/state.json
~/.switchyard/logs/
~/.switchyard/worktrees/
```

Override it with:

```sh
SWITCHYARD_HOME=/tmp/switchyard switchyard status
```

MCP setup preserves `SWITCHYARD_HOME` in generated client config when it is set
during setup.

## Compatibility Fixtures

MCP compatibility requests live in `tests/fixtures/mcp_*.jsonl`.
`scripts/release_check.py` replays those fixtures and validates CLI JSON,
MCP resources, MCP prompts, package build/install, benchmarks, and publish
workflow guardrails.
