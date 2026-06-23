from __future__ import annotations

from pathlib import Path

from .utils import command_exists, run


class GitError(RuntimeError):
    pass


def require_git() -> None:
    if not command_exists("git"):
        raise GitError("git is required but was not found on PATH")


def repo_root(cwd: Path) -> Path:
    require_git()
    result = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, check=False)
    if result.returncode != 0:
        raise GitError("current directory is not inside a git repository")
    return Path(result.stdout.strip()).resolve()


def current_branch(cwd: Path) -> str:
    result = run(["git", "branch", "--show-current"], cwd=cwd, check=False)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "could not read current branch")
    branch = result.stdout.strip()
    if branch:
        return branch
    result = run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, check=False)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "could not read current commit")
    return result.stdout.strip() or "detached"


def branch_exists(repo: Path, branch: str) -> bool:
    result = run(["git", "show-ref", "--verify", f"refs/heads/{branch}"], cwd=repo, check=False)
    return result.returncode == 0


def create_worktree(repo: Path, path: Path, branch: str, base: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and any(path.iterdir()):
        raise GitError(f"worktree path already exists and is not empty: {path}")
    if branch_exists(repo, branch):
        args = ["git", "worktree", "add", str(path), branch]
    else:
        args = ["git", "worktree", "add", "-b", branch, str(path)]
        if base:
            args.append(base)
    result = run(args, cwd=repo, check=False)
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or "git worktree add failed")


def status_short(cwd: Path) -> list[str]:
    result = run(["git", "status", "--short"], cwd=cwd, check=False)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def append_info_exclude(repo: Path, pattern: str) -> None:
    git_dir_result = run(["git", "rev-parse", "--git-common-dir"], cwd=repo, check=False)
    if git_dir_result.returncode != 0:
        return
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = (repo / git_dir).resolve()
    exclude = git_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if pattern not in existing.splitlines():
        with exclude.open("a") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"{pattern}\n")
