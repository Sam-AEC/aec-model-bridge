"""Read-only reviewer credential for the panel hub (#210).

UNVERIFIED: nothing here runs Revit, WebView2 or the add-in. The hub is driven over loopback in mock mode.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
from pathlib import Path

import pytest

from revit_mcp_server import panel_server
from revit_mcp_server.panel_server import build_server
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security import panel_token
from revit_mcp_server.security.panel_token import (
    PanelTokenError,
    create_reviewer_token,
    read_reviewer_token,
    read_token,
)
from revit_mcp_server.security.workspace import WorkspaceMonitor

REVIEWER_HEADER = "X-AMB-Reviewer-Token"
REVIEWER = "R" * 43


def _serve(tmp_path, **kwargs):
    server = build_server(port=0, workspace=WorkspaceMonitor([tmp_path / "ws"]), **kwargs)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def hub(tmp_path):
    server, thread = _serve(tmp_path, reviewer_token=REVIEWER)
    try:
        yield server.server_address[1], read_token()
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def hub_no_reviewer(tmp_path):
    server, thread = _serve(tmp_path)
    try:
        yield server.server_address[1], read_token()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _call(port, method, path, *, token=None, reviewer=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-AMB-Token"] = token
        if reviewer is not None:
            headers[REVIEWER_HEADER] = reviewer
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else {})
    finally:
        conn.close()


def _execute(port, tool, arguments=None, **creds):
    return _call(port, "POST", "/execute", body={"tool": tool, "arguments": arguments or {}}, **creds)


# --- what a reviewer can do -----------------------------------------------------


def test_reviewer_can_list_plans(hub):
    port, _ = hub
    status, body = _execute(port, "list_pending_plans", reviewer=REVIEWER)
    assert status == 200 and body["ok"] is True
    assert "plans" in body["result"]


def test_reviewer_can_read_a_proof_bundle_route(hub):
    port, _ = hub
    status, body = _execute(port, "get_proof_bundle", {"plan_id": "plan_missing"}, reviewer=REVIEWER)
    # Let through to the tool, which says there is no proof yet. Not a role refusal.
    assert status not in (401, 403)
    assert "reviewer" not in body["error"].lower()


@pytest.mark.parametrize("path", ["/diagnostics", "/reports"])
def test_reviewer_can_read_status_routes(hub, path):
    port, _ = hub
    assert _call(port, "GET", path, reviewer=REVIEWER)[0] == 200


# --- what a reviewer cannot do ----------------------------------------------------


@pytest.mark.parametrize("tool", [
    "approve_plan", "reject_plan", "rollback_plan", "execute_plan", "plan_actions", "plan_revert",
    "policy_show", "revit_execute_python", "no_such_tool",
])
def test_reviewer_refused_on_every_other_tool(hub, tool):
    port, _ = hub
    status, body = _execute(port, tool, {"plan_id": "plan_x", "expected_hash": "h"}, reviewer=REVIEWER)
    assert status == 403
    assert body["ok"] is False and "reviewer" in body["error"].lower()


def test_reviewer_refused_on_approval_mode_change(hub):
    port, _ = hub
    for mode in ("auto", "dev", "ask_first"):
        status, body = _call(port, "POST", "/approval-mode", reviewer=REVIEWER, body={"mode": mode, "confirm": True})
        assert status == 403 and "reviewer" in body["error"].lower()


@pytest.mark.parametrize("method,path", [
    ("POST", "/agent/chat"), ("GET", "/agent/providers"), ("GET", "/no-such-route"),
    ("POST", "/no-such-route"), ("POST", "/diagnostics"), ("GET", "/execute"),
])
def test_reviewer_refused_on_any_route_not_listed(hub, method, path):
    port, _ = hub
    status, _ = _call(port, method, path, reviewer=REVIEWER, body={"message": "hi"} if method == "POST" else None)
    assert status == 403


def test_reviewer_secret_is_not_the_approving_token(hub):
    port, _ = hub
    status, _ = _execute(port, "approve_plan", {"plan_id": "p", "expected_hash": "h"}, token=REVIEWER)
    assert status == 401


def test_reviewer_header_does_not_upgrade_a_wrong_approving_token(hub):
    port, token = hub
    wrong = ("A" if token[0] != "A" else "B") + token[1:]
    status, _ = _execute(port, "approve_plan", {"plan_id": "p", "expected_hash": "h"}, token=wrong, reviewer=REVIEWER)
    assert status == 403  # still only a reviewer, so still refused


# --- off when not configured, and the approving token is unchanged ------------------


@pytest.mark.parametrize("method,path,body", [
    ("POST", "/execute", {"tool": "list_pending_plans", "arguments": {}}),
    ("GET", "/diagnostics", None),
    ("POST", "/approval-mode", {"mode": "ask_first"}),
])
def test_reviewer_header_is_401_when_no_reviewer_is_configured(hub_no_reviewer, method, path, body):
    port, _ = hub_no_reviewer
    status, parsed = _call(port, method, path, reviewer=REVIEWER, body=body)
    assert status == 401 and parsed == {"ok": False, "error": "Unauthorized"}


def test_missing_and_wrong_reviewer_are_401(hub):
    port, _ = hub
    assert _call(port, "GET", "/diagnostics")[0] == 401
    assert _call(port, "GET", "/diagnostics", reviewer="X" * 43)[0] == 401
    assert _call(port, "GET", "/diagnostics", reviewer="x" * 5000)[0] == 401


def test_panel_token_still_lists_and_changes_mode(hub):
    port, token = hub
    assert _execute(port, "list_pending_plans", token=token)[0] == 200
    assert _call(port, "GET", "/reports", token=token)[0] == 200
    assert _call(port, "POST", "/approval-mode", token=token, body={"mode": "ask_first"})[0] == 200


def test_panel_token_wins_when_both_are_sent(hub):
    port, token = hub
    status, _ = _call(port, "POST", "/approval-mode", token=token, reviewer=REVIEWER, body={"mode": "ask_first"})
    assert status == 200


def test_reviewer_token_equal_to_panel_token_is_not_a_reviewer(tmp_path):
    token = "T" * 43
    server, thread = _serve(tmp_path, token=token, reviewer_token=token)
    try:
        assert _call(server.server_address[1], "GET", "/diagnostics", reviewer=token)[0] == 401
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_reviewer_compare_is_constant_time(hub, monkeypatch):
    port, _ = hub
    calls = []
    real = panel_server.hmac.compare_digest
    monkeypatch.setattr(panel_server.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    _call(port, "GET", "/diagnostics", reviewer=REVIEWER)
    assert len(calls) >= 1


def test_failed_reviewer_checks_are_rate_limited(hub):
    port, _ = hub
    statuses = [_call(port, "GET", "/diagnostics", reviewer="X" * 43)[0] for _ in range(25)]
    assert 429 in statuses


# --- credential storage ---------------------------------------------------------


def test_reviewer_token_file_is_separate_and_off_by_default():
    assert read_reviewer_token() is None
    assert panel_token.reviewer_token_path() != panel_token.token_path()


def test_create_reviewer_token_writes_a_distinct_token_and_never_overwrites():
    first = create_reviewer_token()
    assert panel_token.is_valid_token(first) and first != panel_token.load_or_create_token()
    assert create_reviewer_token() == first
    assert read_reviewer_token() == first


def test_hub_picks_up_the_reviewer_file(tmp_path):
    token = create_reviewer_token()
    server, thread = _serve(tmp_path)
    try:
        assert _call(server.server_address[1], "GET", "/diagnostics", reviewer=token)[0] == 200
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_malformed_reviewer_file_leaves_the_reviewer_off(tmp_path):
    panel_token.reviewer_token_path().write_text("not a token\n")
    server, thread = _serve(tmp_path)
    try:
        assert _call(server.server_address[1], "GET", "/diagnostics", reviewer="not a token")[0] == 401
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_malformed_reviewer_file_raises_from_the_reader():
    panel_token.reviewer_token_path().write_text("bad\n")
    with pytest.raises(PanelTokenError):
        read_reviewer_token()


# --- no MCP tool can see or set it -------------------------------------------------


def test_no_tool_exposes_or_sets_a_reviewer_credential(tmp_path):
    registry, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    tools = registry.get_all_tools()
    assert tools
    blob = json.dumps([[t.name, t.description, t.input_schema] for t in tools]).lower()
    assert not re.search(r"reviewer|amb-reviewer|panel-reviewer", blob)


def test_only_the_panel_files_handle_the_reviewer_credential():
    src = Path(panel_server.__file__).parent
    offenders = [
        str(p.relative_to(src)) for p in src.rglob("*.py")
        if re.search(r"reviewer_token|REVIEWER_HEADER", p.read_text(encoding="utf-8", errors="ignore"))
        and p.name not in {"panel_token.py", "panel_server.py"}
    ]
    assert offenders == []
