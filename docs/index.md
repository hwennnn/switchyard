<section class="hero" markdown>
# Switchyard Docs

Give each AI agent worktree its own local HTTP runtime: ports, URLs, logs, and
agent-readable status without a cloud control plane.

Start with `switchyard brief --json` for runtime context, or install the MCP
server with `switchyard mcp install` for agent-native workflows.
</section>

<div class="doc-grid" markdown>
<a class="doc-card" href="API/" markdown>
**API Reference**
<span>CLI commands, JSON envelopes, MCP resources/tools, config, env vars, and state.</span>
</a>

<a class="doc-card" href="MCP/" markdown>
**MCP Guide**
<span>Path-free setup, local project aliases, resources, prompts, tools, and approval boundaries.</span>
</a>

<a class="doc-card" href="AGENT_INTERFACE/" markdown>
**Agent Interface**
<span>The expected agent workflow: brief first, focused logs, explicit local mutations.</span>
</a>

<a class="doc-card" href="PUBLISHING_LOCAL/" markdown>
**Publishing And CI/CD**
<span>GitHub Actions, Pages docs deploys, TestPyPI/PyPI releases, and local smoke commands.</span>
</a>

<a class="doc-card" href="RELEASE/" markdown>
**Release**
<span>Release checklist, Trusted Publisher claims, install smokes, and tag discipline.</span>
</a>

<a class="doc-card" href="ARCHITECTURE/" markdown>
**Architecture**
<span>The small pieces: CLI, config, registry, process runner, proxy, and adapter boundaries.</span>
</a>
</div>

## Fast Start

```sh
brew install pipx
pipx ensurepath
pipx install switchyard-dev
cd your-project
switchyard init --dry-run
switchyard init
switchyard mcp install
```

Restart your terminal after `pipx ensurepath` if `switchyard` is not found.
Without Homebrew, install pipx with `python3 -m pip install --user pipx`, then
run `python3 -m pipx ensurepath`.

<ul class="quick-path" markdown>
<li><strong>1.</strong> Create `switchyard.toml` with `switchyard init`.</li>
<li><strong>2.</strong> Create a branch worktree with `switchyard create`.</li>
<li><strong>3.</strong> Start services with `switchyard up`.</li>
<li><strong>4.</strong> Let agents read `switchyard://project/brief`.</li>
</ul>

From a project with `switchyard.toml`, agents should start with:

```sh
switchyard brief --json
switchyard mcp smoke --json
```
