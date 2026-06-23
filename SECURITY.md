# Security

Switchyard runs local developer commands. Treat `switchyard.toml` as executable configuration.

## Defaults

- Binds to `127.0.0.1` by default.
- Does not expose services publicly.
- Does not use ngrok, Tailscale, or LAN sharing in v0.
- Does not read secrets except by linking/copying files you explicitly configure.
- Does not kill arbitrary PIDs.

## Reporting

For a public repository, configure private vulnerability reporting on GitHub or publish a security contact here.

## Local Secrets

Use `env.link` for files like `.env.local` when you want every worktree to see the same local secret file.

Use `env.copy` only when you want a point-in-time copy.

Make sure secret files are gitignored.

