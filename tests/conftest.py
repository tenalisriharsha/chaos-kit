"""Shared fixtures: a stub Prometheus HTTP server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest


class _StubPrometheus:
    """Serves canned /api/v1/query responses and records queries."""

    def __init__(self):
        self._responses: list[dict] = []
        self.queries: list[str] = []
        self.url = ""

    def respond(self, payload: dict) -> None:
        self._responses.append(payload)

    def respond_value(self, value: float) -> None:
        self.respond(
            {
                "status": "success",
                "data": {"result": [{"value": [1700000000, str(value)]}]},
            }
        )


@pytest.fixture
def prometheus():
    stub = _StubPrometheus()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path != "/api/v1/query":
                self.send_error(404)
                return
            stub.queries.append(parse_qs(parsed.query).get("query", [""])[0])
            payload = stub._responses.pop(0) if stub._responses else {
                "status": "success",
                "data": {"result": []},
            }
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stub.url = f"http://127.0.0.1:{server.server_address[1]}"
    yield stub
    server.shutdown()
    thread.join(timeout=2)
