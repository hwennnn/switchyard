from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from .config import ProjectConfig, ServiceConfig
from .registry import Registry
from .utils import (
    child_pythonpath,
    find_free_port,
    now_iso,
    port_is_free,
    pid_running,
    recent_error_lines,
    render_command,
    slugify,
    stop_process_group,
    tail_lines,
)


def service_hostname(config: ProjectConfig, branch: str, service: str) -> str:
    return f"{slugify(service)}.{slugify(branch)}.{config.slug}.{config.proxy.tld}".lower()


def service_url(config: ProjectConfig, branch: str, service: str) -> str:
    return f"http://{service_hostname(config, branch, service)}:{config.proxy.port}"


def proxy_health(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/__switchyard/health", timeout=0.5) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_proxy(config: ProjectConfig, registry: Registry) -> str:
    if proxy_health(config.proxy.port, config.proxy.host):
        return "proxy already running"

    log_path = registry.proxy_log_path(config.proxy.port)
    log = log_path.open("ab", buffering=0)
    env = child_pythonpath(os.environ)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "switchyard",
            "proxy",
            "serve",
            "--host",
            config.proxy.host,
            "--port",
            str(config.proxy.port),
        ],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    registry.set_proxy(
        config.proxy.port,
        {
            "pid": process.pid,
            "host": config.proxy.host,
            "port": config.proxy.port,
            "log_file": str(log_path),
            "started_at": now_iso(),
        },
    )
    for _ in range(20):
        if proxy_health(config.proxy.port, config.proxy.host):
            return f"started proxy on {config.proxy.host}:{config.proxy.port}"
        time.sleep(0.1)
    return f"proxy start requested on {config.proxy.host}:{config.proxy.port}; check {log_path}"


def stop_proxy(config: ProjectConfig, registry: Registry) -> bool:
    record = registry.get_proxy(config.proxy.port)
    if not record:
        return True
    ok = stop_process_group(int(record.get("pid", 0)))
    if ok:
        registry.remove_proxy(config.proxy.port)
    return ok


def start_checkouts(
    config: ProjectConfig,
    registry: Registry,
    branch: str,
    selected: list[str] | None = None,
) -> list[str]:
    messages: list[str] = []
    selected_slugs = {slugify(item) for item in selected} if selected else None
    records = hydrate_status(registry.services(config.root, branch))
    for record in records:
        service_name = str(record.get("service"))
        if selected_slugs and service_name not in selected_slugs:
            continue
        if record.get("status") != "running":
            messages.append(f"{service_name} is not running for {branch}")
            continue
        desired = record.get("desired_port")
        if not desired:
            messages.append(f"{service_name} has no canonical port configured")
            continue
        desired_port = int(desired)
        actual_port = int(record["port"])
        if desired_port == actual_port:
            messages.append(f"{service_name} already owns canonical port {desired_port}")
            continue

        existing = registry.find_checkout(config.root, service_name, branch)
        if existing and pid_running(int(existing.get("pid", 0))):
            messages.append(f"{service_name} checkout already running on canonical port {desired_port}")
            continue
        if not port_is_free(desired_port, str(record.get("backend_host", "127.0.0.1"))):
            messages.append(f"{service_name} cannot bind canonical port {desired_port}; something else owns it")
            continue

        log_path = registry.log_path(config, branch, f"checkout-{service_name}")
        log = log_path.open("ab", buffering=0)
        env = child_pythonpath(os.environ)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "switchyard",
                "forward",
                "serve",
                "--host",
                str(record.get("backend_host", "127.0.0.1")),
                "--port",
                str(desired_port),
                "--target-host",
                str(record.get("backend_host", "127.0.0.1")),
                "--target-port",
                str(actual_port),
            ],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        registry.upsert_checkout(
            config,
            {
                "project": config.name,
                "branch": branch,
                "branch_slug": slugify(branch),
                "service": service_name,
                "pid": process.pid,
                "listen_host": str(record.get("backend_host", "127.0.0.1")),
                "listen_port": desired_port,
                "target_host": str(record.get("backend_host", "127.0.0.1")),
                "target_port": actual_port,
                "log_file": str(log_path),
                "started_at": now_iso(),
            },
        )
        messages.append(f"checked out {service_name}: localhost:{desired_port} -> :{actual_port}")
    if not messages:
        messages.append("no matching running services to checkout")
    return messages


def stop_checkouts(
    config: ProjectConfig,
    registry: Registry,
    branch: str | None = None,
    selected: list[str] | None = None,
) -> list[str]:
    messages: list[str] = []
    selected_slugs = {slugify(item) for item in selected} if selected else None
    for record in registry.checkouts(config.root, branch):
        service_name = str(record.get("service"))
        if selected_slugs and service_name not in selected_slugs:
            continue
        ok = stop_process_group(int(record.get("pid", 0)))
        if ok:
            registry.remove_checkout(config.root, str(record.get("branch")), service_name)
            messages.append(f"unchecked {service_name} from canonical port {record.get('listen_port')}")
        else:
            messages.append(f"could not stop checkout for {service_name}")
    if not messages:
        messages.append("no matching checkouts")
    return messages


def build_service_record(
    config: ProjectConfig,
    service: ServiceConfig,
    branch: str,
    worktree: Path,
    port: int,
    command: str,
    log_path: Path,
    pid: int,
) -> dict[str, object]:
    hostname = service_hostname(config, branch, service.name)
    return {
        "project": config.name,
        "project_slug": config.slug,
        "project_root": str(config.root),
        "branch": branch,
        "branch_slug": slugify(branch),
        "service": service.name,
        "pid": pid,
        "command": command,
        "desired_port": service.port,
        "port": port,
        "backend_host": service.host,
        "hostname": hostname,
        "url": service_url(config, branch, service.name),
        "worktree": str(worktree),
        "log_file": str(log_path),
        "started_at": now_iso(),
    }


def start_services(
    config: ProjectConfig,
    registry: Registry,
    branch: str,
    worktree: Path,
    selected: list[str] | None = None,
) -> list[str]:
    messages = [ensure_proxy(config, registry)]
    selected_slugs = {slugify(item) for item in selected} if selected else set(config.services)
    allocated: dict[str, int] = {}
    avoid = [int(record["port"]) for record in registry.services() if pid_running(int(record.get("pid", 0)))]

    for service_name, service in config.services.items():
        if service_name not in selected_slugs:
            continue
        existing = registry.find_service(config.root, service_name, branch)
        if existing and pid_running(int(existing.get("pid", 0))):
            messages.append(f"{service_name} already running at {existing.get('url')}")
            continue
        port = find_free_port(service.port, service.host, config.ports.start, config.ports.end, avoid + list(allocated.values()))
        allocated[service_name] = port

    urls = {name: service_url(config, branch, name) for name in allocated}

    for service_name, port in allocated.items():
        service = config.services[service_name]
        url = service_url(config, branch, service_name)
        values = {
            "port": port,
            "host": service.host,
            "url": url,
            "service": service_name,
            "branch": branch,
            "branch_slug": slugify(branch),
            "project": config.name,
            "project_slug": config.slug,
        }
        command = render_command(service.command, values)
        log_path = registry.log_path(config, branch, service_name)
        log = log_path.open("ab", buffering=0)
        env = os.environ.copy()
        env.update(service.env)
        env.update(
            {
                "PORT": str(port),
                "HOST": service.host,
                "CANONICAL_PORT": str(service.port or port),
                "SWITCHYARD": "1",
                "SWITCHYARD_PROJECT": config.name,
                "SWITCHYARD_PROJECT_SLUG": config.slug,
                "SWITCHYARD_BRANCH": branch,
                "SWITCHYARD_BRANCH_SLUG": slugify(branch),
                "SWITCHYARD_SERVICE": service_name,
                "SWITCHYARD_PORT": str(port),
                "SWITCHYARD_URL": url,
            }
        )
        for other_name, other_url in urls.items():
            env[f"SWITCHYARD_{other_name.upper()}_URL"] = other_url
            env[f"SWITCHYARD_{other_name.upper()}_PORT"] = str(allocated[other_name])

        process = subprocess.Popen(
            command,
            cwd=str(worktree),
            shell=True,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        record = build_service_record(config, service, branch, worktree, port, command, log_path, process.pid)
        registry.upsert_service(config, record)
        messages.append(f"started {service_name} on :{port} -> {url}")

    return messages


def stop_services(
    config: ProjectConfig,
    registry: Registry,
    branch: str | None = None,
    selected: list[str] | None = None,
) -> list[str]:
    messages: list[str] = []
    selected_slugs = {slugify(item) for item in selected} if selected else None
    records = registry.services(config.root, branch)
    for record in records:
        service = str(record.get("service"))
        if selected_slugs and service not in selected_slugs:
            continue
        pid = int(record.get("pid", 0))
        checkout = registry.find_checkout(config.root, service, str(record.get("branch")))
        if checkout:
            stop_process_group(int(checkout.get("pid", 0)))
            registry.remove_checkout(config.root, str(record.get("branch")), service)
        ok = stop_process_group(pid)
        if ok:
            registry.remove_service(config.root, str(record.get("branch")), service)
            messages.append(f"stopped {service}")
        else:
            messages.append(f"could not stop {service} pid {pid}")
    if not messages:
        messages.append("no matching running services")
    return messages


def hydrate_status(records: list[dict[str, object]]) -> list[dict[str, object]]:
    hydrated = []
    for record in records:
        next_record = dict(record)
        running = pid_running(int(next_record.get("pid", 0)))
        next_record["status"] = "running" if running else "stale"
        log_file = Path(str(next_record.get("log_file", "")))
        next_record["recent_errors"] = recent_error_lines(log_file)
        hydrated.append(next_record)
    return hydrated


def brief_for(config: ProjectConfig, registry: Registry, branch: str | None, changed_files: list[str]) -> dict[str, object]:
    records = hydrate_status(registry.services(config.root, branch))
    errors = []
    for record in records:
        for line in record.get("recent_errors", []):
            errors.append({"service": record.get("service"), "line": line})
    return {
        "project": config.name,
        "project_root": str(config.root),
        "branch": branch,
        "services": [
            {
                "service": record.get("service"),
                "branch": record.get("branch"),
                "status": record.get("status"),
                "url": record.get("url"),
                "port": record.get("port"),
                "log_file": record.get("log_file"),
            }
            for record in records
        ],
        "changed_files": changed_files[:50],
        "recent_errors": errors[:20],
    }


def format_log_tail(log_path: Path, lines: int) -> str:
    return "\n".join(tail_lines(log_path, lines))
