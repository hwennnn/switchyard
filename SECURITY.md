# Security

Switchyard runs local developer commands. Treat `switchyard.toml` as executable configuration.

## Defaults

- Binds to `127.0.0.1` by default.
- Does not expose services publicly.
- Does not use ngrok, Tailscale, or LAN sharing in v0.
- Does not read secrets except by linking/copying files you explicitly configure.
- Rejects env file paths that escape the project/worktree.
- Serializes runtime operations per project to reduce port/state races.
- Checks recorded service commands before stopping running PIDs.
- Pins MCP tool calls to the server startup directory.

## Reporting

For a public repository, configure private vulnerability reporting on GitHub or publish a security contact here.

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
switchyard mcp config
```

The generated config pins project lookup to the detected root. Tool calls can
only load that project or subdirectories under it. Managed worktrees may still
be created in Switchyard's configured local worktree directory, such as
`SWITCHYARD_HOME` or `[project].worktree_root`. Keep approval enabled for
`switchyard_create`, `switchyard_up`, `switchyard_checkout`,
`switchyard_uncheckout`, and `switchyard_down`, because those tools create
worktrees, start port forwarders, or start and stop local processes.
