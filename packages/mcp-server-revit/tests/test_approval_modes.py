"""Approval modes: look_only, ask_first (alias required) and auto.

UNVERIFIED against live Revit: these tests cover the hub's gate only."""
from __future__ import annotations

import asyncio
import logging

import pytest

from revit_mcp_server.config import Config, normalize_approval_mode
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import LOOK_ONLY_MESSAGE, ApprovalGate
from revit_mcp_server.security.dispatch import gate_before, run_gated_tool
from revit_mcp_server.security.workspace import WorkspaceMonitor

MUTATING = "revit_delete_element"
MESSAGE = "Look only mode: this tool changes the model. Switch to Ask me first in the panel or settings."


@pytest.fixture
def stack(tmp_path):
    registry, approval, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    return registry, approval


# ---- normalisation and config ------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    ("look_only", "look_only"), (" Look_Only ", "look_only"),
    ("ask_first", "ask_first"), ("required", "ask_first"), ("REQUIRED", "ask_first"),
    ("auto", "auto"), (" Auto ", "auto"),
])
def test_known_modes_normalise(value, expected):
    assert normalize_approval_mode(value) == expected


@pytest.mark.parametrize("value", ["bogus", "off", "false", "0", "", None, 0, ["auto"], "look-only"])
def test_unknown_modes_fail_closed_with_warning(value, caplog):
    with caplog.at_level(logging.WARNING):
        assert normalize_approval_mode(value) == "ask_first"
    assert "Unknown approval_mode" in caplog.text


def test_message_text_is_the_agreed_one():
    assert LOOK_ONLY_MESSAGE == MESSAGE


@pytest.mark.parametrize("env,expected", [
    ("look_only", "look_only"), ("ask_first", "ask_first"), ("required", "ask_first"),
    ("auto", "auto"), ("nonsense", "ask_first"),
])
def test_env_override_is_validated(monkeypatch, tmp_path, env, expected):
    monkeypatch.setenv("MCP_REVIT_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_REVIT_ALLOWED_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("MCP_REVIT_APPROVAL_MODE", env)
    assert Config().approval_mode == expected


def test_default_config_mode_is_ask_first(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_REVIT_APPROVAL_MODE", raising=False)
    monkeypatch.setenv("MCP_REVIT_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_REVIT_ALLOWED_DIRECTORIES", str(tmp_path))
    assert Config().approval_mode == "ask_first"


# ---- look_only on every gate entry point -------------------------------------------


def test_look_only_refuses_check_tool_execution(tmp_path):
    gate = ApprovalGate(tmp_path, "look_only")
    with pytest.raises(BridgeError, match="Look only mode"):
        gate.check_tool_execution(MUTATING, {"element_id": 1})


def test_look_only_refuses_claim_action_even_with_an_approved_plan(tmp_path):
    gate = ApprovalGate(tmp_path, "ask_first")
    plan = gate.create_plan([{"tool": MUTATING, "arguments": {"element_id": 7}}], {})
    gate.update_plan_state(plan["plan_id"], "approved", approver="t", via="cli", expected_hash=plan["plan_hash"])
    gate.approval_mode = "look_only"
    with pytest.raises(BridgeError, match="Look only mode"):
        gate.claim_action(MUTATING, {"element_id": 7, "plan_id": plan["plan_id"]})
    gate.approval_mode = "ask_first"  # the refused call must not have consumed the action
    assert gate.claim_action(MUTATING, {"element_id": 7, "plan_id": plan["plan_id"]})


def test_look_only_refuses_every_mutating_tool_in_gate_before(stack):
    registry, approval = stack
    approval.gate.approval_mode = "look_only"
    mutating = [t.name for t in registry.get_all_tools() if t.is_mutating]
    assert MUTATING in mutating and len(mutating) > 5
    for name in mutating:
        with pytest.raises(BridgeError, match="Look only mode"):
            gate_before(registry, approval.gate, name, {})


def test_look_only_lets_read_tools_through(stack):
    registry, approval = stack
    approval.gate.approval_mode = "look_only"
    reads = [t.name for t in registry.get_all_tools() if not t.is_mutating]
    assert reads
    for name in reads:
        if name in ("approve_plan", "reject_plan", "rollback_plan"):
            continue
        assert gate_before(registry, approval.gate, name, {}) is None


def test_look_only_refuses_run_gated_tool_and_never_runs_the_tool(stack):
    registry, approval = stack
    approval.gate.approval_mode = "look_only"
    provider = registry.lookup_tool_provider(MUTATING)
    calls = []

    async def spy(name, arguments):
        calls.append(name)
        return {}

    provider.execute_tool = spy
    with pytest.raises(BridgeError, match="Look only mode"):
        asyncio.run(run_gated_tool(registry, approval.gate, MUTATING, {"element_id": 1}))
    assert calls == []


def test_look_only_refuses_execute_plan_before_touching_the_plan(tmp_path):
    registry, approval, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    gate = approval.gate
    plan = gate.create_plan([{"tool": MUTATING, "arguments": {"element_id": 7}}], {})
    gate.update_plan_state(plan["plan_id"], "approved", approver="t", via="cli", expected_hash=plan["plan_hash"])
    gate.approval_mode = "look_only"
    with pytest.raises(BridgeError, match="Look only mode"):
        asyncio.run(approval._execute_plan(plan["plan_id"]))
    assert gate.load_plan(plan["plan_id"])["state"] == "approved"  # not marked partial


def test_look_only_refuses_rollback(tmp_path):
    gate = ApprovalGate(tmp_path, "look_only")

    async def run():
        await gate.rollback_plan("plan_000000000000", lambda *a: None)

    with pytest.raises(BridgeError, match="Look only mode"):
        asyncio.run(run())


# ---- other modes keep their behaviour ----------------------------------------------


@pytest.mark.parametrize("mode", ["ask_first", "required"])
def test_ask_first_still_needs_a_plan(tmp_path, mode):
    gate = ApprovalGate(tmp_path, mode)
    with pytest.raises(BridgeError, match="requires a valid 'plan_id'"):
        gate.check_tool_execution(MUTATING, {"element_id": 1})


def test_auto_is_explicit_and_allows_calls_without_a_plan(tmp_path):
    gate = ApprovalGate(tmp_path, "auto")
    gate.check_tool_execution(MUTATING, {"element_id": 1})
    assert gate.claim_action(MUTATING, {"element_id": 1}) is None


def test_gate_unknown_mode_is_ask_first_not_open(tmp_path):
    gate = ApprovalGate(tmp_path, "bogus")
    assert gate.approval_mode == "ask_first"
    with pytest.raises(BridgeError, match="requires a valid 'plan_id'"):
        gate.claim_action(MUTATING, {"element_id": 1})


# ---- the mode cannot be changed over MCP -------------------------------------------


def test_no_mcp_tool_sets_the_mode(stack):
    registry, _ = stack
    for tool in registry.get_all_tools():
        text = tool.name.lower()
        assert "approval_mode" not in text and "set_mode" not in text and "mode_set" not in text, tool.name
        props = (tool.inputSchema or {}).get("properties", {}) if hasattr(tool, "inputSchema") else {}
        assert "approval_mode" not in props, tool.name
    names = {t.name for t in registry.get_all_tools()}
    assert not {n for n in names if "approval" in n and ("set" in n or "mode" in n or "config" in n)}


# ---- read-only exposure ------------------------------------------------------------


@pytest.mark.parametrize("mode,expected", [("look_only", "look_only"), ("required", "ask_first"),
                                            ("auto", "auto"), ("bogus", "ask_first")])
def test_health_reports_normalised_mode(tmp_path, mode, expected):
    registry, approval, *_ = build_registry(WorkspaceMonitor([tmp_path]))
    approval.gate.approval_mode = mode
    health = asyncio.run(approval.check_health())
    assert health["approval_mode"] == expected
    assert health["status"] == "healthy"
