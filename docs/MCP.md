# Switchyard MCP

Switchyard's MCP server lets agents discover local runtime state without
scraping terminals, guessing ports, or reading stale logs.

It is a dependency-free stdio server:

```sh
switchyard mcp
```

The server speaks newline-delimited JSON-RPC over stdin/stdout and exposes
tools for runtime discovery, logs, and process control.
When launched from a project or any child directory, it automatically pins the
server root to the nearest `switchyard.toml`; no absolute project path argument is
needed in the normal path.

## Codex

Codex reads MCP server configuration from `~/.codex/config.toml`. From inside
the Switchyard project, install the server directly:

```sh
switchyard mcp install
```

This detects the project root and writes the full MCP server block to your
Codex config. The project path is stored in Switchyard's local state as a
project alias; the Codex config only needs stable args:

```toml
args = ["mcp", "--project", "name"]
```

To inspect the config first, generate ready-to-paste setup text:

```sh
switchyard mcp config
```

The helper registers the local project alias and prints the same path-free TOML.
Use `--name` for multiple projects:

```sh
switchyard mcp install --name switchyard-entropic
switchyard mcp config --name switchyard-entropic
```

## Tools

- `switchyard_doctor`: project config, proxy, services, and Switchyard version.
- `switchyard_create`: create a managed git worktree and sync configured env files.
- `switchyard_list`: registered Switchyard worktrees for the project.
- `switchyard_status`: registered services with running/stale state.
- `switchyard_brief`: compact project/runtime summary, including service and checkout state.
- `switchyard_where`: URL, port, PID, worktree, and log path for one service.
- `switchyard_logs`: recent log tail for one service or branch.
- `switchyard_up`: start local services for a branch/worktree.
- `switchyard_checkout`: map a branch runtime back to configured canonical ports.
- `switchyard_uncheckout`: stop canonical port mappings.
- `switchyard_down`: stop Switchyard-managed services.

Recommended agent flow:

1. Call `switchyard_brief` for compact state.
2. Call `switchyard_where` for one service.
3. Call `switchyard_logs` for focused debugging.
4. Call `switchyard_create` when the user wants a new branch runtime.
5. Call `switchyard_up`, `switchyard_checkout`, `switchyard_uncheckout`, or
   `switchyard_down` only when the user wants runtime changes.

## Tool Annotations

Switchyard includes MCP tool annotations for safer clients:

- Discovery tools such as `switchyard_brief`, `switchyard_where`, and
  `switchyard_logs` are marked read-only and closed-world.
- `switchyard_up` is marked as a potentially destructive/open-world mutation
  because it executes configured project commands.
- `switchyard_checkout` is marked as a local, non-destructive mutation because
  it starts Switchyard-managed port forwarders.
- `switchyard_create`, `switchyard_uncheckout`, and `switchyard_down` are
  marked local destructive mutations because they create filesystem/git state or
  stop local runtime state.

## Structured Output

Every tool advertises an MCP `outputSchema` and returns JSON
`structuredContent` with an object envelope. For example, `switchyard_status`
returns `{ "services": [...] }` and `switchyard_logs` returns `{ "logs": [...] }`,
so agents can read tool results without scraping text.

## Safety

- The MCP server is local stdio, not a network listener.
- `switchyard mcp install` and `switchyard mcp config` register one local
  project alias for the detected root; tool calls cannot jump to a different
  local repository.
- `switchyard_create` creates a local git worktree and syncs configured env files.
- `switchyard_up` starts local processes from `switchyard.toml`.
- `switchyard_checkout` starts local canonical-port forwarders.
- `switchyard_uncheckout` stops Switchyard-managed canonical-port forwarders.
- `switchyard_down` stops Switchyard-managed PIDs.
- When called from a registered worktree `cwd`, `switchyard_uncheckout` and
  `switchyard_down` default to that worktree's branch. From the project root,
  an omitted branch still means all matching Switchyard-managed runtime state.
- Keep client approval enabled for write/action tools.
- Use `--cwd` only when installing/generating config for a different checkout.
- Use `--project <name>` when an MCP client starts the server outside the
  project tree.
