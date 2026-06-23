from __future__ import annotations

import http.server
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from switchyard.config import EnvConfig, PortsConfig, ProjectConfig, ProxyConfig, ServiceConfig
from switchyard.proxy import SwitchyardProxyHandler
from switchyard.registry import Registry
from switchyard.utils import find_free_port


class Backend(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"hello from backend"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class ProxyTests(unittest.TestCase):
    def test_proxy_routes_by_host_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "home"
            backend_port = find_free_port()
            proxy_port = find_free_port(avoid=[backend_port])

            backend = http.server.ThreadingHTTPServer(("127.0.0.1", backend_port), Backend)
            backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
            backend_thread.start()

            registry = Registry(home)
            root = Path(temp) / "repo"
            root.mkdir()
            config = ProjectConfig(
                name="Demo",
                root=root,
                path=root / "switchyard.toml",
                worktree_root=None,
                env=EnvConfig(),
                proxy=ProxyConfig(port=proxy_port),
                ports=PortsConfig(),
                services={"web": ServiceConfig(name="web", command="dev")},
            )
            registry.ensure_project(config)
            registry.upsert_service(
                config,
                {
                    "branch": "feature/login",
                    "service": "web",
                    "hostname": "web.feature-login.demo.localhost",
                    "backend_host": "127.0.0.1",
                    "port": backend_port,
                    "pid": 123,
                },
            )

            SwitchyardProxyHandler.registry_home = home
            proxy = http.server.ThreadingHTTPServer(("127.0.0.1", proxy_port), SwitchyardProxyHandler)
            proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
            proxy_thread.start()

            request = urllib.request.Request(
                f"http://127.0.0.1:{proxy_port}/",
                headers={"Host": "web.feature-login.demo.localhost"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.read(), b"hello from backend")

            proxy.shutdown()
            proxy.server_close()
            backend.shutdown()
            backend.server_close()


if __name__ == "__main__":
    unittest.main()
