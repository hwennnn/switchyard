from __future__ import annotations

import argparse
import importlib.resources as resources
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from . import __version__
from .config import CONFIG_NAME, default_config_text, detect_default_service, discover_config, load_config
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
    in_git_repo = True
    try:
        root = repo_root(cwd)
    except GitError:
        in_git_repo = False
        root = cwd.resolve()
    path = root / CONFIG_NAME
    local_state = root / ".switchyard"
    config_exists = path.exists()
    local_state_exists = local_state.exists()
    blocked_by_existing_config = config_exists and not args.force
    existing_config_message = f"{path} already exists; pass --force to overwrite"
    command, port = detect_default_service(root)
    config_text = default_config_text(root)
    payload = {
        "ok": True,
        "action": "init",
        "dry_run": bool(args.dry_run),
        "written": False,
        "created_config": False,
        "overwrote_config": False,
        "created_local_state": False,
        "would_fail": blocked_by_existing_config,
        "failure_reason": existing_config_message if blocked_by_existing_config else None,
        "root": str(root),
        "config": str(path),
        "config_exists": config_exists,
        "would_write_config": not blocked_by_existing_config,
        "local_state": str(local_state),
        "would_create_local_state": (not local_state_exists) and not blocked_by_existing_config,
        "would_update_git_exclude": in_git_repo and not blocked_by_existing_config,
        "detected_service": {"name": "web", "command": command, "port": port},
        "config_text": config_text,
    }
    if args.dry_run:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(config_text, end="")
        return 0
    if blocked_by_existing_config:
        return fail_output(args, existing_config_message)
    path.write_text(config_text)
    local_state.mkdir(exist_ok=True)
    (local_state / ".gitignore").write_text("*\n!.gitignore\n")
    try:
        append_info_exclude(root, ".switchyard/")
    except Exception:
        pass
    payload["written"] = True
    payload["created_config"] = not config_exists
    payload["overwrote_config"] = config_exists
    payload["created_local_state"] = not local_state_exists
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"created {path}")
    print("next: edit services if needed, then run `switchyard create feature/name`")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
    except Exception as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "switchyard": __version__,
                        "python": sys.version.split()[0],
                        "cwd": str(Path.cwd().resolve()),
                        "home": str(switchyard_home()),
                        "error": str(exc),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 1
        print(f"config: {exc}")
        print(f"home: {switchyard_home()}")
        return 1
    payload = {
        "ok": True,
        "switchyard": __version__,
        "python": sys.version.split()[0],
        "home": str(registry.home),
        "project": {
            "name": config.name,
            "slug": config.slug,
            "root": str(config.root),
            "config": str(config.path),
        },
        "proxy": {
            "host": config.proxy.host,
            "port": config.proxy.port,
            "url": f"http://{config.proxy.host}:{config.proxy.port}",
        },
        "services": sorted(config.services),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"switchyard: {__version__}")
    print(f"python: {sys.version.split()[0]}")
    print(f"home: {registry.home}")
    print(f"project: {config.name} ({config.root})")
    print(f"config: {config.path}")
    print(f"proxy: http://{config.proxy.host}:{config.proxy.port}")
    print(f"services: {', '.join(config.services)}")
    return 0


def fail_json(message: str, code: int = 1) -> int:
    print(json.dumps({"ok": False, "error": message}, indent=2, sort_keys=True))
    return code


def fail_output(args: argparse.Namespace, message: str, code: int = 1) -> int:
    if getattr(args, "json", False):
        return fail_json(message, code)
    return fail(message, code)


def print_action_json(action: str, payload: dict[str, object]) -> None:
    data = {"ok": True, "action": action}
    data.update(payload)
    print(json.dumps(data, indent=2, sort_keys=True))


def branch_scope(branch: str | None) -> str:
    return "branch" if branch else "all"


def cmd_create(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch = args.branch
        path = Path(args.path).expanduser().resolve() if args.path else registry.default_worktree_path(config, branch)
        create_worktree(config.root, path, branch, args.base)
        actions = sync_env_files(config.root, path, config.env, force=args.force_env)
        registry.upsert_worktree(config, branch, path)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json("create", {"branch": branch, "worktree": str(path), "env": actions})
        return 0
    print(f"created worktree {branch} at {path}")
    for action in actions:
        print(f"env: {action}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
    except Exception as exc:
        return fail_output(args, str(exc))
    worktrees = registry.list_worktrees(config.root)
    if args.json:
        print(json.dumps({"worktrees": worktrees}, indent=2, sort_keys=True))
        return 0
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
            return fail_output(args, f"worktree does not exist: {worktree}; run `switchyard create {branch}` first")
        messages = start_services(config, registry, branch, worktree, args.services)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json(
            "up",
            {"branch": branch, "worktree": str(worktree), "services": args.services, "messages": messages},
        )
        return 0
    for message in messages:
        print(message)
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        messages = stop_services(config, registry, args.branch, args.services)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json(
            "down",
            {"branch": args.branch, "scope": branch_scope(args.branch), "services": args.services, "messages": messages},
        )
        return 0
    for message in messages:
        print(message)
    return 0


def cmd_checkout(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        messages = start_checkouts(config, registry, args.branch, args.services)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json(
            "checkout",
            {"branch": args.branch, "scope": "branch", "services": args.services, "messages": messages},
        )
        return 0
    for message in messages:
        print(message)
    return 0


def cmd_uncheckout(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        messages = stop_checkouts(config, registry, args.branch, args.services)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json(
            "uncheckout",
            {"branch": args.branch, "scope": branch_scope(args.branch), "services": args.services, "messages": messages},
        )
        return 0
    for message in messages:
        print(message)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        records = hydrate_status(registry.services(config.root, args.branch))
    except Exception as exc:
        return fail_output(args, str(exc))
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
            return fail_output(args, f"{args.service} is not running for {branch}")
    except Exception as exc:
        return fail_output(args, str(exc))
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
        return fail_output(args, str(exc))
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
    if brief["checkouts"]:
        print("checkouts:")
        for checkout in brief["checkouts"]:
            print(
                f"- {checkout['service']} [{checkout['status']}]: "
                f"{checkout['listen_host']}:{checkout['listen_port']} -> "
                f"{checkout['target_host']}:{checkout['target_port']}"
            )
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
    cwd = getattr(args, "mcp_cwd", None)
    root = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    if cwd:
        os.chdir(root)
    return serve_mcp(root)


def mcp_setup_cwd(args: argparse.Namespace) -> str | None:
    return getattr(args, "cwd", None) or getattr(args, "mcp_cwd", None)


def resolve_mcp_config_root(cwd: str | None) -> tuple[Path, bool]:
    root = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    config_path = discover_config(root)
    if config_path:
        return config_path.parent.resolve(), True
    return root, False


def validate_mcp_name(name: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not name or any(char not in allowed for char in name):
        raise ValueError("MCP server name must contain only letters, numbers, underscores, and dashes")


def codex_mcp_add_args(name: str, root: Path) -> list[str]:
    validate_mcp_name(name)
    return ["codex", "mcp", "add", name, "--", "switchyard", "mcp", "--cwd", str(root)]


def mcp_config_text(name: str, root: Path) -> str:
    validate_mcp_name(name)
    args = ["mcp", "--cwd", str(root)]
    args_text = ", ".join(json.dumps(item) for item in args)
    return (
        f"[mcp_servers.{name}]\n"
        'command = "switchyard"\n'
        f"args = [{args_text}]\n"
        "startup_timeout_sec = 10\n"
        "tool_timeout_sec = 60\n"
        'default_tools_approval_mode = "prompt"\n'
    )


def cmd_mcp_config(args: argparse.Namespace) -> int:
    try:
        root, found_config = resolve_mcp_config_root(mcp_setup_cwd(args))
        text = mcp_config_text(args.name, root)
    except Exception as exc:
        return fail(str(exc))
    print(f"# Generated for: {root}")
    print("# Paste into a trusted Codex config, or run the matching CLI command below.")
    if not found_config:
        print(f"# Note: no {CONFIG_NAME} was found from that directory; run `switchyard init` there first.")
    print()
    print(text, end="")
    print()
    print(shlex.join(codex_mcp_add_args(args.name, root)))
    return 0


def cmd_mcp_install(args: argparse.Namespace) -> int:
    try:
        root, found_config = resolve_mcp_config_root(mcp_setup_cwd(args))
        command = codex_mcp_add_args(args.name, root)
    except Exception as exc:
        return fail(str(exc))
    if not found_config:
        return fail(f"could not find {CONFIG_NAME} from {root}; run `switchyard init` there first")
    if args.dry_run:
        print(shlex.join(command))
        return 0
    codex = shutil.which("codex")
    if not codex:
        return fail("codex CLI not found; run `switchyard mcp config` and paste the generated config instead")
    command[0] = codex
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip()
        return fail(details or "codex mcp add failed")
    if result.stdout.strip():
        print(result.stdout.strip())
    print(f"installed Codex MCP server {args.name!r} for {root}")
    return 0


def skill_resource_root():
    return resources.files("switchyard").joinpath("assets", "skills", "switchyard")


def skill_text() -> str:
    return skill_resource_root().joinpath("SKILL.md").read_text(encoding="utf-8")


def copy_resource_tree(source, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            copy_resource_tree(child, destination)
        else:
            destination.write_bytes(child.read_bytes())


def cmd_skill_show(args: argparse.Namespace) -> int:
    print(skill_text(), end="")
    return 0


def cmd_skill_install(args: argparse.Namespace) -> int:
    target_root = Path(args.target).expanduser().resolve()
    target = target_root / "switchyard"
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not args.force:
        return fail(f"{target} already exists; pass --force to replace it")
    staging_root = None
    backup = None
    try:
        target_root.mkdir(parents=True, exist_ok=True)
        staging_root = Path(tempfile.mkdtemp(prefix=".switchyard-skill-", dir=target_root))
        staged = staging_root / "switchyard"
        copy_resource_tree(skill_resource_root(), staged)
        if target_exists:
            backup = staging_root / "previous-switchyard"
            target.rename(backup)
        staged.rename(target)
    except Exception as exc:
        if backup and backup.exists() and not target.exists():
            backup.rename(target)
        return fail(str(exc))
    finally:
        if staging_root and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
    print(f"installed Switchyard skill at {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="switchyard", description="Local runtimes for parallel agent worktrees.")
    parser.add_argument("--version", action="version", version=f"switchyard {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create switchyard.toml")
    init.add_argument("--force", action="store_true")
    init.add_argument("--dry-run", action="store_true", help="Print the generated config without writing files")
    init.add_argument("--json", action="store_true")
    init.set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor", help="Check local setup")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    create = sub.add_parser("create", help="Create a git worktree and sync env files")
    create.add_argument("branch")
    create.add_argument("--base")
    create.add_argument("--path")
    create.add_argument("--force-env", action="store_true")
    create.add_argument("--json", action="store_true")
    create.set_defaults(func=cmd_create)

    list_cmd = sub.add_parser("list", help="List Switchyard worktrees")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    up = sub.add_parser("up", help="Start services for a branch/worktree")
    up.add_argument("branch", nargs="?")
    up.add_argument("services", nargs="*")
    up.add_argument("--json", action="store_true")
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="Stop services")
    down.add_argument("--branch")
    down.add_argument("services", nargs="*")
    down.add_argument("--json", action="store_true")
    down.set_defaults(func=cmd_down)

    checkout = sub.add_parser("checkout", help="Map a running branch runtime to canonical configured ports")
    checkout.add_argument("branch")
    checkout.add_argument("services", nargs="*")
    checkout.add_argument("--json", action="store_true")
    checkout.set_defaults(func=cmd_checkout)

    uncheckout = sub.add_parser("uncheckout", help="Stop canonical port mappings")
    uncheckout.add_argument("--branch")
    uncheckout.add_argument("services", nargs="*")
    uncheckout.add_argument("--json", action="store_true")
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

    mcp = sub.add_parser("mcp", help="Run or configure a stdio MCP server for AI agents")
    mcp.add_argument("--cwd", dest="mcp_cwd", help="Project directory to use as the MCP server working directory")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")
    mcp_config = mcp_sub.add_parser("config", help="Print copy-paste Codex MCP config for this project")
    mcp_config.add_argument("--cwd", help="Project directory to generate config for")
    mcp_config.add_argument("--name", default="switchyard", help="MCP server name in Codex config")
    mcp_install = mcp_sub.add_parser("install", help="Add this project to Codex MCP config")
    mcp_install.add_argument("--cwd", help="Project directory to install config for")
    mcp_install.add_argument("--name", default="switchyard", help="MCP server name in Codex config")
    mcp_install.add_argument("--dry-run", action="store_true", help="Print the codex mcp add command without running it")
    mcp.set_defaults(func=cmd_mcp)
    mcp_config.set_defaults(func=cmd_mcp_config)
    mcp_install.set_defaults(func=cmd_mcp_install)

    skill = sub.add_parser("skill", help="Show or install the bundled Codex skill")
    skill_sub = skill.add_subparsers(dest="skill_command", required=True)
    skill_show = skill_sub.add_parser("show", help="Print the bundled Switchyard skill")
    skill_show.set_defaults(func=cmd_skill_show)
    skill_install = skill_sub.add_parser("install", help="Install the bundled Switchyard skill for Codex")
    skill_install.add_argument("--target", default="~/.codex/skills", help="Directory that contains Codex skills")
    skill_install.add_argument("--force", action="store_true", help="Replace an existing switchyard skill")
    skill_install.set_defaults(func=cmd_skill_install)

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
