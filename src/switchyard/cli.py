from __future__ import annotations

import argparse
import importlib.resources as resources
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import webbrowser
from pathlib import Path

from . import __version__
from .config import CONFIG_NAME, default_config_text, detect_default_service, discover_config, load_config, validate_loopback_host
from .envsync import env_source_warnings, sync_env_files
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
from .utils import fail, lines_since, pid_running, print_table, slugify, switchyard_home, tail_lines


def load_project_config(cwd: Path) -> tuple[object, Registry]:
    registry = Registry()
    registered = registry.find_worktree_containing(cwd)
    if registered:
        project, _ = registered
        config_path = Path(str(project.get("config") or Path(str(project["root"])) / CONFIG_NAME))
        if config_path.exists():
            config = load_config(config_path)
            registry.ensure_project(config)
            return config, registry
    config_path = discover_config(cwd)
    if not config_path:
        raise FileNotFoundError(f"could not find {CONFIG_NAME}; run `switchyard init`")
    config = load_config(config_path)
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
    registered = registry.find_worktree_containing(cwd)
    if registered:
        project, record = registered
        if Path(str(project.get("root", ""))).resolve() == config.root.resolve():
            return str(record["branch"]), Path(str(record["path"]))
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
    env_warnings = env_source_warnings(config.root, config.env)
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
        "env_warnings": env_warnings,
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
    for warning in env_warnings:
        print(f"env: {warning}")
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


def branch_for_action(config, registry: Registry, requested: str | None, cwd: Path) -> str | None:
    if requested:
        return requested
    if cwd.resolve() == config.root.resolve():
        return None
    branch, _ = resolve_branch_and_worktree(config, registry, None, cwd)
    return branch


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
        branch = branch_for_action(config, registry, args.branch, Path.cwd())
        messages = stop_services(config, registry, branch, args.services)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json(
            "down",
            {"branch": branch, "scope": branch_scope(branch), "services": args.services, "messages": messages},
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
        branch = branch_for_action(config, registry, args.branch, Path.cwd())
        messages = stop_checkouts(config, registry, branch, args.services)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print_action_json(
            "uncheckout",
            {"branch": branch, "scope": branch_scope(branch), "services": args.services, "messages": messages},
        )
        return 0
    for message in messages:
        print(message)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    try:
        config, registry = load_project_config(Path.cwd())
        branch_filter = args.branch
        if not branch_filter and Path.cwd().resolve() != config.root.resolve():
            branch_filter, _ = resolve_branch_and_worktree(config, registry, None, Path.cwd())
        records = hydrate_status(registry.services(config.root, branch_filter))
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print(json.dumps({"services": records}, indent=2, sort_keys=True))
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
    if args.follow and args.json:
        return fail_output(args, "--json cannot be used with --follow")
    if args.lines < 1:
        return fail_output(args, "--lines must be at least 1")
    try:
        config, registry = load_project_config(Path.cwd())
        branch, _ = resolve_branch_and_worktree(config, registry, args.branch, Path.cwd())
        if args.service:
            record = registry.find_service(config.root, args.service, branch)
            records = [record] if record else []
        else:
            records = registry.services(config.root, branch)
    except Exception as exc:
        return fail_output(args, str(exc))
    if not records:
        return fail_output(args, "no matching logs")
    if args.json:
        logs = []
        for record in records:
            path = Path(str(record["log_file"]))
            logs.append(
                {
                    "service": record.get("service"),
                    "branch": record.get("branch"),
                    "log_file": str(path),
                    "lines": tail_lines(path, args.lines),
                }
            )
        print(json.dumps({"logs": logs, "lines": args.lines}, indent=2, sort_keys=True))
        return 0
    offsets: dict[str, int] = {}
    while True:
        for record in records:
            path = Path(str(record["log_file"]))
            path_key = str(path)
            if args.follow and path_key in offsets:
                offsets[path_key], new_lines = lines_since(path, offsets[path_key])
                tail = "\n".join(new_lines)
            else:
                tail = format_log_tail(path, args.lines)
                offsets[path_key] = path.stat().st_size if path.exists() else 0
            if len(records) > 1 and tail:
                print(f"==> {record['service']} ({record['branch']}) <==")
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
        branch_filter = branch if args.branch or worktree.resolve() != config.root.resolve() else None
        brief = brief_for(config, registry, branch_filter, changed)
    except Exception as exc:
        return fail_output(args, str(exc))
    if args.json:
        print(json.dumps(brief, indent=2, sort_keys=True))
        return 0
    print(f"project: {brief['project']}")
    if brief.get("branch"):
        print(f"branch: {brief['branch']}")
    if brief["configured_services"]:
        print("configured services:")
        for service_name in brief["configured_services"]:
            print(f"- {service_name}")
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
    if brief["env_warnings"]:
        print("env warnings:")
        for warning in brief["env_warnings"][:10]:
            print(f"- {warning}")
    if brief["recent_errors"]:
        print("recent errors:")
        for item in brief["recent_errors"][:10]:
            print(f"- {item['service']}: {item['line']}")
    return 0


def cmd_proxy(args: argparse.Namespace) -> int:
    if args.proxy_command == "serve":
        try:
            host = validate_loopback_host(args.host, "--host")
        except Exception as exc:
            return fail(str(exc))
        home = Path(args.home).expanduser() if args.home else None
        serve(host, args.port, home)
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
        try:
            host = validate_loopback_host(args.host, "--host")
            target_host = validate_loopback_host(args.target_host, "--target-host")
        except Exception as exc:
            return fail(str(exc))
        serve_fixed(host, args.port, target_host, args.target_port)
        return 0
    return fail("unknown forward command")


def cmd_mcp(args: argparse.Namespace) -> int:
    try:
        launch_cwd = Path.cwd().resolve()
        root = resolve_mcp_server_root(getattr(args, "mcp_cwd", None), getattr(args, "mcp_project", None))
    except Exception as exc:
        return fail(str(exc))
    server_cwd = root
    if getattr(args, "mcp_project", None) and not getattr(args, "mcp_cwd", None):
        try:
            registered_root = registered_mcp_worktree_project_root(launch_cwd)
        except FileNotFoundError:
            registered_root = None
        if registered_root and registered_root.resolve() == root.resolve():
            server_cwd = launch_cwd
    os.chdir(server_cwd)
    return serve_mcp(server_cwd)


def mcp_setup_cwd(args: argparse.Namespace) -> str | None:
    return getattr(args, "cwd", None) or getattr(args, "mcp_cwd", None)


def resolve_mcp_project_root(project: str) -> Path:
    validate_mcp_name(project)
    root = Registry().resolve_project_alias(project)
    if not root:
        raise FileNotFoundError(f"unknown MCP project {project!r}; run `switchyard mcp install --name {project}` from the project")
    config_path = root / CONFIG_NAME
    if not config_path.exists():
        raise FileNotFoundError(f"registered MCP project {project!r} no longer has {CONFIG_NAME}; rerun `switchyard mcp install --name {project}`")
    return root.resolve()


def registered_mcp_worktree_project_root(cwd: Path) -> Path | None:
    registered = Registry(create=False).find_worktree_containing(cwd)
    if not registered:
        return None
    project, _ = registered
    root_value = project.get("root")
    if not root_value:
        raise FileNotFoundError("registered MCP worktree has no parent project root; recreate it with `switchyard create`")
    root = Path(str(root_value)).expanduser().resolve()
    config_value = project.get("config")
    config_path = Path(str(config_value)).expanduser().resolve() if config_value else root / CONFIG_NAME
    if config_path.parent.resolve() != root or config_path.name != CONFIG_NAME:
        raise FileNotFoundError("registered MCP worktree has an invalid parent project config path; recreate it with `switchyard create`")
    if not config_path.exists():
        raise FileNotFoundError(f"registered MCP worktree parent project no longer has {CONFIG_NAME}: {root}")
    return root


def resolve_mcp_server_root(cwd: str | None, project: str | None = None) -> Path:
    if cwd and project:
        raise ValueError("use either --cwd or --project, not both")
    if project:
        return resolve_mcp_project_root(project)
    root = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    if registered_mcp_worktree_project_root(root):
        return root
    config_path = discover_config(root)
    if config_path:
        return config_path.parent.resolve()
    return root


def resolve_mcp_config_root(cwd: str | None, project: str | None = None) -> tuple[Path, bool]:
    if cwd and project:
        raise ValueError("use either --cwd or --project, not both")
    if project:
        return resolve_mcp_project_root(project), True
    root = Path(cwd).expanduser().resolve() if cwd else Path.cwd().resolve()
    registered_root = registered_mcp_worktree_project_root(root)
    if registered_root:
        return registered_root, True
    config_path = discover_config(root)
    if config_path:
        return config_path.parent.resolve(), True
    return root, False


def validate_mcp_name(name: str) -> None:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if not name or any(char not in allowed for char in name):
        raise ValueError("MCP server name must contain only letters, numbers, underscores, and dashes")


def validate_mcp_project_alias(name: str, root: Path, force: bool = False, registry: Registry | None = None) -> None:
    validate_mcp_name(name)
    registry = registry or Registry(create=False)
    existing = registry.resolve_project_alias(name)
    if existing and existing != root.resolve() and not force:
        raise ValueError(
            f"MCP project alias {name!r} already points to {existing}; "
            "use --name for another project or --force to replace it"
        )


def register_mcp_project(name: str, root: Path, force: bool = False, registry: Registry | None = None) -> None:
    validate_mcp_name(name)
    registry = registry or Registry()
    registry.register_project_alias(name, root, force=force)


def path_within(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    resolved_root = root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    return resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root)


def mcp_launch_config(name: str, root: Path | None = None) -> tuple[str, list[str], list[str]]:
    skipped_project_local = False
    invoked = Path(sys.argv[0]).expanduser()
    if invoked.name in {"switchyard", "sy"}:
        resolved = invoked.resolve()
        if resolved.exists():
            if not path_within(resolved, root):
                return str(resolved), ["mcp", "--project", name], []
            skipped_project_local = True

    resolved_switchyard = shutil.which("switchyard")
    if resolved_switchyard:
        switchyard_path = Path(resolved_switchyard).expanduser().resolve()
        if not path_within(switchyard_path, root):
            return str(switchyard_path), ["mcp", "--project", name], []
        skipped_project_local = True

    comments = []
    if skipped_project_local:
        comments.append("# Ignored a project-local `switchyard` executable to keep MCP config path-free.")
    if path_within(Path(sys.executable), root):
        comments.append("# Install Switchyard on PATH with pipx/pip so the MCP client can launch it.")
        return "switchyard", ["mcp", "--project", name], comments

    return (
        sys.executable,
        ["-m", "switchyard", "mcp", "--project", name],
        comments
        + [
            "# `switchyard` was not found on PATH; this uses the current Python interpreter.",
            "# If Codex cannot launch it, install Switchyard with pipx or rerun from the target virtualenv.",
        ],
    )


def explicit_mcp_env(existing: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(existing or {})
    if "SWITCHYARD_HOME" in os.environ:
        env["SWITCHYARD_HOME"] = str(switchyard_home().expanduser().resolve())
    elif "SWITCHYARD_HOME" in env:
        env["SWITCHYARD_HOME"] = str(Path(env["SWITCHYARD_HOME"]).expanduser().resolve())
    return env


def mcp_registry_for_env(env: dict[str, str], create: bool = True) -> Registry:
    if "SWITCHYARD_HOME" in env:
        return Registry(Path(env["SWITCHYARD_HOME"]).expanduser().resolve(), create=create)
    return Registry(create=create)


def mcp_config_payload(name: str, existing_env: dict[str, str] | None = None, root: Path | None = None) -> dict[str, object]:
    validate_mcp_name(name)
    command, args, comments = mcp_launch_config(name, root=root)
    env = explicit_mcp_env(existing_env)
    args_text = ", ".join(json.dumps(item) for item in args)
    comment_text = "".join(f"{comment}\n" for comment in comments)
    env_text = ""
    if env:
        env_lines = "\n".join(f"{json.dumps(key)} = {json.dumps(value)}" for key, value in sorted(env.items()))
        env_text = f"\n[mcp_servers.{name}.env]\n{env_lines}\n"
    config_text = (
        f"[mcp_servers.{name}]\n"
        f"{comment_text}"
        f"command = {json.dumps(command)}\n"
        f"args = [{args_text}]\n"
        "startup_timeout_sec = 10\n"
        "tool_timeout_sec = 60\n"
        'default_tools_approval_mode = "prompt"\n'
        f"{env_text}"
    )
    return {
        "name": name,
        "config_text": config_text,
        "command": command,
        "args": args,
        "comments": comments,
        "env": env,
        "uses_python_fallback": args[:2] == ["-m", "switchyard"],
    }


def mcp_config_text(name: str, _root: Path) -> str:
    return str(mcp_config_payload(name, root=_root)["config_text"])


def codex_config_path() -> Path:
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return home / "config.toml"


def upsert_mcp_config_text(existing: str, name: str, root: Path) -> tuple[str, str]:
    original = existing
    existing_env = existing_mcp_env(existing, name)
    table = str(mcp_config_payload(name, existing_env, root=root)["config_text"]).rstrip() + "\n"
    header = f"[mcp_servers.{name}]"
    env_header = f"[mcp_servers.{name}.env]"
    existing = re.compile(rf"(?ms)^{re.escape(env_header)}\n.*?(?=^\[|\Z)").sub("", existing)
    pattern = re.compile(rf"(?ms)^{re.escape(header)}\n.*?(?=^\[|\Z)")
    if pattern.search(existing):
        updated = pattern.sub(table, existing, count=1)
        action = "updated"
    elif match := re.search(rf"(?m)^\[mcp_servers\.{re.escape(name)}\.", existing):
        updated = existing[: match.start()] + table + "\n" + existing[match.start() :]
        action = "added"
    elif existing.strip():
        updated = existing.rstrip() + "\n\n" + table
        action = "added"
    else:
        updated = table
        action = "added"
    if updated == original:
        action = "unchanged"
    tomllib.loads(updated)
    return updated, action


def existing_mcp_env(existing: str, name: str) -> dict[str, str]:
    if not existing.strip():
        return {}
    try:
        data = tomllib.loads(existing)
    except tomllib.TOMLDecodeError:
        return {}
    servers = data.get("mcp_servers", {})
    if not isinstance(servers, dict):
        return {}
    server = servers.get(name, {})
    env = server.get("env", {}) if isinstance(server, dict) else {}
    if not isinstance(env, dict):
        return {}
    return {str(key): value for key, value in env.items() if isinstance(value, str)}


def install_mcp_config(name: str, root: Path, path: Path | None = None) -> tuple[Path, str]:
    config_path = path or codex_config_path()
    existing = config_path.read_text() if config_path.exists() else ""
    if existing.strip():
        tomllib.loads(existing)
    updated, action = upsert_mcp_config_text(existing, name, root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{config_path.name}.", dir=config_path.parent)
    with open(fd, "w") as handle:
        handle.write(updated)
    Path(temp_name).replace(config_path)
    return config_path, action


def mcp_project_records(registry: Registry | None = None) -> list[dict[str, object]]:
    registry = registry or Registry(create=False)
    records: list[dict[str, object]] = []
    for record in registry.project_aliases():
        root = Path(record["root"]).expanduser().resolve()
        config_path = root / CONFIG_NAME
        if not config_path.exists():
            config_path = None
        records.append(
            {
                "name": record["name"],
                "root": str(root),
                "config": str(config_path) if config_path else None,
                "status": "ok" if config_path else "missing",
            }
        )
    return records


def mcp_projects_payload() -> dict[str, object]:
    registry = Registry(create=False)
    home = registry.home.expanduser().resolve()
    return {
        "home": str(home),
        "state_path": str((home / "state.json").resolve()),
        "projects": mcp_project_records(registry),
    }


def cmd_mcp_config(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False))
    try:
        root, found_config = resolve_mcp_config_root(mcp_setup_cwd(args), getattr(args, "mcp_project", None))
        payload = mcp_config_payload(args.name, root=root)
        text = str(payload["config_text"])
        registry = mcp_registry_for_env(payload["env"], create=False)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        return fail(str(exc))
    if not found_config:
        message = f"could not find {CONFIG_NAME} from {root}; run `switchyard init` there first"
        if json_output:
            print(json.dumps({"ok": False, "error": message}, indent=2, sort_keys=True))
            return 1
        return fail(message)
    try:
        register_mcp_project(args.name, root, force=args.force, registry=registry)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        return fail(str(exc))
    if json_output:
        print(
            json.dumps(
                {
                    "ok": True,
                    "name": args.name,
                    "registered": True,
                    "codex_config_path": str(codex_config_path()),
                    **payload,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(f"# Registered local MCP project: {args.name}")
    print(f"# Paste into {codex_config_path()}, or run `switchyard mcp install`.")
    print()
    print(text, end="")
    return 0


def cmd_mcp_install(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False))
    try:
        root, found_config = resolve_mcp_config_root(mcp_setup_cwd(args), getattr(args, "mcp_project", None))
        config_path = codex_config_path()
        existing = config_path.read_text() if config_path.exists() else ""
        if existing.strip():
            tomllib.loads(existing)
        existing_env = existing_mcp_env(existing, args.name)
        payload = mcp_config_payload(args.name, existing_env, root=root)
        text = str(payload["config_text"])
        registry = mcp_registry_for_env(payload["env"], create=False)
        _, action = upsert_mcp_config_text(existing, args.name, root)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        return fail(str(exc))
    if not found_config:
        message = f"could not find {CONFIG_NAME} from {root}; run `switchyard init` there first"
        if json_output:
            print(json.dumps({"ok": False, "error": message}, indent=2, sort_keys=True))
            return 1
        return fail(message)
    try:
        validate_mcp_project_alias(args.name, root, force=args.force, registry=registry)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        return fail(str(exc))
    if args.dry_run:
        if json_output:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "dry_run": True,
                        "name": args.name,
                        "registered": False,
                        "would_register": args.name,
                        "would_replace": bool(args.force),
                        "would_update": str(config_path),
                        **payload,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(f"# Would update: {codex_config_path()}")
        print(f"# Would register local MCP project: {args.name}")
        print("# Dry run only: the alias is not registered. Use `switchyard mcp config` for pasteable setup.")
        if args.force:
            print("# Would replace any existing local MCP project alias with that name.")
        print()
        print(text, end="")
        return 0
    try:
        config_path, action = install_mcp_config(args.name, root)
        register_mcp_project(args.name, root, force=args.force, registry=registry)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        return fail(str(exc))
    if json_output:
        print(
            json.dumps(
                {
                    "ok": True,
                    "dry_run": False,
                    "name": args.name,
                    "registered": True,
                    "action": action,
                    "codex_config_path": str(config_path),
                    "server_project": args.name,
                    **payload,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    print(f"{action} Codex MCP server {args.name!r} in {config_path}")
    print(f"server project: {args.name}")
    return 0


def cmd_mcp_projects(args: argparse.Namespace) -> int:
    payload = mcp_projects_payload()
    records = list(payload["projects"])
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    print(f"state home: {payload['home']}")
    if not records:
        print("no registered MCP projects")
        return 0
    rows = [[item["name"], item["status"], item["root"]] for item in records]
    print_table(["name", "status", "root"], rows)
    return 0


def mcp_smoke_rpc_payload() -> str:
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "switchyard-mcp-smoke", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": "switchyard://project/brief"},
        },
    ]
    return "\n".join(json.dumps(message) for message in messages) + "\n"


def run_mcp_smoke_command(args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "switchyard", *args],
        cwd=str(cwd),
        env=env,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"switchyard {' '.join(args)} failed with exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def run_mcp_smoke_process(command: str, args: list[str], cwd: Path, env: dict[str, str], stdin: str) -> str:
    result = subprocess.run(
        [command, *args],
        cwd=str(cwd),
        env=env,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"configured MCP server failed with exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result.stdout


def find_mcp_alias(projects: list[dict[str, object]], name: str) -> dict[str, object] | None:
    for alias in projects:
        if alias.get("name") == name:
            return alias
    return None


def mcp_smoke(project: Path, nested: str | None, name: str) -> dict[str, object]:
    cwd = (project / nested).expanduser().resolve() if nested else project.expanduser().resolve()
    if not cwd.is_dir():
        raise FileNotFoundError(f"smoke cwd is not a directory: {cwd}")
    root, found_config = resolve_mcp_config_root(str(cwd))
    if not found_config:
        raise FileNotFoundError(f"could not find {CONFIG_NAME} from {cwd}; run `switchyard init` there first")
    config_name = f"{name}-config"

    with tempfile.TemporaryDirectory(prefix="switchyard-mcp-smoke-") as temp:
        temp_path = Path(temp)
        env = os.environ.copy()
        package_root = Path(__file__).resolve().parents[1]
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(package_root) if not existing_pythonpath else f"{package_root}{os.pathsep}{existing_pythonpath}"
        env["SWITCHYARD_HOME"] = str((temp_path / "switchyard-home").resolve())
        env["CODEX_HOME"] = str((temp_path / "codex-home").resolve())

        config = json.loads(run_mcp_smoke_command(["mcp", "config", "--json", "--name", config_name], cwd, env))
        if config["ok"] is not True:
            raise RuntimeError("mcp config --json did not report ok")
        if config["args"][-2:] != ["--project", config_name]:
            raise RuntimeError("generated MCP args did not use the local alias")
        for forbidden in ["cwd =", "--cwd", str(root)]:
            if forbidden in config["config_text"]:
                raise RuntimeError(f"generated MCP config unexpectedly contained {forbidden!r}")
        if config["env"].get("SWITCHYARD_HOME") != env["SWITCHYARD_HOME"]:
            raise RuntimeError("generated MCP config did not preserve SWITCHYARD_HOME")

        projects = json.loads(run_mcp_smoke_command(["mcp", "projects", "--json"], temp_path, env))
        if projects["home"] != env["SWITCHYARD_HOME"]:
            raise RuntimeError("mcp projects did not report the smoke Switchyard home")
        if projects["state_path"] != str((Path(env["SWITCHYARD_HOME"]) / "state.json").resolve()):
            raise RuntimeError("mcp projects did not report the smoke state path")
        aliases = projects["projects"]
        config_alias = find_mcp_alias(aliases, config_name)
        if not config_alias:
            raise RuntimeError("mcp projects did not list the config alias")
        if config_alias["root"] != str(root) or config_alias["config"] != str(root / CONFIG_NAME):
            raise RuntimeError("mcp projects did not register the expected project alias")
        if config_alias["status"] != "ok":
            raise RuntimeError("mcp projects did not report a healthy alias")

        dry_run = json.loads(run_mcp_smoke_command(["mcp", "install", "--dry-run", "--json", "--name", name], cwd, env))
        if dry_run["ok"] is not True or dry_run["dry_run"] is not True or dry_run["registered"] is not False:
            raise RuntimeError("mcp install dry-run JSON did not report the expected state")
        for forbidden in ["cwd =", "--cwd", str(root)]:
            if forbidden in dry_run["config_text"]:
                raise RuntimeError(f"dry-run MCP config unexpectedly contained {forbidden!r}")
        dry_projects = json.loads(run_mcp_smoke_command(["mcp", "projects", "--json"], temp_path, env))
        if find_mcp_alias(dry_projects["projects"], name):
            raise RuntimeError("mcp install dry-run registered an alias")

        install = json.loads(run_mcp_smoke_command(["mcp", "install", "--json", "--name", name], cwd, env))
        if install["ok"] is not True or install["registered"] is not True:
            raise RuntimeError("mcp install JSON did not report registration")
        config_text = (Path(env["CODEX_HOME"]) / "config.toml").read_text()
        if f'"--project", "{name}"' not in config_text:
            raise RuntimeError("installed Codex config did not use alias args")
        for forbidden in ["cwd =", "--cwd", str(root)]:
            if forbidden in config_text:
                raise RuntimeError(f"installed Codex config unexpectedly contained {forbidden!r}")
        install_projects = json.loads(run_mcp_smoke_command(["mcp", "projects", "--json"], temp_path, env))
        install_alias = find_mcp_alias(install_projects["projects"], name)
        if not install_alias:
            raise RuntimeError("mcp install did not register the alias")
        if install_alias["root"] != str(root) or install_alias["config"] != str(root / CONFIG_NAME):
            raise RuntimeError("mcp install registered an unexpected project alias")
        if install_alias["status"] != "ok":
            raise RuntimeError("mcp install did not report a healthy alias")

        server = tomllib.loads(config_text)["mcp_servers"][name]
        server_env = dict(env)
        server_env.update({str(key): str(value) for key, value in server.get("env", {}).items()})
        mcp_output = run_mcp_smoke_process(
            str(server["command"]),
            [str(item) for item in server["args"]],
            temp_path,
            server_env,
            mcp_smoke_rpc_payload(),
        )
        if "switchyard://project/brief" not in mcp_output or "configured_services" not in mcp_output:
            raise RuntimeError("MCP server did not return the project brief resource")

        return {
            "ok": True,
            "project": str(root),
            "cwd": str(cwd),
            "name": name,
            "home": projects["home"],
            "state_path": projects["state_path"],
            "alias": install_alias,
            "config_alias": config_alias,
            "used_python": sys.executable,
        }


def cmd_mcp_smoke(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False))
    try:
        if getattr(args, "mcp_project", None):
            raise ValueError("run `switchyard mcp smoke` from a project checkout instead of using --project")
        result = mcp_smoke(Path(args.project or "."), args.nested, args.name)
    except Exception as exc:
        if json_output:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            return 1
        return fail(str(exc))
    if json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    print("OK   MCP project smoke")
    print(f"project: {result['project']}")
    print(f"cwd: {result['cwd']}")
    print(f"alias: {result['name']}")
    print(f"home: {result['home']}")
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
    logs.add_argument("--json", action="store_true")
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

    mcp = sub.add_parser(
        "mcp",
        usage="switchyard mcp [-h] [--project MCP_PROJECT] [config|install|projects|smoke] ...",
        help="Run or configure a stdio MCP server for AI agents",
        description=(
            "Run without a subcommand to start the stdio MCP server. "
            "Run inside a project, or use --project with an alias created by `switchyard mcp install`."
        ),
        epilog="Run `switchyard mcp install` from a project to create path-free Codex setup.",
    )
    mcp.add_argument(
        "--cwd",
        dest="mcp_cwd",
        help=argparse.SUPPRESS,
    )
    mcp.add_argument(
        "--project",
        dest="mcp_project",
        help="Registered project alias from `switchyard mcp install`",
    )
    mcp_sub = mcp.add_subparsers(dest="mcp_command", title="commands")
    mcp_config = mcp_sub.add_parser(
        "config",
        prog="switchyard mcp config",
        help="Print copy-paste Codex MCP config for this project",
    )
    mcp_config.add_argument("--cwd", help=argparse.SUPPRESS)
    mcp_config.add_argument("--name", default="switchyard", help="MCP server name in Codex config")
    mcp_config.add_argument("--force", action="store_true", help="Replace an existing alias that points to another project")
    mcp_config.add_argument("--json", action="store_true", help="Print machine-readable setup details")
    mcp_install = mcp_sub.add_parser(
        "install",
        prog="switchyard mcp install",
        help="Add this project to Codex MCP config",
    )
    mcp_install.add_argument("--cwd", help=argparse.SUPPRESS)
    mcp_install.add_argument("--name", default="switchyard", help="MCP server name in Codex config")
    mcp_install.add_argument("--dry-run", action="store_true", help="Print the Codex config update without writing it")
    mcp_install.add_argument("--force", action="store_true", help="Replace an existing alias that points to another project")
    mcp_install.add_argument("--json", action="store_true", help="Print machine-readable install details")
    mcp_projects = mcp_sub.add_parser(
        "projects",
        prog="switchyard mcp projects",
        help="List registered MCP project aliases",
    )
    mcp_projects.add_argument("--json", action="store_true")
    mcp_smoke_cmd = mcp_sub.add_parser(
        "smoke",
        prog="switchyard mcp smoke",
        help="Verify path-free MCP setup for a project",
    )
    mcp_smoke_cmd.add_argument("project", nargs="?", default=".", help="Project checkout or child directory to smoke")
    mcp_smoke_cmd.add_argument("--nested", help="Optional child directory, relative to project, to run setup from")
    mcp_smoke_cmd.add_argument("--name", default="switchyard-smoke", help="Temporary MCP alias name")
    mcp_smoke_cmd.add_argument("--json", action="store_true", help="Print machine-readable smoke details")
    mcp.set_defaults(func=cmd_mcp)
    mcp_config.set_defaults(func=cmd_mcp_config)
    mcp_install.set_defaults(func=cmd_mcp_install)
    mcp_projects.set_defaults(func=cmd_mcp_projects)
    mcp_smoke_cmd.set_defaults(func=cmd_mcp_smoke)

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
