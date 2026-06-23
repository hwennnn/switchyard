from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from pathlib import Path

from . import __version__
from .config import CONFIG_NAME, default_config_text, discover_config, load_config
from .envsync import sync_env_files
from .gittools import GitError, append_info_exclude, create_worktree, current_branch, repo_root, status_short
from .mcp import serve_mcp
from .proxy import serve, serve_fixed
from .registry import Registry
from .runtime import (
    brief_for,
    format_log_tail,
    hydrate_status,
    service_url,
    start_checkouts,
    start_services,
    stop_checkouts,
    stop_proxy,
    stop_services,
)
from .utils import fail, pid_running, print_table, slugify, switchyard_home


def load_project_config(cwd: Path) -> tuple[object, Registry]:
    config_path = discover_config(cwd)
    if not config_path:
        raise FileNotFoundError(f"could not find {CONFIG_NAME}; run `switchyard init`")
    config = load_config(config_path)
    registry = Registry()
    registry.ensure_project(config)
    return config, registry


def resolve_branch_and_worktree(config, registry: Registry, branch: str | None, cwd: Path) -> tuple[str, Path]:
    if branch:
        record = registry.get_worktree(config.root, branch)
        if record:
            return str(record["branch"]), Path(str(record["path"]))
        if cwd.resolve() != config.root.resolve():
            return branch, cwd.resolve()
        return branch, registry.default_worktree_path(config, branch)
    try:
        branch = current_branch(cwd)
    except GitError:
        branch = "current"
    record = registry.get_worktree(config.root, branch)
    if record:
        return str(record["branch"]), Path(str(record["path"]))
    return branch, cwd.resolve()


def cmd_init(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        root = repo_root(cwd)
    except GitError:
        root = cwd.resolve()
    path = root / CONFIG_NAME
    if path.exists() and not args.force:
        return fail(f"{path} already exists; pass --force to overwrite")
    path.write_text(default_config_text(root))
    local_state = root / ".switchyard"
    local_state.mkdir(exist_ok=True)
    (local_state / ".gitignore").write_text("*\n!.gitignore\n")
    try:
        append_info_exclude(root, ".switchyard/")
    except Exception:
        pass
    print(f"created {path}")
    print("next: edit services if needed, then run `switchyard create feature/name`")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
    except Exception as exc:
        print(f"config: {exc}")
        print(f"home: {switchyard_home()}")
        return 1
    print(f"switchyard: {__version__}")
    print(f"python: {sys.version.split()[0]}")
    print(f"home: {registry.home}")
    print(f"project: {config.name} ({config.root})")
    print(f"config: {config.path}")
    print(f"proxy: http://{config.proxy.host}:{config.proxy.port}")
    print(f"services: {', '.join(config.services)}")
    return 0


def cmd_create(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch = args.branch
        path = Path(args.path).expanduser().resolve() if args.path else registry.default_worktree_path(config, branch)
        create_worktree(config.root, path, branch, args.base)
        actions = sync_env_files(config.root, path, config.env, force=args.force_env)
        registry.upsert_worktree(config, branch, path)
    except Exception as exc:
        return fail(str(exc))
    print(f"created worktree {branch} at {path}")
    for action in actions:
        print(f"env: {action}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
    except Exception as exc:
        return fail(str(exc))
    worktrees = registry.list_worktrees(config.root)
    rows = [[item["branch"], item["path"]] for item in worktrees]
    if rows:
        print_table(["branch", "path"], rows)
    else:
        print("no Switchyard worktrees registered")
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch, worktree = resolve_branch_and_worktree(config, registry, args.branch, Path.cwd())
        if not worktree.exists():
            return fail(f"worktree does not exist: {worktree}; run `switchyard create {branch}` first")
        messages = start_services(config, registry, branch, worktree, args.services)
    except Exception as exc:
        return fail(str(exc))
    for message in messages:
        print(message)
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        messages = stop_services(config, registry, args.branch, args.services)
    except Exception as exc:
        return fail(str(exc))
    for message in messages:
        print(message)
    return 0


def cmd_checkout(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        messages = start_checkouts(config, registry, args.branch, args.services)
    except Exception as exc:
        return fail(str(exc))
    for message in messages:
        print(message)
    return 0


def cmd_uncheckout(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        messages = stop_checkouts(config, registry, args.branch, args.services)
    except Exception as exc:
        return fail(str(exc))
    for message in messages:
        print(message)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        records = hydrate_status(registry.services(config.root, args.branch))
    except Exception as exc:
        return fail(str(exc))
    if args.json:
        print(json.dumps(records, indent=2, sort_keys=True))
        return 0
    if not records:
        print("no services registered")
        return 0
    rows = [
        [record["status"], record["branch"], record["service"], record["port"], record["url"], record["pid"]]
        for record in records
    ]
    print_table(["status", "branch", "service", "port", "url", "pid"], rows)
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch, _ = resolve_branch_and_worktree(config, registry, args.branch, Path.cwd())
        if args.service:
            record = registry.find_service(config.root, args.service, branch)
            records = [record] if record else []
        else:
            records = registry.services(config.root, branch)
    except Exception as exc:
        return fail(str(exc))
    if not records:
        return fail("no matching logs")
    while True:
        for record in records:
            path = Path(str(record["log_file"]))
            if len(records) > 1:
                print(f"==> {record['service']} ({record['branch']}) <==")
            tail = format_log_tail(path, args.lines)
            if tail:
                print(tail)
        if not args.follow:
            return 0
        time.sleep(1)


def cmd_open(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch, _ = resolve_branch_and_worktree(config, registry, args.branch, Path.cwd())
        record = registry.find_service(config.root, args.service, branch)
        url = str(record["url"]) if record else service_url(config, branch, args.service)
    except Exception as exc:
        return fail(str(exc))
    print(url)
    if not args.print_only:
        webbrowser.open(url)
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch, _ = resolve_branch_and_worktree(config, registry, args.branch, Path.cwd())
        record = registry.find_service(config.root, args.service, branch)
        if not record:
            return fail(f"{args.service} is not running for {branch}")
    except Exception as exc:
        return fail(str(exc))
    if args.json:
        print(json.dumps(record, indent=2, sort_keys=True))
    else:
        print(record["url"])
        print(f"port: {record['port']}")
        print(f"log: {record['log_file']}")
    return 0


def cmd_brief(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch, worktree = resolve_branch_and_worktree(config, registry, args.branch, Path.cwd())
        changed = status_short(worktree) if worktree.exists() else []
        brief = brief_for(config, registry, branch if args.branch else None, changed)
    except Exception as exc:
        return fail(str(exc))
    if args.json:
        print(json.dumps(brief, indent=2, sort_keys=True))
        return 0
    print(f"project: {brief['project']}")
    if brief.get("branch"):
        print(f"branch: {brief['branch']}")
    if brief["services"]:
        print("services:")
        for service in brief["services"]:
            print(f"- {service['service']} [{service['status']}]: {service['url']}")
    else:
        print("services: none")
    if brief["changed_files"]:
        print("changed files:")
        for line in brief["changed_files"][:20]:
            print(f"- {line}")
    if brief["recent_errors"]:
        print("recent errors:")
        for item in brief["recent_errors"][:10]:
            print(f"- {item['service']}: {item['line']}")
    return 0


def cmd_proxy(args: argparse.Namespace) -> int:
    if args.proxy_command == "serve":
        home = Path(args.home).expanduser() if args.home else None
        serve(args.host, args.port, home)
        return 0
    try:
        config, registry = load_project_config(Path.cwd())
    except Exception as exc:
        return fail(str(exc))
    if args.proxy_command == "stop":
        ok = stop_proxy(config, registry)
        if ok:
            print("proxy stopped")
            return 0
        return fail("could not stop proxy")
    return fail("unknown proxy command")


def cmd_forward(args: argparse.Namespace) -> int:
    if args.forward_command == "serve":
        serve_fixed(args.host, args.port, args.target_host, args.target_port)
        return 0
    return fail("unknown forward command")


def cmd_mcp(args: argparse.Namespace) -> int:
    if args.cwd:
        os.chdir(Path(args.cwd).expanduser().resolve())
    return serve_mcp()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="switchyard", description="Local runtimes for parallel agent worktrees.")
    parser.add_argument("--version", action="version", version=f"switchyard {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create switchyard.toml")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor", help="Check local setup")
    doctor.set_defaults(func=cmd_doctor)

    create = sub.add_parser("create", help="Create a git worktree and sync env files")
    create.add_argument("branch")
    create.add_argument("--base")
    create.add_argument("--path")
    create.add_argument("--force-env", action="store_true")
    create.set_defaults(func=cmd_create)

    list_cmd = sub.add_parser("list", help="List Switchyard worktrees")
    list_cmd.set_defaults(func=cmd_list)

    up = sub.add_parser("up", help="Start services for a branch/worktree")
    up.add_argument("branch", nargs="?")
    up.add_argument("services", nargs="*")
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="Stop services")
    down.add_argument("--branch")
    down.add_argument("services", nargs="*")
    down.set_defaults(func=cmd_down)

    checkout = sub.add_parser("checkout", help="Map a running branch runtime to canonical configured ports")
    checkout.add_argument("branch")
    checkout.add_argument("services", nargs="*")
    checkout.set_defaults(func=cmd_checkout)

    uncheckout = sub.add_parser("uncheckout", help="Stop canonical port mappings")
    uncheckout.add_argument("--branch")
    uncheckout.add_argument("services", nargs="*")
    uncheckout.set_defaults(func=cmd_uncheckout)

    status = sub.add_parser("status", help="Show services")
    status.add_argument("--branch")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    logs = sub.add_parser("logs", help="Show service logs")
    logs.add_argument("service", nargs="?")
    logs.add_argument("--branch")
    logs.add_argument("-n", "--lines", type=int, default=80)
    logs.add_argument("-f", "--follow", action="store_true")
    logs.set_defaults(func=cmd_logs)

    open_cmd = sub.add_parser("open", help="Open a service URL")
    open_cmd.add_argument("service")
    open_cmd.add_argument("branch", nargs="?")
    open_cmd.add_argument("--print-only", action="store_true")
    open_cmd.set_defaults(func=cmd_open)

    where = sub.add_parser("where", help="Print service URL, port, and log path")
    where.add_argument("service")
    where.add_argument("branch", nargs="?")
    where.add_argument("--json", action="store_true")
    where.set_defaults(func=cmd_where)

    brief = sub.add_parser("brief", help="Print an agent-readable project summary")
    brief.add_argument("branch", nargs="?")
    brief.add_argument("--json", action="store_true")
    brief.set_defaults(func=cmd_brief)

    mcp = sub.add_parser("mcp", help="Run a stdio MCP server for AI agents")
    mcp.add_argument("--cwd", help="Project directory to use as the MCP server working directory")
    mcp.set_defaults(func=cmd_mcp)

    proxy = sub.add_parser("proxy", help="Manage the built-in reverse proxy")
    proxy_sub = proxy.add_subparsers(dest="proxy_command", required=True)
    serve_cmd = proxy_sub.add_parser("serve", help="Run proxy in foreground")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=7331)
    serve_cmd.add_argument("--home")
    stop_cmd = proxy_sub.add_parser("stop", help="Stop project proxy")
    proxy.set_defaults(func=cmd_proxy)
    serve_cmd.set_defaults(func=cmd_proxy)
    stop_cmd.set_defaults(func=cmd_proxy)

    return parser


def build_forward_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="switchyard forward", description=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="forward_command", required=True)
    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, required=True)
    serve_cmd.add_argument("--target-host", default="127.0.0.1")
    serve_cmd.add_argument("--target-port", type=int, required=True)
    serve_cmd.set_defaults(func=cmd_forward)
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "forward":
        parser = build_forward_parser()
        args = parser.parse_args(argv[1:])
        return int(args.func(args))
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
