from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .config import ProjectConfig
from .utils import ensure_dir, now_iso, slugify, switchyard_home


STATE_VERSION = 1


class Registry:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or switchyard_home()
        ensure_dir(self.home)
        ensure_dir(self.home / "logs")
        ensure_dir(self.home / "worktrees")
        self.path = self.home / "state.json"

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": STATE_VERSION, "projects": {}, "proxies": {}}
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            backup = self.path.with_suffix(".corrupt.json")
            self.path.replace(backup)
            return {"version": STATE_VERSION, "projects": {}, "proxies": {}}
        data.setdefault("version", STATE_VERSION)
        data.setdefault("projects", {})
        data.setdefault("proxies", {})
        return data

    def write(self, data: dict[str, Any]) -> None:
        ensure_dir(self.path.parent)
        fd, temp_name = tempfile.mkstemp(prefix="state.", suffix=".json", dir=self.path.parent)
        with open(fd, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        Path(temp_name).replace(self.path)

    def project_key(self, root: Path) -> str:
        return str(root.resolve())

    def ensure_project(self, config: ProjectConfig) -> dict[str, Any]:
        data = self.read()
        key = self.project_key(config.root)
        project = data["projects"].setdefault(
            key,
            {
                "name": config.name,
                "slug": config.slug,
                "root": str(config.root),
                "config": str(config.path),
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "worktrees": {},
                "services": {},
                "checkouts": {},
            },
        )
        project.update(
            {
                "name": config.name,
                "slug": config.slug,
                "root": str(config.root),
                "config": str(config.path),
                "updated_at": now_iso(),
            }
        )
        project.setdefault("worktrees", {})
        project.setdefault("services", {})
        project.setdefault("checkouts", {})
        self.write(data)
        return project

    def default_worktree_path(self, config: ProjectConfig, branch: str) -> Path:
        branch_slug = slugify(branch)
        if config.worktree_root:
            base = Path(config.worktree_root).expanduser()
            if not base.is_absolute():
                base = config.root / base
            return (base / branch_slug).resolve()
        return (self.home / "worktrees" / config.slug / branch_slug).resolve()

    def log_path(self, config: ProjectConfig, branch: str, service: str) -> Path:
        path = self.home / "logs" / config.slug / slugify(branch) / f"{slugify(service)}.log"
        ensure_dir(path.parent)
        return path

    def proxy_log_path(self, port: int) -> Path:
        path = self.home / "logs" / "proxy" / f"{port}.log"
        ensure_dir(path.parent)
        return path

    def upsert_worktree(self, config: ProjectConfig, branch: str, path: Path) -> None:
        data = self.read()
        key = self.project_key(config.root)
        project = data["projects"].setdefault(key, {"worktrees": {}, "services": {}, "checkouts": {}})
        project.setdefault("worktrees", {})[slugify(branch)] = {
            "branch": branch,
            "slug": slugify(branch),
            "path": str(path.resolve()),
            "updated_at": now_iso(),
        }
        project.update({"name": config.name, "slug": config.slug, "root": str(config.root), "config": str(config.path)})
        self.write(data)

    def get_project(self, root: Path) -> dict[str, Any] | None:
        return self.read()["projects"].get(self.project_key(root))

    def get_worktree(self, root: Path, branch_or_slug: str) -> dict[str, Any] | None:
        project = self.get_project(root)
        if not project:
            return None
        worktrees = project.get("worktrees", {})
        return worktrees.get(slugify(branch_or_slug))

    def list_worktrees(self, root: Path) -> list[dict[str, Any]]:
        project = self.get_project(root)
        if not project:
            return []
        return list(project.get("worktrees", {}).values())

    def service_key(self, branch: str, service: str) -> str:
        return f"{slugify(branch)}::{slugify(service)}"

    def upsert_service(self, config: ProjectConfig, record: dict[str, Any]) -> None:
        data = self.read()
        key = self.project_key(config.root)
        project = data["projects"].setdefault(key, {"worktrees": {}, "services": {}, "checkouts": {}})
        project.update({"name": config.name, "slug": config.slug, "root": str(config.root), "config": str(config.path)})
        project.setdefault("services", {})[self.service_key(record["branch"], record["service"])] = record
        self.write(data)

    def remove_service(self, root: Path, branch: str, service: str) -> None:
        data = self.read()
        project = data["projects"].get(self.project_key(root))
        if project:
            project.get("services", {}).pop(self.service_key(branch, service), None)
        self.write(data)

    def services(self, root: Path | None = None, branch: str | None = None) -> list[dict[str, Any]]:
        data = self.read()
        records: list[dict[str, Any]] = []
        projects = data["projects"]
        selected = [projects.get(self.project_key(root))] if root else projects.values()
        for project in selected:
            if not project:
                continue
            for record in project.get("services", {}).values():
                if branch and slugify(record.get("branch", "")) != slugify(branch):
                    continue
                records.append(record)
        return records

    def find_service(self, root: Path, service: str, branch: str) -> dict[str, Any] | None:
        key = self.service_key(branch, service)
        project = self.get_project(root)
        if not project:
            return None
        return project.get("services", {}).get(key)

    def find_route(self, host: str) -> dict[str, Any] | None:
        hostname = host.split(":", 1)[0].lower()
        for record in self.services():
            if str(record.get("hostname", "")).lower() == hostname:
                return record
        return None

    def upsert_checkout(self, config: ProjectConfig, record: dict[str, Any]) -> None:
        data = self.read()
        key = self.project_key(config.root)
        project = data["projects"].setdefault(key, {"worktrees": {}, "services": {}, "checkouts": {}})
        project.update({"name": config.name, "slug": config.slug, "root": str(config.root), "config": str(config.path)})
        project.setdefault("checkouts", {})[self.service_key(record["branch"], record["service"])] = record
        self.write(data)

    def checkouts(self, root: Path, branch: str | None = None) -> list[dict[str, Any]]:
        project = self.get_project(root)
        if not project:
            return []
        records = list(project.get("checkouts", {}).values())
        if branch:
            return [record for record in records if slugify(str(record.get("branch", ""))) == slugify(branch)]
        return records

    def find_checkout(self, root: Path, service: str, branch: str) -> dict[str, Any] | None:
        project = self.get_project(root)
        if not project:
            return None
        return project.get("checkouts", {}).get(self.service_key(branch, service))

    def remove_checkout(self, root: Path, branch: str, service: str) -> None:
        data = self.read()
        project = data["projects"].get(self.project_key(root))
        if project:
            project.get("checkouts", {}).pop(self.service_key(branch, service), None)
        self.write(data)

    def set_proxy(self, port: int, record: dict[str, Any]) -> None:
        data = self.read()
        data.setdefault("proxies", {})[str(port)] = record
        self.write(data)

    def get_proxy(self, port: int) -> dict[str, Any] | None:
        return self.read().get("proxies", {}).get(str(port))

    def remove_proxy(self, port: int) -> None:
        data = self.read()
        data.setdefault("proxies", {}).pop(str(port), None)
        self.write(data)
