from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(REPO_ROOT / "src")


def run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("COMMAND FAILED:", " ".join(args))
        print(result.stdout)
        print(result.stderr)
        raise SystemExit(result.returncode)
    return result


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def cleanup(repo: Path, env: dict[str, str], procs: list[subprocess.Popen[str]]) -> None:
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    for branch in ["feature/one", "feature/two"]:
        subprocess.run(
            [sys.executable, "-m", "switchyard", "down", "--branch", branch],
            cwd=repo,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    subprocess.run(
        [sys.executable, "-m", "switchyard", "proxy", "stop"],
        cwd=repo,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="switchyard-concurrency-") as temp:
        temp_path = Path(temp)
        repo = temp_path / "repo"
        home = temp_path / "home"
        repo.mkdir()
        env = os.environ.copy()
        env["PYTHONPATH"] = PYTHONPATH
        env["SWITCHYARD_HOME"] = str(home)
        procs: list[subprocess.Popen[str]] = []

        try:
            run(["git", "init"], repo, env)
            run(["git", "config", "user.email", "switchyard@example.test"], repo, env)
            run(["git", "config", "user.name", "Switchyard Test"], repo, env)

            (repo / "app.py").write_text(
                """
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = os.environ.get("SWITCHYARD_BRANCH", "").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *args):
        return

ThreadingHTTPServer(("127.0.0.1", int(os.environ["PORT"])), Handler).serve_forever()
"""
            )
            dynamic_start = free_port()
            dynamic_end = min(dynamic_start + 1000, 65535)
            (repo / "switchyard.toml").write_text(
                f"""
[project]
name = "parallel"

[proxy]
host = "127.0.0.1"
port = {free_port()}

[ports]
start = {dynamic_start}
end = {dynamic_end}

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
            run([sys.executable, "-m", "switchyard", "create", "feature/one"], repo, env)
            run([sys.executable, "-m", "switchyard", "create", "feature/two"], repo, env)

            procs = [
                subprocess.Popen(
                    [sys.executable, "-m", "switchyard", "up", branch, "web"],
                    cwd=str(repo),
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for branch in ("feature/one", "feature/two")
            ]
            for proc in procs:
                stdout, stderr = proc.communicate(timeout=20)
                if proc.returncode:
                    print(stdout)
                    print(stderr)
                    return proc.returncode

            status = json.loads(run([sys.executable, "-m", "switchyard", "status", "--json"], repo, env).stdout)
            records = [record for record in status["services"] if record["service"] == "web" and record["status"] == "running"]
            ports = {record["port"] for record in records}
            if len(records) != 2 or len(ports) != 2:
                print("unexpected records:", json.dumps(status, indent=2))
                return 1

            time.sleep(0.2)
            print("CONCURRENCY OK")
        finally:
            cleanup(repo, env, procs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
