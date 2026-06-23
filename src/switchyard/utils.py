from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SLUG_RE = re.compile(r"[^a-z0-9]+")


def switchyard_home() -> Path:
    return Path(os.environ.get("SWITCHYARD_HOME", "~/.switchyard")).expanduser()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    slug = SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or "default"


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def _can_bind(family: socket.AddressFamily, address: tuple) -> bool:
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(address)
    except OSError:
        return False
    return True


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    checks: list[tuple[socket.AddressFamily, tuple]] = []
    if ":" in host:
        checks.append((socket.AF_INET6, (host, port, 0, 0)))
    else:
        checks.append((socket.AF_INET, (host, port)))
        checks.append((socket.AF_INET, ("0.0.0.0", port)))
        if socket.has_ipv6:
            checks.append((socket.AF_INET6, ("::", port, 0, 0)))
    return all(_can_bind(family, address) for family, address in checks)


def find_free_port(
    preferred: int | None = None,
    host: str = "127.0.0.1",
    start: int = 41000,
    end: int = 49999,
    avoid: Iterable[int] = (),
) -> int:
    avoid_set = set(avoid)
    if preferred and preferred not in avoid_set and port_is_free(preferred, host):
        return preferred
    for port in range(start, end + 1):
        if port not in avoid_set and port_is_free(port, host):
            return port
    raise RuntimeError(f"no free TCP ports found in {start}-{end}")


def pid_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command_contains(pid: int, expected: str | None) -> bool:
    if not expected or not pid_running(pid):
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return False
    return result.returncode == 0 and expected in result.stdout


def stop_process_group(pid: int, timeout: float = 5.0) -> bool:
    if not pid_running(pid):
        return True
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_running(pid):
            return True
        time.sleep(0.1)

    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return not pid_running(pid)


def tail_lines(path: Path, limit: int = 80) -> list[str]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        block = 4096
        data = b""
        while size > 0 and data.count(b"\n") <= limit:
            read_size = min(block, size)
            size -= read_size
            handle.seek(size)
            data = handle.read(read_size) + data
    lines = data.decode(errors="replace").splitlines()
    return lines[-limit:]


def recent_error_lines(path: Path, limit: int = 8, scan_lines: int = 200) -> list[str]:
    needles = ("error", "exception", "failed", "traceback", "eaddrinuse", "panic")
    found = []
    for line in tail_lines(path, scan_lines):
        lower = line.lower()
        if any(needle in lower for needle in needles):
            found.append(line)
    return found[-limit:]


def render_command(command: str, values: dict[str, object]) -> str:
    rendered = command
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def src_dir_for_child() -> str:
    return str(Path(__file__).resolve().parents[1])


def child_pythonpath(env: dict[str, str]) -> dict[str, str]:
    next_env = dict(env)
    current = next_env.get("PYTHONPATH")
    src_dir = src_dir_for_child()
    next_env["PYTHONPATH"] = src_dir if not current else f"{src_dir}{os.pathsep}{current}"
    return next_env


def print_table(headers: list[str], rows: list[list[object]]) -> None:
    data = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in data:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]
    print("  ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("  ".join("-" * width for width in widths))
    for row in data:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)))


def fail(message: str, code: int = 1) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code
