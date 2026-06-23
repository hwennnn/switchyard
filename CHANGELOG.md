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
- Machine-readable `logs --json` with structured log tail lines.
- Built-in local HTTP reverse proxy and canonical checkout forwarder.
- Stdio MCP server for agent-readable runtime state.
- MCP tool annotations for read-only discovery and local mutation safety hints.
- MCP output schemas for structured agent tool results.
- One-command Codex MCP setup with `switchyard mcp install`.
- Generated MCP config uses Codex `cwd` so server args stay pathless.
- MCP install writes the full Codex config block directly instead of shelling out to `codex mcp add`.
- MCP worktree create/list tools for agent-managed branch runtimes.
- MCP checkout/uncheckout tools for canonical local port mappings.
- MCP tool calls can target registered worktree paths for current-branch context.
- Service commands can reference peer `{service_url}` and `{service_port}` placeholders.
- Config validation rejects non-loopback proxy and service bind hosts.
- Bundled Codex skill with `switchyard skill show/install`.
- Hardened release readiness, benchmark, and PyPI publish harnesses.
- Minimal sdist allowlist with package-content checks.
- Pinned CI actions and multi-run benchmark release gate.
