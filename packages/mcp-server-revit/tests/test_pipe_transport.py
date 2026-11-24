"""Named-pipe transport (ADR 0021): framing, client behaviour and provider selection.

No Windows pipe is opened here. A socket pair stands in for the pipe and a thread plays the add-in,
so the framing and the client run against real cross-thread I/O. Live-Revit behaviour is UNVERIFIED.
"""
from __future__ import annotations

import io
import json
import socket
import struct
import threading
import time
from pathlib import Path

import httpx
import pytest

from revit_mcp_server.bridge import discovery, pipe_transport
from revit_mcp_server.bridge.client import BridgeClient
from revit_mcp_server.bridge.pipe_transport import (
    MAX_REQUEST_FRAME_BYTES,
    MAX_RESPONSE_FRAME_BYTES,
    PipeProtocolError,
    PipeTransport,
    encode_frame,
    read_frame,
    resolve_transport,
)
from revit_mcp_server.config import BridgeMode, Config
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.revit import RevitProvider, UnavailableBridge
from revit_mcp_server.security.workspace import WorkspaceMonitor

PIPE = "AECModelBridge-revit-4242-" + "ab" * 16
TOKEN = "t" * 64


# --- framing ----------------------------------------------------------------------------------------

def test_frame_is_little_endian_length_then_utf8_json():
    frame = encode_frame({"path": "/health", "name": "wand é"}, MAX_REQUEST_FRAME_BYTES)
    (length,) = struct.unpack("<I", frame[:4])
    assert length == len(frame) - 4
    assert json.loads(frame[4:].decode("utf-8")) == {"path": "/health", "name": "wand é"}
    assert read_frame(io.BytesIO(frame), MAX_REQUEST_FRAME_BYTES) == {"path": "/health", "name": "wand é"}


def test_oversize_frame_is_refused_on_write():
    with pytest.raises(PipeProtocolError, match="exceeds"):
        encode_frame({"x": "a" * 100}, 50)


def test_oversize_declared_length_is_refused_before_the_body_is_read():
    stream = io.BytesIO(struct.pack("<I", MAX_RESPONSE_FRAME_BYTES + 1))  # no body at all
    with pytest.raises(PipeProtocolError, match="exceeds"):
        read_frame(stream, MAX_RESPONSE_FRAME_BYTES)


@pytest.mark.parametrize("data", [b"", b"\x05\x00", struct.pack("<I", 10) + b"{}"])
def test_truncated_frame_is_refused(data):
    with pytest.raises(PipeProtocolError, match="incomplete"):
        read_frame(io.BytesIO(data), 100)


def test_frame_that_is_not_json_is_refused():
    with pytest.raises(PipeProtocolError, match="UTF-8 JSON"):
        read_frame(io.BytesIO(struct.pack("<I", 3) + b"\xff{]"), 100)


@pytest.mark.parametrize("message", [[], {"body": {}}, {"status": "200"}, {"status": True}])
def test_response_without_integer_status_is_refused(message):
    with pytest.raises(PipeProtocolError):
        pipe_transport.parse_response(message)


def test_protocol_errors_are_request_errors_so_client_retries_apply():
    assert issubclass(PipeProtocolError, httpx.RequestError)


# --- transport selection ----------------------------------------------------------------------------

def test_transport_defaults_to_http(monkeypatch):
    monkeypatch.delenv("AEC_BRIDGE_TRANSPORT", raising=False)
    assert resolve_transport(None) == "http"


def test_server_setting_wins_over_add_in_variable(monkeypatch):
    monkeypatch.setenv("AEC_BRIDGE_TRANSPORT", "pipe")
    assert resolve_transport(None) == "pipe"
    assert resolve_transport(" HTTP ") == "http"


def test_unknown_transport_is_refused(monkeypatch):
    monkeypatch.delenv("AEC_BRIDGE_TRANSPORT", raising=False)
    with pytest.raises(BridgeError, match="Unknown bridge transport"):
        resolve_transport("pipes")


def test_config_reads_mcp_revit_bridge_transport(monkeypatch):
    monkeypatch.setenv("MCP_REVIT_BRIDGE_TRANSPORT", "pipe")
    assert Config().bridge_transport == "pipe"


def test_registry_entry_carries_optional_pipe_name():
    base = dict(
        provider_id="revit", endpoint="http://127.0.0.1:39001", pid=4242, host_version="2026",
        connector_version="1.6.0", protocol_version=2, capability_digest="dynamic",
        session_token=TOKEN, started_at="2026-11-01T08:00:00Z",
    )
    assert discovery.SwitchInfo(**base).pipe_name is None
    assert discovery.SwitchInfo(**base, pipe_name=None).pipe_name is None
    assert discovery.SwitchInfo(**base, pipe_name=PIPE).pipe_name == PIPE


# --- client against a fake add-in -------------------------------------------------------------------

class FakeAddin:
    """Answers one frame per connection, like the add-in's PipeBridgeServer."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[dict] = []
        self.connections = 0

    def open(self, path: str):
        assert path == "\\\\.\\pipe\\" + PIPE
        self.connections += 1
        client_end, server_end = socket.socketpair()
        threading.Thread(target=self._serve, args=(server_end,), daemon=True).start()
        return client_end.makefile("rwb", buffering=0)

    def _serve(self, sock):
        with sock, sock.makefile("rwb", buffering=0) as stream:
            try:
                request = read_frame(stream, MAX_REQUEST_FRAME_BYTES)
            except PipeProtocolError:
                return
            self.requests.append(request)
            reply = self.handler(request)
            if reply is not None:
                stream.write(encode_frame(reply, MAX_RESPONSE_FRAME_BYTES))


def authorized(handler):
    def check(request):
        if request["path"] != "/health" and request["headers"].get("Authorization") != f"Bearer {TOKEN}":
            return {"status": 401, "body": {"error": "Unauthorized"}}
        return handler(request)
    return check


def pipe_client(addin, *, server_pid=lambda stream: 4242, timeout=5):
    client = BridgeClient("http://127.0.0.1:39001", token=TOKEN, timeout=timeout)
    client.use_pipe(PIPE, 4242, opener=addin.open, server_pid=server_pid, platform="nt")
    client._sleep = lambda seconds: None
    return client


def test_call_tool_goes_over_the_pipe_with_the_same_json_and_token():
    def handler(request):
        if request["path"] == "/execute":
            body = request["body"]
            return {"status": 200, "body": {"status": "ok", "tool": body["tool"], "result": {"wall_id": 7}}}
        return {"status": 404, "body": {"error": "Not found"}}

    addin = FakeAddin(authorized(handler))
    client = pipe_client(addin)
    assert client.transport == "pipe"
    result = client.call_tool("revit.create_wall", {"length": 3})
    assert result == {"wall_id": 7, "element_id": 7}
    (request,) = addin.requests
    assert request["method"] == "POST" and request["path"] == "/execute"
    assert request["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    assert request["body"]["tool"] == "revit.create_wall" and request["body"]["payload"] == {"length": 3}
    assert set(request["body"]) == {"tool", "payload", "request_id", "wait_ms"}


def test_initialize_reads_health_and_tools_over_the_pipe():
    def handler(request):
        if request["path"] == "/health":
            return {"status": 200, "body": {"status": "healthy"}}
        return {"status": 200, "body": {"tools": ["revit.ping"]}}

    addin = FakeAddin(authorized(handler))
    client = pipe_client(addin)
    client.initialize()
    assert client._tool_catalog == ["revit.ping"]
    assert [r["method"] for r in addin.requests] == ["GET", "GET"]
    assert addin.connections == 2  # one request per connection


def test_wrong_token_surfaces_as_http_status_error():
    addin = FakeAddin(authorized(lambda request: {"status": 200, "body": {}}))
    client = pipe_client(addin)
    client.token = "wrong"
    with pytest.raises(httpx.HTTPStatusError) as caught:
        client._get("/tools")
    assert caught.value.response.status_code == 401


def test_unknown_request_id_over_the_pipe_keeps_the_http_message():
    addin = FakeAddin(authorized(lambda request: {"status": 404, "body": {"error": "unknown_or_expired"}}))
    client = pipe_client(addin)
    with pytest.raises(BridgeError, match="unknown to the add-in"):
        client.get_result("abc", wait_s=0)


def test_pipe_served_by_another_process_gets_no_token():
    addin = FakeAddin(lambda request: {"status": 200, "body": {}})
    client = pipe_client(addin, server_pid=lambda stream: 999)
    with pytest.raises(BridgeError, match="not by the Revit process 4242"):
        client._get("/tools")
    time.sleep(0.05)
    assert addin.requests == []


def test_missing_pipe_is_retried_then_reported():
    attempts = []

    def opener(path):
        attempts.append(path)
        raise FileNotFoundError(2, "The system cannot find the file specified")

    client = BridgeClient("http://127.0.0.1:39001", token=TOKEN)
    client.use_pipe(PIPE, 4242, opener=opener, server_pid=lambda s: 4242, platform="nt")
    client._sleep = lambda seconds: None
    with pytest.raises(BridgeError, match="failed after 3 attempts"):
        client.call_tool("revit.ping", {})
    assert len(attempts) == 3


def test_busy_pipe_is_retried_until_an_instance_is_free():
    addin = FakeAddin(lambda request: {"status": 200, "body": {"tools": []}})
    busy = []
    for _ in range(2):
        error = OSError("All pipe instances are busy")
        error.winerror = 231  # ERROR_PIPE_BUSY, as Windows reports it
        busy.append(error)

    def opener(path):
        if busy:
            raise busy.pop()
        return addin.open(path)

    transport = PipeTransport(PIPE, 4242, opener=opener, server_pid=lambda s: 4242, platform="nt")
    transport._sleep = lambda seconds: None
    assert transport.request("GET", "/tools", TOKEN) == (200, {"tools": []})


def test_silent_add_in_times_out_as_read_timeout():
    addin = FakeAddin(lambda request: (time.sleep(1), None)[1])
    transport = PipeTransport(PIPE, 4242, timeout=0.2, opener=addin.open, server_pid=lambda s: 4242, platform="nt")
    with pytest.raises(httpx.ReadTimeout):
        transport.request("GET", "/health", None)


def test_oversize_request_is_refused_before_sending():
    addin = FakeAddin(lambda request: {"status": 200, "body": {}})
    transport = PipeTransport(PIPE, 4242, opener=addin.open, server_pid=lambda s: 4242, platform="nt")
    with pytest.raises(PipeProtocolError, match="exceeds"):
        transport.request("POST", "/execute", TOKEN, {"blob": "a" * MAX_REQUEST_FRAME_BYTES})
    time.sleep(0.05)
    assert addin.requests == []


def test_pipe_transport_refuses_off_windows():
    with pytest.raises(BridgeError, match="only on Windows"):
        PipeTransport(PIPE, 4242, platform="posix")


@pytest.mark.parametrize("name", ["", "other-pipe", "AECModelBridge-revit-1-xyz", "..\\x", PIPE + "\\x"])
def test_invalid_pipe_name_is_refused(name):
    with pytest.raises(BridgeError, match="invalid pipe name"):
        PipeTransport(name, 4242, platform="nt")


def test_registry_session_check_includes_the_pipe_name(monkeypatch):
    def entry(pipe_name):
        return discovery.SwitchInfo(
            provider_id="revit", endpoint="http://127.0.0.1:39001", pid=4242, host_version="2026",
            connector_version="1.6.0", protocol_version=2, capability_digest="dynamic",
            session_token=TOKEN, started_at="2026-11-01T08:00:00Z", pipe_name=pipe_name,
        )

    live = [entry(PIPE)]
    monkeypatch.setattr(discovery, "discover_switch_list", lambda **kwargs: live)
    client = BridgeClient("http://127.0.0.1:39001", token=TOKEN)
    client.bind_registry_session(live[0])
    client._check_registry_session()
    live[:] = [entry("AECModelBridge-revit-4242-" + "cd" * 16)]
    with pytest.raises(BridgeError, match="changed or closed"):
        client._check_registry_session()


# --- provider selection -----------------------------------------------------------------------------

class RecordingBridge:
    def __init__(self, url, token=None):
        self.url, self.token = url, token
        self.pipe = None

    def bind_registry_session(self, switch):
        pass

    def use_pipe(self, pipe_name, pid):
        self.pipe = (pipe_name, pid)

    def initialize(self):
        pass


def _switch(pipe_name):
    return discovery.SwitchInfo(
        provider_id="revit", endpoint="http://127.0.0.1:39001", pid=4242, host_version="2026",
        connector_version="1.6.0", protocol_version=2, capability_digest="dynamic",
        session_token=TOKEN, started_at="2026-11-01T08:00:00Z", pipe_name=pipe_name,
    )


def _provider(tmp_path, monkeypatch, *, transport, pipe_name, platform="nt"):
    monkeypatch.setattr(discovery, "select_switch", lambda *a, **k: _switch(pipe_name))
    monkeypatch.setattr(pipe_transport, "PLATFORM", platform)
    monkeypatch.delenv("AEC_BRIDGE_TRANSPORT", raising=False)
    return RevitProvider(
        WorkspaceMonitor([tmp_path]), BridgeMode.bridge, bridge_url=None,
        bridge_factory=RecordingBridge, bridge_transport=transport,
    )


def test_default_transport_stays_http(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, transport=None, pipe_name=PIPE)
    assert provider._bridge.pipe is None


def test_pipe_transport_uses_the_registry_pipe_and_pid(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, transport="pipe", pipe_name=PIPE)
    assert provider._bridge.pipe == (PIPE, 4242)


def test_pipe_requested_but_not_published_falls_back_to_http_with_a_warning(tmp_path, monkeypatch, caplog):
    with caplog.at_level("WARNING"):
        provider = _provider(tmp_path, monkeypatch, transport="pipe", pipe_name=None)
    assert provider._bridge.pipe is None and provider._bridge.url == "http://127.0.0.1:39001"
    assert "Falling back to HTTP" in caplog.text


def test_pipe_transport_off_windows_refuses(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, transport="pipe", pipe_name=PIPE, platform="posix")
    assert isinstance(provider._bridge, UnavailableBridge)
    assert "only on Windows" in provider._bridge.message


def test_unknown_transport_makes_the_bridge_unavailable(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, transport="tcp", pipe_name=PIPE)
    assert isinstance(provider._bridge, UnavailableBridge)
    assert "Unknown bridge transport" in provider._bridge.message


# --- add-in source guards (C# is not built in this container) --------------------------------------

ADDIN = Path(__file__).resolve().parents[3] / "packages" / "revit-bridge-addin" / "src" / "Bridge"


def _cs(name: str) -> str:
    return (ADDIN / name).read_text(encoding="utf-8")


def test_addin_pipe_is_opt_in_and_published_in_the_registry():
    server = _cs("BridgeServer.cs")
    assert "PipeBridgeServer.IsRequested()" in server
    assert server.index("PipeBridgeServer.IsRequested()") < server.index("WriteRegistryFile(prefix)")
    assert "pipe_name = _pipe != null && _pipe.IsListening ? _pipe.PipeName : null" in server
    assert "_pipe?.Stop()" in server
    pipe = _cs("PipeBridgeServer.cs")
    assert '"AEC_BRIDGE_TRANSPORT"' in pipe and '"pipe"' in pipe


def test_addin_pipe_acl_allows_only_the_current_user():
    pipe = _cs("PipeBridgeServer.cs")
    assert "WindowsIdentity.GetCurrent()" in pipe and "new PipeAccessRule(user, PipeAccessRights.FullControl" in pipe
    assert "SetAccessRuleProtection(true, false)" in pipe
    assert pipe.count("AddAccessRule(") == 1
    assert "WellKnownSidType" not in pipe and "Everyone" not in pipe
    assert "#if NETFRAMEWORK" in pipe
    assert "PipeOptions.Asynchronous, BufferSize, BufferSize, _security)" in pipe
    assert "NamedPipeServerStreamAcl.Create(" in pipe


def test_addin_pipe_name_has_pid_and_random_part_matching_the_client_rule():
    pipe = _cs("PipeBridgeServer.cs")
    assert '"AECModelBridge-revit-" + pid + "-" + Guid.NewGuid().ToString("N")' in pipe
    assert pipe_transport.PIPE_NAME_RE.match("AECModelBridge-revit-12345-" + "0123456789abcdef" * 2)


def test_addin_pipe_checks_the_token_before_routing_and_uses_the_command_queue():
    pipe = _cs("PipeBridgeServer.cs")
    dispatch = pipe[pipe.index("private async Task<string> Dispatch("):]
    assert dispatch.index("Unauthorized") < dispatch.index('"/tools"') < dispatch.index('"/execute"')
    assert 'path != "/health" && !PipeFraming.TokenMatches(auth, "Bearer " + _owner.SessionToken)' in dispatch
    assert "PayloadPathValidator.Validate(payload" in pipe
    assert pipe.index("PayloadPathValidator.Validate(payload") < pipe.index("queue.Enqueue(")
    assert "_externalEvent.Raise()" in pipe and "WaitForResponse(requestId, waitMs)" in pipe


def test_frame_limits_match_on_both_sides():
    framing = _cs("PipeFraming.cs")
    assert "MaxRequestFrameBytes = 5 * 1024 * 1024" in framing and MAX_REQUEST_FRAME_BYTES == 5 * 1024 * 1024
    assert "MaxResponseFrameBytes = 64 * 1024 * 1024" in framing and MAX_RESPONSE_FRAME_BYTES == 64 * 1024 * 1024
    assert "throw new InvalidDataException" in framing
    assert "header[0] | (header[1] << 8) | (header[2] << 16) | (header[3] << 24)" in framing
