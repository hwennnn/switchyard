from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from statistics import median


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(REPO_ROOT / "src")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run(args: list[str], cwd: Path, env: dict[str, str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        env=env,
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def timed(label: str, fn) -> dict[str, object]:
    started = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {"name": label, "ms": round(elapsed_ms, 2), "result": result}


def create_repo(root: Path, env: dict[str, str]) -> Path:
    repo = root / "repo"
    repo.mkdir()
    run(["git", "init"], repo, env)
    run(["git", "config", "user.email", "switchyard@example.test"], repo, env)
    run(["git", "config", "user.name", "Switchyard Benchmark"], repo, env)
    (repo / "app.py").write_text(
        """
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"ok {os.environ.get('SWITCHYARD_SERVICE')}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *args):
        return

ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
"""
    )
    (repo / "switchyard.toml").write_text(
        f"""
[project]
name = "bench"

[proxy]
host = "127.0.0.1"
port = {free_port()}

[env]
link = []
copy = []

[services.web]
command = "{sys.executable} app.py"
port = {free_port()}
"""
    )
    run(["git", "add", "."], repo, env)
    run(["git", "commit", "-m", "initial"], repo, env)
    return repo


def source_bytes() -> int:
    total = 0
    for path in (REPO_ROOT / "src").rglob("*.py"):
        total += path.stat().st_size
    return total


def tree_bytes(path: Path) -> int:
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache"}
    total = 0
    for item in path.rglob("*"):
        if any(part in ignored for part in item.parts):
            continue
        if item.is_file():
            total += item.stat().st_size
    return total


def run_once() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="switchyard-bench-") as temp:
        root = Path(temp)
        env = os.environ.copy()
        env["PYTHONPATH"] = PYTHONPATH
        env["SWITCHYARD_HOME"] = str(root / "home")
        repo = create_repo(root, env)

        metrics = []
        metrics.append(timed("doctor", lambda: run([sys.executable, "-m", "switchyard", "doctor"], repo, env).stdout))
        metrics.append(
            timed(
                "mcp_initialize_and_doctor",
                lambda: run(
                    [sys.executable, "-m", "switchyard", "mcp"],
                    repo,
                    env,
                    "\n".join(
                        [
                            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}',
                            '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"switchyard_doctor","arguments":{}}}',
                            "",
                        ]
                    ),
                ).stdout,
            )
        )
        metrics.append(timed("create_worktree", lambda: run([sys.executable, "-m", "switchyard", "create", "feature/bench"], repo, env).stdout))
        metrics.append(timed("up_web", lambda: run([sys.executable, "-m", "switchyard", "up", "feature/bench", "web"], repo, env).stdout))

        config = json.loads((Path(env["SWITCHYARD_HOME"]) / "state.json").read_text())
        project = next(iter(config["projects"].values()))
        service = next(iter(project["services"].values()))
        proxy_port = int(service["url"].rsplit(":", 1)[1])
        host = str(service["hostname"])
        request = urllib.request.Request(f"http://127.0.0.1:{proxy_port}/", headers={"Host": host})

        def fetch() -> str:
            for _ in range(30):
                try:
                    with urllib.request.urlopen(request, timeout=1) as response:
                        return response.read().decode()
                except Exception:
                    time.sleep(0.1)
            raise RuntimeError("service did not answer through proxy")

        metrics.append(timed("proxy_fetch", fetch))
        brief = timed("brief_json", lambda: run([sys.executable, "-m", "switchyard", "brief", "feature/bench", "--json"], repo, env).stdout)
        brief["bytes"] = len(str(brief["result"]).encode())
        brief["has_checkouts"] = "checkouts" in json.loads(str(brief["result"]))
        metrics.append(brief)
        metrics.append(timed("down", lambda: run([sys.executable, "-m", "switchyard", "down", "--branch", "feature/bench"], repo, env).stdout))
        run([sys.executable, "-m", "switchyard", "proxy", "stop"], repo, env)
        return {
            "metrics": [{key: value for key, value in item.items() if key != "result"} for item in metrics],
            "source_bytes": source_bytes(),
            "repo_bytes": tree_bytes(REPO_ROOT),
        }


def summarize(runs: list[dict[str, object]]) -> dict[str, object]:
    names = [item["name"] for item in runs[0]["metrics"]]
    metrics = []
    for name in names:
        values = [
            float(next(metric["ms"] for metric in run["metrics"] if metric["name"] == name))
            for run in runs
        ]
        entry = {"name": name, "median_ms": round(median(values), 2), "runs": values}
        bytes_values = [
            int(metric["bytes"])
            for run in runs
            for metric in run["metrics"]
            if metric["name"] == name and "bytes" in metric
        ]
        if bytes_values:
            entry["bytes"] = int(median(bytes_values))
        bool_keys = sorted(
            {
                key
                for run in runs
                for metric in run["metrics"]
                if metric["name"] == name
                for key, value in metric.items()
                if isinstance(value, bool)
            }
        )
        for key in bool_keys:
            entry[key] = all(bool(next(metric[key] for metric in run["metrics"] if metric["name"] == name)) for run in runs)
        metrics.append(entry)
    return {
        "runs": len(runs),
        "metrics": metrics,
        "source_bytes": runs[0]["source_bytes"],
        "repo_bytes": runs[0]["repo_bytes"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Switchyard local runtime operations.")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if not shutil.which("git"):
        raise SystemExit("git is required")
    results = [run_once() for _ in range(args.runs)]
    summary = summarize(results)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"Switchyard benchmark ({summary['runs']} run(s))")
    print(f"source bytes: {summary['source_bytes']}")
    print(f"repo bytes: {summary['repo_bytes']}")
    for metric in summary["metrics"]:
        extra = f", {metric['bytes']} bytes" if "bytes" in metric else ""
        print(f"- {metric['name']}: {metric['median_ms']} ms{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
