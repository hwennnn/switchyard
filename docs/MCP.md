# Switchyard MCP

Switchyard includes a dependency-free stdio MCP server:

```sh
switchyard mcp --cwd /path/to/project
```

The server speaks newline-delimited JSON-RPC over stdin/stdout and exposes
tools for runtime discovery, logs, and process control.

## Codex

Codex reads MCP server configuration from `~/.codex/config.toml` or from a
trusted project-scoped `.codex/config.toml`.

```toml
[mcp_servers.switchyard]
command = "switchyard"
args = ["mcp", "--cwd", "/path/to/project"]
startup_timeout_sec = 10
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

You can also add it from the Codex CLI:

```sh
codex mcp add switchyard -- switchyard mcp --cwd /path/to/project
```

## Tools

```txt
switchyard_doctor
switchyard_status
switchyard_brief
switchyard_where
switchyard_logs
switchyard_up
switchyard_down
```

Recommended agent flow:

1. Call `switchyard_brief` for compact state.
2. Call `switchyard_where` for one service.
3. Call `switchyard_logs` for focused debugging.
4. Call `switchyard_up` or `switchyard_down` only when the user wants runtime changes.

## Safety

- The MCP server is local stdio, not a network listener.
- `switchyard_up` starts local processes from `switchyard.toml`.
- `switchyard_down` stops Switchyard-managed PIDs.
- Keep client approval enabled for write/action tools.
- Use `cwd` to pin the MCP server to the intended project.
