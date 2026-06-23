# Switchyard Docs

Switchyard gives each AI agent worktree its own local HTTP runtime: ports,
URLs, logs, and agent-readable status.

Use these docs when you need the supported integration contract, MCP setup, or
release process:

- [API Reference](API.md): CLI commands, JSON outputs, MCP resources/tools,
  `switchyard.toml`, env vars, and local state.
- [MCP Guide](MCP.md): path-free MCP setup, resources, prompts, tools, and
  safety boundaries.
- [Agent Interface](AGENT_INTERFACE.md): agent-first workflows and expected
  runtime inspection order.
- [Publishing And CI/CD](PUBLISHING_LOCAL.md): local build, GitHub Actions,
  GitHub Pages docs publishing, TestPyPI/PyPI release flow, and troubleshooting.
- [Release](RELEASE.md): release checklist and manual smoke commands.
- [Architecture](ARCHITECTURE.md): implementation boundaries and future adapter
  seams.

## Fast Start

```sh
pipx install switchyard-dev
cd your-project
switchyard init --dry-run
switchyard init
switchyard mcp install
```

From a project with `switchyard.toml`, agents should start with:

```sh
switchyard brief --json
switchyard mcp smoke --json
```
