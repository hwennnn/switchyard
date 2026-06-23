# Security

Switchyard runs local developer commands. Treat `switchyard.toml` as executable configuration.

## Defaults

- Binds to `127.0.0.1` by default.
- Does not expose services publicly.
- Rejects proxy and service bind hosts outside `127.0.0.1`, `localhost`, or `::1`.
- Does not use ngrok, Tailscale, or LAN sharing in v0.
- Does not read secrets except by linking/copying files you explicitly configure.
- Rejects env file paths that escape the project/worktree.
- Serializes runtime operations per project to reduce port/state races.
- Checks recorded service commands before stopping running PIDs.
- Pins MCP tool calls to the server startup directory or registered worktrees.

## Reporting

Report vulnerabilities through GitHub private vulnerability reporting when it is
enabled for the repository. If private reporting is unavailable, open a minimal
public issue asking for a private security contact; do not include exploit
details or local secrets in the issue.

## Local Secrets

Use `env.link` for files like `.env.local` when you want every worktree to see the same local secret file.

Use `env.copy` only when you want a point-in-time copy.

Make sure secret files are gitignored.

`env.link` and `env.copy` accept relative paths inside the repository only.
Absolute paths, `..`, and empty path components are rejected before filesystem
mutation.

## MCP

Generate MCP setup from inside the trusted project:

```sh
switchyard mcp install
switchyard mcp config
```

The installed/generated config pins project lookup to a local project alias
registered from the detected root. The generated TOML uses
`args = ["mcp", "--project", "name"]`, so normal setup should not require
hard-coded path arguments. Direct `switchyard mcp` startup from a project or
child directory auto-pins to the nearest `switchyard.toml`. Tool calls can only
load the alias's project, subdirectories under it, or worktrees already
registered for that project.
Managed worktrees may still be created in Switchyard's configured local
worktree directory, such as `SWITCHYARD_HOME` or `[project].worktree_root`.
`[project].worktree_root` must be a non-empty string path.
Keep approval enabled for
`switchyard_create`, `switchyard_up`, `switchyard_checkout`,
`switchyard_uncheckout`, and `switchyard_down`, because those tools create
worktrees, start port forwarders, or start and stop local processes.
The MCP tool list also includes read-only/destructive/idempotent hints for
clients that surface tool risk in their approval UI.
