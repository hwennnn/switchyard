# Changelog

## 0.1.0 - Unreleased

- Initial CLI for worktree-scoped local runtimes.
- Dynamic port allocation and stable `.localhost` service URLs.
- Env file link/copy support for worktrees.
- Service registry, logs, status, `where`, and compact `brief` output.
- Checkout mappings in compact `brief` output.
- Machine-readable `init --dry-run --json` for first-run setup previews.
- Machine-readable `doctor --json` for setup and release harnesses.
- Machine-readable action output and error envelopes for `create`, `list`, `up`, `down`, `checkout`, and `uncheckout`.
- Built-in local HTTP reverse proxy and canonical checkout forwarder.
- Stdio MCP server for agent-readable runtime state.
- MCP tool annotations for read-only discovery and local mutation safety hints.
- One-command Codex MCP setup with `switchyard mcp install`.
- MCP worktree create/list tools for agent-managed branch runtimes.
- MCP checkout/uncheckout tools for canonical local port mappings.
- Bundled Codex skill with `switchyard skill show/install`.
- Release readiness and benchmark harnesses.
