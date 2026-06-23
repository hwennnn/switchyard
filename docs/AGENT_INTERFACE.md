# How Agents Use Switchyard

Switchyard is designed so agents do not need to infer local runtime state from terminal scrollback.

## MCP Server

Run Switchyard as a local stdio MCP server:

```sh
switchyard mcp
```

When launched from a project or any child directory, `switchyard mcp` resolves
the nearest `switchyard.toml` automatically. Avoid hard-coded
project path args in normal MCP setup.

For Codex, generate project-specific setup text from inside the repository:

```sh
switchyard mcp install
switchyard mcp config
```

`switchyard mcp install` detects the root and writes the full server block to
`~/.codex/config.toml`. `switchyard mcp config` prints a trusted config snippet
using a local project alias:

```toml
args = ["mcp", "--project", "name"]
```

The alias keeps MCP client setup free of hand-written project paths.
Use `switchyard mcp projects --json` to inspect registered aliases.

Clients that support MCP resources can read stable, read-only context before
choosing a tool:

```txt
switchyard://project/brief
switchyard://project/doctor
switchyard://agent/guide
```

Reading these resources does not initialize Switchyard state.

Clients that support MCP prompts can expose ready-made workflows:

```txt
switchyard_runtime_handoff
switchyard_branch_runtime
```

Prompts are read-only templates. Runtime changes still happen only through the
mutation tools.

## Codex Skill

Install the bundled skill when an agent benefits from Switchyard-specific
workflow guidance:

```sh
switchyard skill install
```

Available MCP tools:

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

Use `switchyard_brief` before reading logs or guessing URLs. Treat
`switchyard_create`, `switchyard_up`, `switchyard_checkout`,
`switchyard_uncheckout`, and `switchyard_down` as visible local actions because
they create worktrees, start services, or change port mappings.
When MCP `switchyard_uncheckout` or `switchyard_down` runs with a registered
worktree `cwd`, an omitted branch means that worktree's branch. From the project
root, an omitted branch still means all matching Switchyard-managed runtime
state.

## Best Commands For Agents

Use:

```sh
switchyard init --dry-run --json
switchyard doctor --json
switchyard list --json
```

When checking setup, previewing first-run config, or reporting why a project is
not initialized. `doctor --json` includes `env_warnings` for missing configured
env link/copy sources.

Use:

```sh
switchyard brief --json
```

For a compact overview. When run inside a Switchyard-registered worktree, the
CLI uses that worktree's branch and parent project automatically:

```json
{
  "project": "entropic",
  "branch": "feature/login",
  "services": [
    {
      "service": "web",
      "status": "running",
      "url": "http://web.feature-login.entropic.localhost:7331",
      "port": 41000,
      "log_file": "/Users/me/.switchyard/logs/entropic/feature-login/web.log"
    }
  ],
  "checkouts": [
    {
      "service": "web",
      "status": "running",
      "listen_host": "127.0.0.1",
      "listen_port": 3000,
      "target_host": "127.0.0.1",
      "target_port": 41000
    }
  ],
  "changed_files": [" M src/app.tsx"],
  "recent_errors": []
}
```

Use:

```sh
switchyard where web feature/login --json
```

When you need one service.

Use:

```sh
switchyard logs web --branch feature/login -n 120 --json
```

When debugging.

Log JSON returns each selected service with `service`, `branch`, `log_file`, and
an array of tail `lines`.

Use action JSON when a shell-only agent needs to report what it changed:

```sh
switchyard up feature/login web --json
switchyard checkout feature/login web --json
switchyard down --branch feature/login web --json
```

Action JSON returns `ok`, `action`, requested services, messages, and a JSON
error envelope on failure.

When `down` or `uncheckout` run inside a registered worktree without an
explicit branch, Switchyard scopes the action to that worktree's branch. From
the project root, omitting the branch still means all matching Switchyard state.

MCP clients can also read tool annotations: discovery tools are read-only,
`switchyard_up` is conservative because it runs configured project commands,
and worktree/process/checkout tools are marked as mutations.

## Token-Saving Workflow

Instead of repeatedly running:

- `git status`
- `lsof -i`
- `ps`
- `cat` on logs
- package manager inspection
- browser URL guessing

Prefer:

```sh
switchyard brief --json
```

Then inspect only the log file or service that looks relevant.

## Stable Env Vars

Each service receives:

```txt
SWITCHYARD=1
SWITCHYARD_PROJECT
SWITCHYARD_PROJECT_SLUG
SWITCHYARD_BRANCH
SWITCHYARD_BRANCH_SLUG
SWITCHYARD_SERVICE
SWITCHYARD_PORT
SWITCHYARD_URL
```

For peer services:

```txt
SWITCHYARD_WEB_URL
SWITCHYARD_WEB_PORT
SWITCHYARD_API_URL
SWITCHYARD_API_PORT
```

Service commands can also use peer placeholders such as `{web_url}`,
`{web_port}`, `{api_url}`, and `{api_port}`. For hyphenated service names, use
underscores in placeholders, such as `{db_main_port}`.

## MCP Tool Order

1. `switchyard_brief`
2. `switchyard_where` for a specific service
3. `switchyard_logs` only for the service that looks relevant
4. `switchyard_create` when the user asked for a missing branch runtime
5. `switchyard_up`, `switchyard_checkout`, `switchyard_uncheckout`, or `switchyard_down` only when the user asked for runtime changes
