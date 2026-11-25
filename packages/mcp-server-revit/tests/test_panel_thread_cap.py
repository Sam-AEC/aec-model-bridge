"""Panel hub thread cap: BoundedThreadingHTTPServer and AEC_PANEL_MAX_THREADS."""
from __future__ import annotations

import json
import logging
import socket
import threading
import time

import pytest

from revit_mcp_server import panel_server
from revit_mcp_server.panel_server import (
    DEFAULT_MAX_THREADS,
    BoundedThreadingHTTPServer,
    PanelRequestHandler,
    build_server,
    max_threads_from_env,
)
from revit_mcp_server.security.workspace import WorkspaceMonitor


def _wait_for(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached in time")


def _make_handler(release: threading.Event, entered: list) -> type:
    """A PanelRequestHandler (so the reserved-slot check applies) whose routes block until released."""

    class BlockingHandler(PanelRequestHandler):
        def _answer(self) -> None:
            entered.append(self.path)
            if self.path.startswith("/boom"):
                raise RuntimeError("handler fault")
            release.wait(10)
            self._send_json(200, {"ok": True, "path": self.path})

        def do_GET(self) -> None:  # noqa: N802
            self._answer()

        def do_POST(self) -> None:  # noqa: N802
            self._answer()

    return BlockingHandler


class _QuietServer(BoundedThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        pass


@pytest.fixture
def capped():
    release = threading.Event()
    entered: list = []
    server = _QuietServer(("127.0.0.1", 0), _make_handler(release, entered), max_threads=3, reserved_execute=1)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server, release, entered
    finally:
        release.set()
        server.shutdown()
        server.server_close()


def _send(port: int, method: str, path: str) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    body = b"{}" if method == "POST" else b""
    sock.sendall(
        f"{method} {path} HTTP/1.0\r\nHost: 127.0.0.1\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
    )
    return sock


def _read_all(sock: socket.socket) -> bytes:
    chunks = []
    with sock:
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks)


def _status_headers_body(raw: bytes):
    head, _, body = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {k.strip().lower(): v.strip() for k, v in (line.split(":", 1) for line in lines[1:])}
    return status, headers, body


def test_full_cap_answers_503_without_a_new_thread(capped):
    server, release, entered = capped
    port = server.server_address[1]
    held = [_send(port, "GET", "/a"), _send(port, "GET", "/b"), _send(port, "POST", "/execute")]
    _wait_for(lambda: len(entered) == 3)
    assert server.active_threads == 3

    threads_before = threading.active_count()
    extra = socket.create_connection(("127.0.0.1", port), timeout=5)
    raw = _read_all(extra)
    status, headers, body = _status_headers_body(raw)
    assert status == 503
    assert headers["retry-after"] == "1"
    assert headers["content-type"] == "application/json"
    payload = json.loads(body)
    assert payload == {"ok": False, "kind": "hub_busy", "error": panel_server.BUSY_ERROR}
    assert threading.active_count() == threads_before
    assert server.active_threads == 3
    assert server.refused_busy == 1

    release.set()
    for sock in held:
        assert _status_headers_body(_read_all(sock))[0] == 200
    _wait_for(lambda: server.active_threads == 0)


def test_full_cap_refuses_a_client_that_already_sent_its_request(capped):
    server, release, entered = capped
    port = server.server_address[1]
    held = [_send(port, "GET", "/a"), _send(port, "GET", "/b"), _send(port, "POST", "/execute")]
    _wait_for(lambda: len(entered) == 3)
    status, headers, _ = _status_headers_body(_read_all(_send(port, "POST", "/execute")))
    assert status == 503 and headers["retry-after"] == "1"
    release.set()
    for sock in held:
        _read_all(sock)


def test_reserved_slot_serves_execute_only(capped):
    server, release, entered = capped
    port = server.server_address[1]
    held = [_send(port, "GET", "/a"), _send(port, "GET", "/b")]
    _wait_for(lambda: len(entered) == 2)

    # General slots are full; the reserved slot refuses another route.
    status, headers, body = _status_headers_body(_read_all(_send(port, "GET", "/health")))
    assert status == 503
    assert headers["retry-after"] == "1"
    assert json.loads(body)["kind"] == "hub_busy"
    assert "/health" not in entered
    _wait_for(lambda: server.active_threads == 2)

    # ...but takes /execute.
    execute = _send(port, "POST", "/execute")
    _wait_for(lambda: "/execute" in entered)
    assert server.active_threads == 3

    release.set()
    assert _status_headers_body(_read_all(execute))[0] == 200
    for sock in held:
        _read_all(sock)


def test_slots_are_released_after_requests_and_exceptions(capped):
    server, release, entered = capped
    release.set()
    port = server.server_address[1]
    for i in range(server.max_threads + 3):
        path = f"/boom{i}" if i % 2 else f"/ok{i}"
        raw = _read_all(_send(port, "GET", path))
        if not path.startswith("/boom"):
            assert _status_headers_body(raw)[0] == 200
    _wait_for(lambda: server.active_threads == 0)
    assert server.refused_busy == 0
    # Every slot is free again: all of them can be held at once.
    release.clear()
    held = [_send(port, "GET", "/x"), _send(port, "GET", "/y"), _send(port, "POST", "/execute")]
    _wait_for(lambda: server.active_threads == 3)
    release.set()
    for sock in held:
        assert _status_headers_body(_read_all(sock))[0] == 200


def test_constructor_needs_more_slots_than_reserved():
    with pytest.raises(ValueError):
        BoundedThreadingHTTPServer(("127.0.0.1", 0), PanelRequestHandler, max_threads=2, reserved_execute=2,
                                   bind_and_activate=False)


@pytest.mark.parametrize("raw,expected", [(None, 32), ("", 32), ("4", 4), ("256", 256), (" 64 ", 64)])
def test_max_threads_from_env_accepts_valid_values(raw, expected, caplog):
    env = {} if raw is None else {"AEC_PANEL_MAX_THREADS": raw}
    with caplog.at_level(logging.WARNING, logger="revit_mcp_server.panel_server"):
        assert max_threads_from_env(env) == expected
    assert not caplog.records


@pytest.mark.parametrize("raw", ["abc", "3", "257", "-1", "0", "12.5"])
def test_max_threads_from_env_bad_value_falls_back_with_warning(raw, caplog):
    with caplog.at_level(logging.WARNING, logger="revit_mcp_server.panel_server"):
        assert max_threads_from_env({"AEC_PANEL_MAX_THREADS": raw}) == DEFAULT_MAX_THREADS
    assert any("AEC_PANEL_MAX_THREADS" in r.getMessage() for r in caplog.records)


def test_build_server_reads_the_cap_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AEC_PANEL_MAX_THREADS", "8")
    server = build_server(port=0, workspace=WorkspaceMonitor([tmp_path]), token="t" * 32)
    try:
        assert isinstance(server, BoundedThreadingHTTPServer)
        assert server.max_threads == 8
        assert server.reserved_execute == panel_server.RESERVED_EXECUTE_SLOTS
        assert server.daemon_threads is True
    finally:
        server.server_close()


def test_incomplete_headers_cannot_hold_a_reserved_slot(capped, monkeypatch):
    """#336 review: a client that never finishes its headers on a reserved slot is dropped after a short
    timeout, so a later /execute still gets the slot."""
    monkeypatch.setattr(panel_server, "RESERVED_HEADER_TIMEOUT_SECONDS", 0.3)
    server, release, entered = capped
    port = server.server_address[1]
    held = [_send(port, "GET", "/a"), _send(port, "GET", "/b")]
    _wait_for(lambda: len(entered) == 2)

    slow = socket.create_connection(("127.0.0.1", port), timeout=5)
    slow.sendall(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n")  # never ends its headers
    _wait_for(lambda: server.active_threads == 3)
    _wait_for(lambda: server.active_threads == 2, timeout=5.0)  # dropped after the short timeout
    slow.close()

    execute = _send(port, "POST", "/execute")
    _wait_for(lambda: "/execute" in entered)
    release.set()
    assert _status_headers_body(_read_all(execute))[0] == 200
    for sock in held:
        _read_all(sock)
