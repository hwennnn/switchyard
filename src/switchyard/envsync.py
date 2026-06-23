from __future__ import annotations

import shutil
from pathlib import Path

from .config import EnvConfig


def sync_env_files(source_root: Path, worktree: Path, env: EnvConfig, force: bool = False) -> list[str]:
    actions: list[str] = []
    for item in env.link:
        source = source_root / item
        target = worktree / item
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
        source = source_root / item
        target = worktree / item
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

