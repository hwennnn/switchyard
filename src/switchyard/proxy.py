from __future__ import annotations

import http.client
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

from .registry import Registry


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class SwitchyardProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    registry_home: ClassVar[Path | None] = None

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle(head_only=True)

    def do_OPTIONS(self) -> None:
        self._handle()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _handle(self, head_only: bool = False) -> None:
        if self.path == "/__switchyard/health":
            self._send_json(200, {"ok": True, "name": "switchyard-proxy"})
            return

        host = self.headers.get("Host", "")
        registry = Registry(self.registry_home)
        route = registry.find_route(host)
        if not route:
            self._send_text(502, f"Switchyard has no route for Host: {host}\n")
            return

        backend_host = route.get("backend_host", "127.0.0.1")
        backend_port = int(route["port"])
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None

        headers = {}
        for key, value in self.headers.items():
            if key.lower() not in HOP_BY_HOP and key.lower() != "host":
                headers[key] = value
        headers["Host"] = f"{backend_host}:{backend_port}"
        headers["X-Forwarded-Host"] = host
        headers["X-Forwarded-Proto"] = "http"
        headers["X-Switchyard-Service"] = str(route.get("service", ""))
        headers["X-Switchyard-Branch"] = str(route.get("branch", ""))

        conn = http.client.HTTPConnection(str(backend_host), backend_port, timeout=60)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            payload = b"" if head_only else response.read()
        except OSError as exc:
            self._send_text(502, f"Switchyard could not reach backend {backend_host}:{backend_port}: {exc}\n")
            return
        finally:
            conn.close()

        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() not in HOP_BY_HOP and key.lower() != "content-length":
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _send_json(self, code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, code: int, text: str) -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str, port: int, registry_home: Path | None = None) -> None:
    SwitchyardProxyHandler.registry_home = registry_home
    server = ThreadingHTTPServer((host, port), SwitchyardProxyHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


class FixedTargetProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    target_host: ClassVar[str] = "127.0.0.1"
    target_port: ClassVar[int] = 0

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle(head_only=True)

    def do_OPTIONS(self) -> None:
        self._handle()

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _handle(self, head_only: bool = False) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        headers = {}
        for key, value in self.headers.items():
            if key.lower() not in HOP_BY_HOP and key.lower() != "host":
                headers[key] = value
        headers["Host"] = f"{self.target_host}:{self.target_port}"
        headers["X-Forwarded-Host"] = self.headers.get("Host", "")
        headers["X-Forwarded-Proto"] = "http"

        conn = http.client.HTTPConnection(self.target_host, self.target_port, timeout=60)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            response = conn.getresponse()
            payload = b"" if head_only else response.read()
        except OSError as exc:
            self._send_text(502, f"Switchyard canonical forward failed: {exc}\n")
            return
        finally:
            conn.close()

        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() not in HOP_BY_HOP and key.lower() != "content-length":
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _send_text(self, code: int, text: str) -> None:
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_fixed(host: str, port: int, target_host: str, target_port: int) -> None:
    class Handler(FixedTargetProxyHandler):
        pass

    Handler.target_host = target_host
    Handler.target_port = target_port
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
