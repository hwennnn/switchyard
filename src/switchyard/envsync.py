from __future__ import annotations

import shutil
from pathlib import Path

from .config import EnvConfig, validate_env_path


def safe_env_pair(source_root: Path, worktree: Path, item: str) -> tuple[Path, Path]:
    relative = validate_env_path(item)
    source_base = source_root.resolve()
    target_base = worktree.resolve()
    source = (source_base / relative).resolve(strict=False)
    target = (target_base / relative).resolve(strict=False)
    if not source.is_relative_to(source_base):
        raise ValueError(f"env source escapes project root: {item}")
    if not target.is_relative_to(target_base):
        raise ValueError(f"env target escapes worktree: {item}")
    return source, target


def env_source_warnings(source_root: Path, env: EnvConfig) -> list[str]:
    warnings: list[str] = []
    for mode, items in [("link", env.link), ("copy", env.copy)]:
        for item in items:
            source, _ = safe_env_pair(source_root, source_root, item)
            if not source.exists():
                warnings.append(f"missing {mode} source {item}")
    return warnings


def sync_env_files(source_root: Path, worktree: Path, env: EnvConfig, force: bool = False) -> list[str]:
    actions: list[str] = []
    for item in env.link:
        source, target = safe_env_pair(source_root, worktree, item)
        if not source.exists():
            actions.append(f"missing link source {item}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            if not force:
                actions.append(f"kept existing {item}")
                continue
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        target.symlink_to(source)
        actions.append(f"linked {item}")

    for item in env.copy:
        source, target = safe_env_pair(source_root, worktree, item)
        if not source.exists():
            actions.append(f"missing copy source {item}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            actions.append(f"kept existing {item}")
            continue
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
        actions.append(f"copied {item}")
    return actions
