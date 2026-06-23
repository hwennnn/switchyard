from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .utils import slugify


CONFIG_NAME = "switchyard.toml"


@dataclass(frozen=True)
class EnvConfig:
    link: list[str] = field(default_factory=list)
    copy: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProxyConfig:
    host: str = "127.0.0.1"
    port: int = 7331
    tld: str = "localhost"


@dataclass(frozen=True)
class PortsConfig:
    start: int = 41000
    end: int = 49999


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    command: str
    port: int | None = None
    host: str = "127.0.0.1"
    health: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    root: Path
    path: Path
    worktree_root: str | None
    env: EnvConfig
    proxy: ProxyConfig
    ports: PortsConfig
    services: dict[str, ServiceConfig]

    @property
    def slug(self) -> str:
        return slugify(self.name)


def discover_config(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for path in [current, *current.parents]:
        candidate = path / CONFIG_NAME
        if candidate.exists():
            return candidate
    return None


def load_config(path: Path) -> ProjectConfig:
    path = path.resolve()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    project_raw = raw.get("project", {})
    if not isinstance(project_raw, dict):
        raise ValueError("[project] must be a table")
    name = str(project_raw.get("name") or path.parent.name)
    worktree_root = project_raw.get("worktree_root")
    if worktree_root is not None:
        worktree_root = str(worktree_root)

    env_raw = raw.get("env", {})
    proxy_raw = raw.get("proxy", {})
    ports_raw = raw.get("ports", {})
    services_raw = raw.get("services", {})

    if not isinstance(services_raw, dict) or not services_raw:
        raise ValueError("at least one [services.<name>] table is required")

    services = {}
    for name_key, service_raw in services_raw.items():
        if not isinstance(service_raw, dict):
            raise ValueError(f"[services.{name_key}] must be a table")
        command = service_raw.get("command")
        if not command:
            raise ValueError(f"[services.{name_key}] command is required")
        service_name = slugify(str(name_key))
        env = service_raw.get("env", {})
        if not isinstance(env, dict):
            raise ValueError(f"[services.{name_key}.env] must be a table")
        services[service_name] = ServiceConfig(
            name=service_name,
            command=str(command),
            port=int(service_raw["port"]) if "port" in service_raw else None,
            host=str(service_raw.get("host", "127.0.0.1")),
            health=str(service_raw["health"]) if "health" in service_raw else None,
            env={str(k): str(v) for k, v in env.items()},
        )

    return ProjectConfig(
        name=name,
        root=path.parent,
        path=path,
        worktree_root=worktree_root,
        env=EnvConfig(
            link=[str(item) for item in env_raw.get("link", [])],
            copy=[str(item) for item in env_raw.get("copy", [])],
        ),
        proxy=ProxyConfig(
            host=str(proxy_raw.get("host", "127.0.0.1")),
            port=int(proxy_raw.get("port", 7331)),
            tld=str(proxy_raw.get("tld", "localhost")).strip("."),
        ),
        ports=PortsConfig(
            start=int(ports_raw.get("start", 41000)),
            end=int(ports_raw.get("end", 49999)),
        ),
        services=services,
    )


def detect_default_service(root: Path) -> tuple[str, int]:
    package_json = root / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text())
            scripts = package.get("scripts", {})
            if isinstance(scripts, dict) and "dev" in scripts:
                manager = "npm"
                if (root / "pnpm-lock.yaml").exists():
                    manager = "pnpm"
                elif (root / "yarn.lock").exists():
                    manager = "yarn"
                return f"{manager} run dev", 3000
        except Exception:
            pass
    if (root / "manage.py").exists():
        return "python manage.py runserver 127.0.0.1:{port}", 8000
    return "python -m http.server {port}", 8000


def default_config_text(root: Path) -> str:
    command, port = detect_default_service(root)
    project_name = slugify(root.name)
    return f"""# Switchyard maps each agent worktree to its own local runtime.
# Desired ports are preferences. If a port is busy, Switchyard allocates a free one.

[project]
name = "{project_name}"

[env]
link = [".env", ".env.local"]
copy = []

[proxy]
host = "127.0.0.1"
port = 7331
tld = "localhost"

[ports]
start = 41000
end = 49999

[services.web]
command = "{command}"
port = {port}
"""

