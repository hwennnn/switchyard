# Contributing

Switchyard is intentionally small. Before adding a dependency or large abstraction, prefer:

1. A stdlib implementation.
2. An adapter boundary.
3. A documented limitation.

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
PYTHONPATH=src python3 -m unittest discover -s tests
python3 scripts/release_check.py --skip-package
```

Use the full release gate before packaging or publishing:

```sh
python3 scripts/release_check.py
```

## Design Principles

- Local-first.
- Headless first, UI later.
- Agent-readable by default.
- Works with existing tools.
- Owns only the processes it starts.
- Small config, explicit escape hatches.

## Pull Requests

Good first areas:

- WebSocket support in the built-in proxy.
- Caddy backend adapter.
- Portless backend adapter.
- Worktrunk worktree adapter.
- Docker Compose adapter.
- Better health checks.

MCP protocol changes should update the compatibility fixtures in
`tests/fixtures/mcp_*.jsonl` and keep `scripts/release_check.py` consuming them.
