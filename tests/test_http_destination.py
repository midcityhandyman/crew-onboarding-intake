"""HttpDestination against a stub server on 127.0.0.1. No real service is contacted."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from crew_intake.destinations import HttpDestination, PermanentError, TransientError

# page key -> (status code, raw response body)
REPLIES = {
    "crew-0001": (200, b'{"id": "remote-1"}'),
    "crew-0002": (200, b"OK"),
    "crew-0003": (204, b""),
    "crew-0004": (422, b"{}"),
    "crew-0005": (401, b"{}"),
    "crew-0006": (429, b"{}"),
    "crew-0007": (503, b"{}"),
    "crew-0008": (200, b"[1, 2]"),
}


class Stub(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def do_PUT(self):  # noqa: N802
        key = self.path.rsplit("/", 1)[-1]
        body = self.rfile.read(int(self.headers["Content-Length"]))
        Stub.seen.append(
            {"path": self.path, "auth": self.headers["Authorization"], "body": json.loads(body)}
        )
        code, reply = REPLIES[key]
        self.send_response(code)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


@pytest.fixture
def dest():
    server = HTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    Stub.seen = []
    yield HttpDestination(f"http://127.0.0.1:{server.server_port}/", "test-key", timeout=5)
    server.shutdown()
    server.server_close()
    thread.join()


def test_put_sends_payload_and_token_and_returns_remote_id(dest):
    assert dest.upsert_page("crew-0001", {"name": "Alex Sample"}) == "remote-1"
    assert Stub.seen == [
        {"path": "/pages/crew-0001", "auth": "Bearer test-key", "body": {"name": "Alex Sample"}}
    ]


@pytest.mark.parametrize("key", ["crew-0002", "crew-0003", "crew-0008"])
def test_success_without_a_json_id_falls_back_to_the_page_key(dest, key):
    assert dest.upsert_page(key, {}) == key


@pytest.mark.parametrize("key", ["crew-0004", "crew-0005"])
def test_client_errors_are_permanent(dest, key):
    with pytest.raises(PermanentError):
        dest.upsert_page(key, {})


@pytest.mark.parametrize("key", ["crew-0006", "crew-0007"])
def test_rate_limit_and_server_errors_are_transient(dest, key):
    with pytest.raises(TransientError):
        dest.upsert_page(key, {})


def test_connection_refused_is_transient():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(TransientError):
        HttpDestination(f"http://127.0.0.1:{port}", "test-key", timeout=2).upsert_page("k", {})
