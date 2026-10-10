"""Panel hub access token (finding H1) and multi-Revit instance routing.

UNVERIFIED: nothing here runs Revit, WebView2 or the C# add-in. Windows ACL handling
(icacls) is not exercised on this platform; the POSIX permission checks are.
"""
from __future__ import annotations

import http.client
import json
import logging
import os
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server import panel_server
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.panel_server import build_server
from revit_mcp_server.security import panel_token
from revit_mcp_server.security.audit import redact_data
from revit_mcp_server.security.panel_token import PanelTokenError, load_or_create_token, read_token
from revit_mcp_server.security.workspace import WorkspaceMonitor

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")


@pytest.fixture(autouse=True)
def _no_real_agents(monkeypatch):
    """/agent/chat must never start a real CLI or call the API from these tests."""
    fake = lambda *a, **k: {"ok": True, "response": "stub", "session_id": "s"}  # noqa: E731
    monkeypatch.setattr(panel_server.agent_bridge, "run_agent_turn", fake)
    monkeypatch.setattr(panel_server.agent_native, "run_native_turn", fake)


@pytest.fixture
def hub(tmp_path):
    server = build_server(port=0, workspace=WorkspaceMonitor([tmp_path / "ws"]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], read_token()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _call(port, method, path, token=None, body=None, extra=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-AMB-Token"] = token
        headers.update(extra or {})
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, raw, (json.loads(raw) if raw else {})
    finally:
        conn.close()


ROUTES = [
    ("POST", "/execute", {"tool": "list_pending_plans", "arguments": {}}),
    ("POST", "/agent/chat", {"message": "hi"}),
    ("GET", "/diagnostics", None),
    ("GET", "/reports", None),
    ("GET", "/agent/providers", None),
    ("GET", "/no-such-route", None),
]


# --- the token gate -----------------------------------------------------------


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_missing_token_is_401_with_plain_body(hub, method, path, body):
    port, _ = hub
    status, raw, parsed = _call(port, method, path, None, body)
    assert status == 401
    assert parsed == {"ok": False, "error": "Unauthorized"}


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_wrong_token_is_401_same_as_missing(hub, method, path, body):
    port, token = hub
    wrong = ("A" if token[0] != "A" else "B") + token[1:]
    status, raw_wrong, _ = _call(port, method, path, wrong, body)
    _, raw_missing, _ = _call(port, method, path, None, body)
    assert status == 401
    assert raw_wrong == raw_missing  # the response does not say which part was wrong


def test_right_token_runs_execute(hub):
    port, token = hub
    status, _, body = _call(port, "POST", "/execute", token, {"tool": "list_pending_plans", "arguments": {}})
    assert status == 200 and body["ok"] is True


@pytest.mark.parametrize("method,path,body", [r for r in ROUTES if r[1] != "/no-such-route"])
def test_right_token_is_accepted_on_every_route(hub, method, path, body):
    port, token = hub
    status, _, _ = _call(port, method, path, token, body)
    assert status != 401


def test_unknown_path_with_right_token_is_404(hub):
    port, token = hub
    assert _call(port, "GET", "/no-such-route", token)[0] == 404


def test_health_stays_minimal_and_needs_no_token(hub):
    port, _ = hub
    status, raw, body = _call(port, "GET", "/health")
    assert (status, body) == (200, {"status": "healthy"})
    # Nothing about the install in the unauthenticated response.
    assert set(body) == {"status"}


def test_token_cannot_be_sent_other_ways(hub):
    port, token = hub
    assert _call(port, "GET", "/diagnostics", None, extra={"Authorization": f"Bearer {token}"})[0] == 401
    assert _call(port, "GET", f"/diagnostics?token={token}")[0] == 401


def test_overlong_token_header_is_rejected_without_compare(hub):
    port, _ = hub
    assert _call(port, "GET", "/diagnostics", "x" * 5000)[0] == 401


def test_host_and_origin_checks_still_run_before_the_token(hub):
    port, token = hub
    assert _call(port, "GET", "/diagnostics", token, extra={"Origin": "https://evil.example"})[0] == 403
    assert _call(port, "GET", "/diagnostics", token, extra={"Host": "evil.example"})[0] == 403


def test_comparison_uses_hmac_compare_digest(hub, monkeypatch):
    port, token = hub
    calls = []
    real = panel_server.hmac.compare_digest

    def spy(a, b):
        calls.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(panel_server.hmac, "compare_digest", spy)
    _call(port, "GET", "/diagnostics", token)
    _call(port, "GET", "/diagnostics", "wrong-token")
    assert len(calls) >= 2 and set(calls) == {(bytes, bytes)}


def test_token_is_never_compared_with_equality_operators():
    import inspect

    src = inspect.getsource(panel_server.PanelRequestHandler._check_token)
    assert "compare_digest" in src
    assert "== expected" not in src and "== self.token" not in src and "supplied ==" not in src


def test_hub_without_a_token_refuses_everything(tmp_path):
    handler = type("H", (panel_server.PanelRequestHandler,), {"token": None, "failures": None})
    fake = SimpleNamespace(token=None, failures=None, headers={"X-AMB-Token": "anything"})
    rejected = []
    fake._reject = lambda status, error: rejected.append((status, error)) or False
    fake._warn_if_token_file_changed = lambda: None
    assert handler._check_token(fake) is False
    assert rejected == [(401, "Unauthorized")]


def test_build_server_refuses_to_start_with_empty_token(tmp_path):
    with pytest.raises(PanelTokenError):
        build_server(port=0, workspace=WorkspaceMonitor([tmp_path]), token="")


def test_failure_rate_limit_never_locks_out_the_real_caller(hub):
    port, token = hub
    statuses = [_call(port, "GET", "/diagnostics", "bad")[0] for _ in range(25)]
    assert statuses[:20] == [401] * 20
    assert set(statuses[20:]) == {429}
    # the legitimate caller is not counted and is not limited
    assert _call(port, "GET", "/diagnostics", token)[0] == 200


def test_oversized_body_is_refused_after_auth(hub):
    port, token = hub
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.putrequest("POST", "/execute")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("X-AMB-Token", token)
        conn.putheader("Content-Length", str(5_000_000))
        conn.endheaders()
        assert conn.getresponse().status == 413
    finally:
        conn.close()


# --- the token file -------------------------------------------------------------


@posix_only
def test_token_file_is_created_0600_with_a_32_byte_token(tmp_path):
    path = tmp_path / "sub" / "panel-hub.token"
    token = load_or_create_token(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert panel_token.is_valid_token(token) and len(token) == 43  # token_urlsafe(32)
    assert path.read_text().strip() == token
    assert load_or_create_token(path) == token  # a second hub reads the same one
    assert [p.name for p in path.parent.iterdir()] == ["panel-hub.token"]  # no temp file left behind


@posix_only
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666, 0o660])
def test_group_or_world_accessible_token_file_is_refused(tmp_path, mode):
    path = tmp_path / "panel-hub.token"
    token = load_or_create_token(path)
    os.chmod(path, mode)
    with pytest.raises(PanelTokenError) as exc:
        read_token(path)
    assert token not in str(exc.value)
    with pytest.raises(PanelTokenError):
        load_or_create_token(path)


@posix_only
def test_hub_will_not_start_on_a_world_readable_token_file(tmp_path, monkeypatch):
    path = tmp_path / "loose.token"
    monkeypatch.setenv("MCP_PANEL_TOKEN_FILE", str(path))
    load_or_create_token()
    os.chmod(path, 0o644)
    with pytest.raises(PanelTokenError):
        build_server(port=0, workspace=WorkspaceMonitor([tmp_path / "ws"]))


@posix_only
def test_symlinked_token_file_is_refused(tmp_path):
    real = tmp_path / "real.token"
    load_or_create_token(real)
    link = tmp_path / "link.token"
    link.symlink_to(real)
    with pytest.raises(PanelTokenError):
        read_token(link)


@pytest.mark.parametrize("content", ["", "short", "x" * 44, "not a valid token!" + "a" * 30])
def test_malformed_token_file_is_refused(tmp_path, content):
    path = tmp_path / "panel-hub.token"
    path.write_text(content)
    if os.name != "nt":
        os.chmod(path, 0o600)
    with pytest.raises(PanelTokenError) as exc:
        read_token(path)
    assert "delete it" in str(exc.value)


def test_missing_file_reads_as_none(tmp_path):
    assert read_token(tmp_path / "nope.token") is None


def test_concurrent_first_start_creates_one_file_and_one_token(tmp_path):
    path = tmp_path / "AECModelBridge" / "panel-hub.token"
    n = 12
    barrier = threading.Barrier(n)
    results, errors = [], []

    def start():
        try:
            barrier.wait()
            results.append(load_or_create_token(path))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=start) for _ in range(n)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert not errors
    assert len(results) == n and len(set(results)) == 1
    assert [p.name for p in path.parent.iterdir()] == ["panel-hub.token"]


def test_rotation_by_deleting_the_file_yields_a_new_token(tmp_path):
    path = tmp_path / "panel-hub.token"
    first = load_or_create_token(path)
    path.unlink()
    assert load_or_create_token(path) != first


def test_default_path_lives_beside_the_registry_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_PANEL_TOKEN_FILE")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert panel_token.token_path() == tmp_path / "AECModelBridge" / "panel-hub.token"


# --- the token never leaks ------------------------------------------------------


def test_token_never_appears_in_logs_responses_diagnostics_or_errors(hub, tmp_path, caplog):
    port, token = hub
    caplog.set_level(logging.DEBUG)
    seen = []
    for tok in (token, "wrong", None):
        for method, path, body in ROUTES:
            _, raw, _ = _call(port, method, path, tok, body)
            seen.append(raw.decode())
    # an execute that fails and one whose arguments carry the token
    seen.append(_call(port, "POST", "/execute", token, {"tool": "not_a_tool", "arguments": {"note": token}})[1].decode())
    seen.append(_call(port, "GET", "/diagnostics", token)[1].decode())
    assert all(token not in text for text in seen)
    assert token not in caplog.text
    assert all(token not in r.getMessage() for r in caplog.records)
    for p in tmp_path.rglob("*"):
        if p.is_file() and p.name != "panel-hub.token":
            assert token not in p.read_text(errors="ignore"), p  # plans/, proofs/, audit logs, workspace


def test_stale_hub_logs_a_restart_hint_without_the_token(hub, tmp_path, caplog):
    port, token = hub
    # rotation: the file now holds a different token than the running hub
    path = panel_token.token_path()
    path.unlink()
    new = load_or_create_token(path)
    caplog.set_level(logging.WARNING)
    assert _call(port, "GET", "/diagnostics", new)[0] == 401
    assert "Restart the hub" in caplog.text
    assert token not in caplog.text and new not in caplog.text


def test_redact_data_masks_the_token_by_value_and_by_header_name(tmp_path):
    token = load_or_create_token(tmp_path / "t.token")
    assert token not in json.dumps(redact_data({"note": f"sent {token} to hub"}))
    assert redact_data({"X-AMB-Token": token}) == {"X-AMB-Token": "<redacted>"}
    assert token not in redact_data(f"failed: {token}")


def test_file_log_handler_masks_the_token(tmp_path):
    token = load_or_create_token(tmp_path / "t.token")
    log_file = tmp_path / "Logs" / "panel-hub.log"
    panel_server.configure_file_logging(log_file)
    pkg_logger = logging.getLogger("revit_mcp_server")
    try:
        logging.getLogger("revit_mcp_server.panel_server").error("oops %s", token)
        for h in pkg_logger.handlers:
            h.flush()
        text = log_file.read_text(encoding="utf-8")
        assert "oops" in text and token not in text
    finally:
        for h in list(pkg_logger.handlers):
            if getattr(h, "baseFilename", None) == str(log_file):
                pkg_logger.removeHandler(h)
                h.close()


# --- multi-Revit instance routing -----------------------------------------------


def _switch(pid, version="2026", started="2026-01-01T10:00:00+00:00"):
    from revit_mcp_server.bridge.discovery import SwitchInfo

    return SwitchInfo(
        provider_id="revit", endpoint=f"http://127.0.0.1:{4000 + pid % 1000}", pid=pid, host_version=version,
        connector_version="1", protocol_version=2, capability_digest="dynamic",
        session_token=f"bridge-secret-{pid}", started_at=started,
    )


@pytest.fixture
def bridge_mode(monkeypatch):
    monkeypatch.setattr(panel_server.config, "mode", BridgeMode.bridge)
    monkeypatch.setattr(panel_server.config, "bridge_url", None)


def _live(monkeypatch, *switches):
    monkeypatch.setattr("revit_mcp_server.bridge.discovery.discover_switch_list", lambda *_a, **_k: list(switches))


def test_two_revits_and_no_instance_is_refused_with_a_listing(bridge_mode, monkeypatch):
    _live(monkeypatch, _switch(111, "2024"), _switch(222, "2026"))
    with pytest.raises(panel_server.InstanceRoutingError) as exc:
        panel_server.resolve_instance(None, "revit_get_document_info")
    msg = str(exc.value)
    assert "111" in msg and "222" in msg and "2024" in msg and "2026" in msg
    assert "bridge-secret" not in msg and "127.0.0.1" not in msg  # no endpoints or bridge tokens


def test_single_live_instance_is_the_default(bridge_mode, monkeypatch):
    _live(monkeypatch, _switch(111))
    assert panel_server.resolve_instance(None, "revit_get_document_info").pid == 111


def test_explicit_instance_picks_that_revit(bridge_mode, monkeypatch):
    _live(monkeypatch, _switch(111, "2024"), _switch(222, "2026"))
    assert panel_server.resolve_instance({"pid": 111, "document": "House.rvt"}, "execute_plan").pid == 111


def test_unknown_pid_is_refused_not_guessed(bridge_mode, monkeypatch):
    _live(monkeypatch, _switch(111), _switch(222))
    with pytest.raises(panel_server.InstanceRoutingError) as exc:
        panel_server.resolve_instance({"pid": 999}, "revit_get_document_info")
    assert "999" in str(exc.value) and "111" in str(exc.value)


@pytest.mark.parametrize("bad", ["111", {"pid": "111"}, {"pid": True}, {}, [], 5])
def test_malformed_instance_is_refused(bridge_mode, monkeypatch, bad):
    _live(monkeypatch, _switch(111))
    with pytest.raises(panel_server.InstanceRoutingError):
        panel_server.resolve_instance(bad, "revit_get_document_info")


def test_hub_local_tools_need_no_instance_even_with_two_revits(bridge_mode, monkeypatch):
    _live(monkeypatch, _switch(111), _switch(222))
    for tool in ("list_pending_plans", "approve_plan", "reject_plan", "plan_actions"):
        assert panel_server.resolve_instance(None, tool) is None


def test_no_routing_in_mock_mode_or_with_explicit_bridge_url(monkeypatch):
    _live(monkeypatch, _switch(111), _switch(222))
    assert panel_server.resolve_instance(None, "revit_get_document_info") is None  # mock mode (tests default)
    monkeypatch.setattr(panel_server.config, "mode", BridgeMode.bridge)
    monkeypatch.setattr(panel_server.config, "bridge_url", "http://127.0.0.1:3000")
    assert panel_server.resolve_instance(None, "revit_get_document_info") is None


def test_http_execute_ambiguity_is_409_and_hub_local_still_works(hub, bridge_mode, monkeypatch):
    port, token = hub
    _live(monkeypatch, _switch(111, "2024"), _switch(222, "2026"))
    status, _, body = _call(port, "POST", "/execute", token, {"tool": "revit_get_document_info", "arguments": {}})
    assert status == 409 and "111" in body["error"] and "222" in body["error"]
    status, _, body = _call(port, "POST", "/execute", token, {"tool": "list_pending_plans", "arguments": {}})
    assert status == 200


def test_http_execute_routes_to_the_requested_instance(hub, bridge_mode, monkeypatch):
    port, token = hub
    _live(monkeypatch, _switch(111, "2024"), _switch(222, "2026"))
    seen = []

    def fake_run(registry, approval, name, arguments):
        from revit_mcp_server.providers import revit as revit_module

        seen.append((name, revit_module._BRIDGE_OVERRIDE.get()))
        return {"ok": True}

    monkeypatch.setattr(panel_server, "_run_tool_sync", fake_run)
    status, _, body = _call(port, "POST", "/execute", token, {
        "tool": "revit_get_document_info", "arguments": {}, "instance": {"pid": 222, "document": "Tower.rvt"},
    })
    assert status == 200 and body["ok"] is True
    assert len(seen) == 1 and seen[0][1] is not None


def test_routed_to_sends_calls_to_that_bridge_only(tmp_path):
    from revit_mcp_server.providers.revit import RevitProvider

    class Recorder:
        def __init__(self, url, token=None):
            self.url, self.token, self.calls = url, token, []

        def send_tool(self, tool, payload):
            self.calls.append(tool)
            return {"ok": True, "via": self.url}

    made = {}

    def factory(url, token=None):
        made[url] = Recorder(url, token)
        return made[url]

    provider = RevitProvider(
        workspace=WorkspaceMonitor([tmp_path]), mode=BridgeMode.bridge, bridge_url="http://127.0.0.1:3000",
        bridge_factory=factory,
    )
    import asyncio

    with provider.routed_to("http://127.0.0.1:4111", "tok-b"):
        result = asyncio.run(provider.execute_tool("revit_health", {}))
    assert result["via"] == "http://127.0.0.1:4111"
    assert made["http://127.0.0.1:4111"].token == "tok-b"
    assert made["http://127.0.0.1:3000"].calls == []  # the default bridge was not touched
    after = asyncio.run(provider.execute_tool("revit_health", {}))
    assert after["via"] == "http://127.0.0.1:3000"  # override is scoped to the block


def test_chat_through_a_cli_is_refused_when_two_revits_are_open(hub, bridge_mode, monkeypatch):
    port, token = hub
    _live(monkeypatch, _switch(111), _switch(222))
    monkeypatch.setattr(panel_server.config, "anthropic_api_key", None)
    monkeypatch.setattr(panel_server.shutil, "which", lambda _n: "/usr/bin/claude")
    called = []
    monkeypatch.setattr(panel_server.agent_bridge, "run_agent_turn", lambda *a: called.append(a) or {"ok": True})
    status, _, body = _call(port, "POST", "/agent/chat", token, {"message": "hi", "instance": {"pid": 111}})
    assert status == 409 and "111" in body["error"] and "222" in body["error"]
    assert called == []


# --- source guards for the parts that cannot run here (C# and panel JS) ------------

REPO = Path(__file__).resolve().parents[3]


def test_panel_page_never_calls_the_hub_or_sees_the_token():
    for page in (REPO / "panel").glob("*"):
        if page.suffix not in {".js", ".html"}:
            continue
        text = page.read_text(encoding="utf-8")
        assert "X-AMB-Token" not in text and "panel-hub.token" not in text, page
        for needle in ("fetch(", "XMLHttpRequest", "WebSocket(", "EventSource(", ":8787"):
            assert needle not in text, f"{page.name} calls the network directly ({needle})"


def test_every_csharp_hub_call_goes_through_the_token_sending_helper():
    ui = REPO / "packages" / "revit-bridge-addin" / "src" / "UI"
    src = (ui / "HubClient.cs").read_text(encoding="utf-8")
    assert 'TokenHeader = "X-AMB-Token"' in src
    assert src.count("request.Headers.Add(TokenHeader, token)") == 1
    # the only direct HttpClient send is inside SendOnceAsync, which adds the header
    assert src.count("client.SendAsync(") == 1
    for forbidden in ("Client.GetAsync(", "Client.PostAsync(", "DefaultRequestHeaders"):
        assert forbidden not in src
    # the token is never handed to the page through the WebView2 message bridge
    assert "HubTokenStore" not in (ui / "BridgePanel.xaml.cs").read_text(encoding="utf-8")
