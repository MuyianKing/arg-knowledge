"""Serve the local debug console and proxy requests to the RAG engine.

The web page is plain static files, so this script only needs the standard
library. It proxies `/engine/*` to the engine to avoid CORS, and also forwards
`/docs`, `/redoc` and `/openapi.json` so the Swagger link works.

Usage:
    .venv/Scripts/python.exe scripts/dev_web.py
    .venv/Scripts/python.exe scripts/dev_web.py --port 8090 --engine http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

PROXY_PREFIX = "/engine"
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    # Do not negotiate compression: we forward the body verbatim and drop
    # content-encoding on the way back.
    "accept-encoding",
}

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")


class ConsoleHandler(BaseHTTPRequestHandler):
    server_version = "RAGDevWeb/1.0"
    protocol_version = "HTTP/1.1"
    engine_url = "http://127.0.0.1:8080"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write(f"[web] {self.address_string()} {fmt % args}\n")

    # ------------------------------------------------------------- dispatch

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:
        self._handle("OPTIONS")

    def _handle(self, method: str) -> None:
        split = urllib.parse.urlsplit(self.path)
        path = split.path
        query = f"?{split.query}" if split.query else ""
        if path == PROXY_PREFIX or path.startswith(PROXY_PREFIX + "/"):
            self._proxy(method, (path[len(PROXY_PREFIX) :] or "/") + query)
            return
        if path in {"/docs", "/redoc", "/openapi.json"}:
            self._proxy(method, path + query)
            return
        if method != "GET":
            self._send_json(405, {"detail": "Method Not Allowed"})
            return
        self._serve_static(path)

    # -------------------------------------------------------------- static

    def _serve_static(self, raw_path: str) -> None:
        relative = urllib.parse.unquote(raw_path).lstrip("/") or "index.html"
        try:
            candidate = (WEB_DIR / relative).resolve()
            candidate.relative_to(WEB_DIR.resolve())
        except (ValueError, OSError):
            self._send_json(404, {"detail": "Not Found"})
            return
        if not candidate.is_file():
            self._send_json(404, {"detail": "Not Found"})
            return

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # --------------------------------------------------------------- proxy

    def _proxy(self, method: str, upstream_path: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {
            key: value for key, value in self.headers.items() if key.lower() not in HOP_BY_HOP
        }
        target = self.engine_url.rstrip("/") + upstream_path
        request = urllib.request.Request(target, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
                extra = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() in {"cache-control", "location"}
                }
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
            extra = {}
        except Exception as exc:  # connection refused, timeout, DNS, ...
            payload = json.dumps(
                {"detail": f"引擎不可达（{target}）：{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            ).encode("utf-8")
            status = 502
            content_type = "application/json; charset=utf-8"
            extra = {}

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    # ---------------------------------------------------------------- util

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the RAG debug console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--engine", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    if not (WEB_DIR / "index.html").is_file():
        raise SystemExit(f"web/index.html not found under {WEB_DIR}")

    ConsoleHandler.engine_url = args.engine
    server = ThreadingHTTPServer((args.host, args.port), ConsoleHandler)

    print(f"Debug console : http://{args.host}:{args.port}")
    print(f"Engine proxy  : {args.engine}  (mounted at {PROXY_PREFIX})")
    print("Engine must run with DEV_TOOLS_ENABLED=true for retrieve/ingest/LLM config.")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
