"""Tests for panel_server.py, the loopback HTTP shim the dockable panel calls
since MCP itself is stdio-only (see panel_server.py's module docstring and
docs/product/PLUGIN_APP_ARCHITECTURE.md section 2).

Each test builds its own server bound to workspace=WorkspaceMonitor([tmp_path])
so ApprovalGate plan files never land in the shared tests/ workspace.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from revit_mcp_server.panel_server import build_server
from revit_mcp_server.security.workspace import WorkspaceMonitor


@pytest.fixture
def running_server(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    server = build_server(port=0, workspace=workspace)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield port
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _get(port: int, path: str):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(port: int, path: str, body: dict):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_reports_tool_count(running_server):
    status, body = _get(running_server, "/health")
    assert status == 200
    assert body["status"] == "healthy"
    assert body["tools"] > 100  # ~218 across all providers/modules


def test_execute_runs_a_real_readonly_tool(running_server):
    """list_pending_plans is a genuinely readonly tool: it only reads plan files from
    disk, never writes, and doesn't depend on optional modules like qaqc_checker."""
    status, body = _post(running_server, "/execute", {"tool": "list_pending_plans", "arguments": {}})
    assert status == 200
    assert body["ok"] is True
    assert "plans" in body["result"]


def test_execute_unknown_tool_returns_500_with_message(running_server):
    status, body = _post(running_server, "/execute", {"tool": "not_a_real_tool", "arguments": {}})
    assert status == 500
    assert body["ok"] is False
    assert "not_a_real_tool" in body["error"]


def test_execute_missing_tool_field_returns_400(running_server):
    status, body = _post(running_server, "/execute", {"arguments": {}})
    assert status == 400
    assert body["ok"] is False


def test_unknown_path_returns_404(running_server):
    status, body = _get(running_server, "/nope")
    assert status == 404
    assert body["ok"] is False


def test_mutating_tool_without_plan_is_rejected(running_server):
    """The panel shim must apply the same ApprovalGate check as the stdio
    server - a mutating tool called with no plan_id must not go through."""
    status, body = _post(running_server, "/execute", {
        "tool": "revit_set_parameter_value",
        "arguments": {"element_id": 1, "parameter_name": "FireRating", "value": "60"},
    })
    assert status == 409
    assert body["ok"] is False
    assert "plan_id" in body["error"]


def test_plan_actions_approve_execute_round_trip_over_http(running_server):
    """Proves the panel can drive the full W5 workflow end-to-end through
    HTTP alone: plan -> approve -> execute -> verify, all as separate
    requests hitting the same server (and therefore the same in-process
    registry) - this is the exact shape the C# panel host will use."""
    status, plan = _post(running_server, "/execute", {
        "tool": "plan_actions",
        "arguments": {"actions": [{
            "tool": "revit_set_parameter_value",
            "arguments": {"element_id": 42, "parameter_name": "Mark", "value": "D-999"},
        }]},
    })
    assert status == 200
    plan_id = plan["result"]["plan_id"]
    assert plan["result"]["state"] == "pending"

    status, approved = _post(running_server, "/execute", {"tool": "approve_plan", "arguments": {"plan_id": plan_id}})
    assert status == 200
    assert approved["result"]["state"] == "approved"

    status, executed = _post(running_server, "/execute", {"tool": "execute_plan", "arguments": {"plan_id": plan_id}})
    assert status == 200
    # execute_plan succeeds even when the underlying Revit tool is mocked and returns
    # an error (no live Revit process in tests). Accept "executed" (all OK) or
    # "partial" (some actions failed — expected here since Revit is unavailable).
    assert executed["result"]["state"] in ("executed", "partial")
