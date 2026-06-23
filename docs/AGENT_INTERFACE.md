# How Agents Use Switchyard

Switchyard is designed so agents do not need to infer local runtime state from terminal scrollback.

## MCP Server

Run Switchyard as a local stdio MCP server:

```sh
switchyard mcp
```

For Codex, generate project-specific setup text from inside the repository:

```sh
switchyard mcp config
```

The helper prints a trusted config snippet and an equivalent `codex mcp add`
command with the detected project root already filled in.

Available MCP tools:

```txt
switchyard_doctor
switchyard_status
switchyard_brief
switchyard_where
switchyard_logs
switchyard_up
switchyard_down
```

Use `switchyard_brief` before reading logs or guessing URLs. Treat
`switchyard_up` and `switchyard_down` as visible local actions because they
start and stop processes.

## Best Commands For Agents

Use:

```sh
switchyard brief --json
```

For a compact overview:

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
switchyard logs web --branch feature/login -n 120
```

When debugging.

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

## MCP Tool Order

1. `switchyard_brief`
2. `switchyard_where` for a specific service
3. `switchyard_logs` only for the service that looks relevant
4. `switchyard_up` or `switchyard_down` only when the user asked for runtime changes
