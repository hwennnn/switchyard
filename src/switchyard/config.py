from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .utils import slugify


CONFIG_NAME = "switchyard.toml"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


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
class ProfileConfig:
    name: str
    services: list[str]
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
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)

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


def validate_env_path(value: str) -> str:
    path = Path(value)
    if not value or value.strip() != value:
        raise ValueError(f"invalid env path: {value!r}")
    if path.is_absolute():
        raise ValueError(f"env path must be relative: {value}")
    if value in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"env path must stay inside the project: {value}")
    return value


def validate_worktree_root(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("[project].worktree_root must be a string")
    if not value or value.strip() != value:
        raise ValueError("[project].worktree_root must be a non-empty path")
    return value


def env_list(raw: object, key: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"[env].{key} must be a list of strings")
    return [validate_env_path(item) for item in raw]


def validate_loopback_host(value: object, key: str) -> str:
    host = str(value).strip()
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"{key} must be a loopback host: 127.0.0.1, localhost, or ::1")
    return host


def env_table(raw: object, key: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{key} must be a table")
    return {str(k): str(v) for k, v in raw.items()}


def service_name_list(raw: object, key: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{key}.services must be a list of strings")
    return [slugify(item) for item in raw]


def load_config(path: Path) -> ProjectConfig:
    path = path.resolve()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    project_raw = raw.get("project", {})
    if not isinstance(project_raw, dict):
        raise ValueError("[project] must be a table")
    name = str(project_raw.get("name") or path.parent.name)
    worktree_root = validate_worktree_root(project_raw.get("worktree_root"))

    env_raw = raw.get("env", {})
    proxy_raw = raw.get("proxy", {})
    ports_raw = raw.get("ports", {})
    services_raw = raw.get("services", {})
    profiles_raw = raw.get("profiles", {})

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
        if service_name in services:
            raise ValueError(f"service names collide after slugging: {name_key}")
        services[service_name] = ServiceConfig(
            name=service_name,
            command=str(command),
            port=int(service_raw["port"]) if "port" in service_raw else None,
            host=validate_loopback_host(service_raw.get("host", "127.0.0.1"), f"[services.{name_key}].host"),
            health=str(service_raw["health"]) if "health" in service_raw else None,
            env=env_table(service_raw.get("env", {}), f"[services.{name_key}.env]"),
        )

    if not isinstance(profiles_raw, dict):
        raise ValueError("[profiles] must be a table")
    profiles = {}
    for profile_key, profile_raw in profiles_raw.items():
        if not isinstance(profile_raw, dict):
            raise ValueError(f"[profiles.{profile_key}] must be a table")
        profile_name = slugify(str(profile_key))
        if profile_name in profiles:
            raise ValueError(f"profile names collide after slugging: {profile_key}")
        profile_services = service_name_list(profile_raw.get("services", []), f"[profiles.{profile_key}]")
        unknown = sorted(set(profile_services) - set(services))
        if unknown:
            raise ValueError(f"[profiles.{profile_key}] references unknown service(s): {', '.join(unknown)}")
        profiles[profile_name] = ProfileConfig(
            name=profile_name,
            services=profile_services,
            env=env_table(profile_raw.get("env", {}), f"[profiles.{profile_key}.env]"),
        )

    return ProjectConfig(
        name=name,
        root=path.parent,
        path=path,
        worktree_root=worktree_root,
        env=EnvConfig(
            link=env_list(env_raw.get("link", []), "link"),
            copy=env_list(env_raw.get("copy", []), "copy"),
        ),
        proxy=ProxyConfig(
            host=validate_loopback_host(proxy_raw.get("host", "127.0.0.1"), "[proxy].host"),
            port=int(proxy_raw.get("port", 7331)),
            tld=str(proxy_raw.get("tld", "localhost")).strip("."),
        ),
        ports=PortsConfig(
            start=int(ports_raw.get("start", 41000)),
            end=int(ports_raw.get("end", 49999)),
        ),
        services=services,
        profiles=profiles,
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
                if manager == "yarn":
                    return "yarn run dev --port {port}", 3000
                return f"{manager} run dev -- --port {{port}}", 3000
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
# Commands should honor PORT/HOST env vars or include {{port}}/{{host}} placeholders.

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
