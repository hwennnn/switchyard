from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHONPATH = str(REPO_ROOT / "src")


def run(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="switchyard-e2e-") as temp:
        temp_path = Path(temp)
        repo = temp_path / "repo"
        home = temp_path / "home"
        repo.mkdir()
        env = os.environ.copy()
        env["PYTHONPATH"] = PYTHONPATH
        env["SWITCHYARD_HOME"] = str(home)

        proxy_port = free_port()
        desired_port = free_port()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", desired_port))
        blocker.listen()

        run(["git", "init"], repo, env)
        run(["git", "config", "user.email", "switchyard@example.test"], repo, env)
        run(["git", "config", "user.name", "Switchyard Test"], repo, env)

        (repo / "app.py").write_text(
            """
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"hello {os.environ.get('SWITCHYARD_BRANCH')} {os.environ.get('SWITCHYARD_SERVICE')}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *args):
        return

port = int(os.environ["PORT"])
ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
"""
        )
        (repo / "switchyard.toml").write_text(
            f"""
[project]
name = "demo"

[proxy]
host = "127.0.0.1"
port = {proxy_port}

[env]
link = []
copy = []

[services.web]
command = "{sys.executable} app.py"
port = {desired_port}
"""
        )
        run(["git", "add", "."], repo, env)
        run(["git", "commit", "-m", "initial"], repo, env)

        run([sys.executable, "-m", "switchyard", "create", "feature/demo"], repo, env)
        run([sys.executable, "-m", "switchyard", "up", "feature/demo"], repo, env)
        blocker.close()

        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy_port}/",
            headers={"Host": "web.feature-demo.demo.localhost"},
        )
        body = ""
        for _ in range(30):
            try:
                with urllib.request.urlopen(request, timeout=1) as response:
                    body = response.read().decode()
                    break
            except Exception:
                time.sleep(0.2)
        if body != "hello feature/demo web":
            print("unexpected proxy response:", body)
            return 1

        run([sys.executable, "-m", "switchyard", "checkout", "feature/demo", "web"], repo, env)
        canonical_body = ""
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{desired_port}/", timeout=1) as response:
                    canonical_body = response.read().decode()
                    break
            except Exception:
                time.sleep(0.2)
        if canonical_body != "hello feature/demo web":
            print("unexpected canonical response:", canonical_body)
            return 1

        run([sys.executable, "-m", "switchyard", "down", "--branch", "feature/demo"], repo, env)
        run([sys.executable, "-m", "switchyard", "proxy", "stop"], repo, env)
        print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

