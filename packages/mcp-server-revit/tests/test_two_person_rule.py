"""Optional two-person rule (#203): with `require_second_approver` on, the person who asked for a plan cannot
approve it. It only adds refusals; it is off by default and no tool call can turn it on or name an approver."""
from __future__ import annotations

import asyncio

import pytest

from helpers import human_approve
from revit_mcp_server import approve_cli
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import policy as pol
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security.approval import (
    APPROVER_ENV, REQUESTER_ENV, ApprovalGate, local_user, plan_hash,
)
from revit_mcp_server.security.workspace import WorkspaceMonitor

SET = "revit_set_parameter_value"
ACTION = [{"tool": SET, "arguments": {"element_id": 1, "parameter_name": "Mark", "value": "A"}}]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (REQUESTER_ENV, APPROVER_ENV, pol.POLICY_ENV):
        monkeypatch.delenv(name, raising=False)


def _gate(tmp_path, policy_text=None):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    if policy_text is not None:
        (ws / "policy.yaml").write_text(policy_text, encoding="utf-8")
    return ApprovalGate(ws)


def _on(tmp_path):
    return _gate(tmp_path, "require_second_approver: true\n")


def _draft(gate, monkeypatch, requester="alice"):
    monkeypatch.setenv(REQUESTER_ENV, requester)
    return gate.create_plan(ACTION, [{}])["plan_id"]


def test_requester_is_refused(tmp_path, monkeypatch):
    gate = _on(tmp_path)
    pid = _draft(gate, monkeypatch, "alice")
    assert gate.load_plan(pid)["requested_by"] == "alice"
    with pytest.raises(ValueError, match="requested by 'alice'.*cannot approve"):
        human_approve(gate, pid, approver="Alice")
    assert gate.load_plan(pid)["state"] == "pending"


def test_different_named_approver_succeeds(tmp_path, monkeypatch):
    gate = _on(tmp_path)
    pid = _draft(gate, monkeypatch, "alice")
    plan = human_approve(gate, pid, approver="bob")
    assert plan["state"] == "approved" and plan["approved_by"] == "bob"


def test_default_requester_is_the_os_account_so_same_account_is_refused(tmp_path):
    gate = _on(tmp_path)
    pid = gate.create_plan(ACTION, [{}])["plan_id"]
    assert gate.load_plan(pid)["requested_by"] == local_user()
    with pytest.raises(ValueError, match="second approver"):
        human_approve(gate, pid)


@pytest.mark.parametrize("requester", ["unknown", ""])
def test_unknown_requester_is_refused(tmp_path, requester):
    gate = _on(tmp_path)
    pid = gate.create_plan(ACTION, [{}])["plan_id"]
    plan = gate.load_plan(pid)
    plan["requested_by"] = requester
    plan["plan_hash"] = plan_hash(plan)
    gate.save_plan(plan)
    with pytest.raises(ValueError, match="does not record who asked"):
        human_approve(gate, pid, approver="bob")


def test_plan_drafted_before_the_option_was_on_is_refused(tmp_path, monkeypatch):
    gate = _gate(tmp_path)
    pid = _draft(gate, monkeypatch)
    assert "requested_by" not in gate.load_plan(pid)
    (tmp_path / "ws" / "policy.yaml").write_text("require_second_approver: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not record who asked"):
        human_approve(gate, pid, approver="bob")


@pytest.mark.parametrize("approver", ["unknown", "  "])
def test_unknown_approver_is_refused(tmp_path, monkeypatch, approver):
    gate = _on(tmp_path)
    pid = _draft(gate, monkeypatch)
    with pytest.raises(ValueError, match="name of the approver is not known"):
        human_approve(gate, pid, approver=approver)


def test_requester_cannot_be_edited_after_drafting(tmp_path, monkeypatch):
    gate = _on(tmp_path)
    pid = _draft(gate, monkeypatch, "alice")
    plan = gate.load_plan(pid)
    shown = plan_hash(plan)
    plan["requested_by"] = "mallory"
    gate.save_plan(plan)
    with pytest.raises(ValueError, match="content changed"):
        gate.update_plan_state(pid, "approved", approver="bob", via="cli", expected_hash=shown)


def test_off_is_unchanged_and_hash_is_stable(tmp_path):
    gate = _gate(tmp_path)
    plan = gate.create_plan(ACTION, [{}])
    assert "requested_by" not in plan
    assert plan["plan_hash"] == proof_mod.plan_content_hash({k: v for k, v in plan.items() if k != "requested_by"})
    done = human_approve(gate, plan["plan_id"])  # same account drafted and approved: still fine
    assert done["state"] == "approved" and done["approved_by"] == local_user()


def test_explicit_false_is_off(tmp_path):
    gate = _gate(tmp_path, "require_second_approver: false\n")
    plan = gate.create_plan(ACTION, [{}])
    assert "requested_by" not in plan
    assert human_approve(gate, plan["plan_id"])["state"] == "approved"


def test_requested_by_changes_the_hash_only_when_present(tmp_path):
    gate = _gate(tmp_path)
    plan = gate.create_plan(ACTION, [{}])
    with_key = dict(plan, requested_by="alice")
    assert plan_hash(with_key) != plan_hash(plan)
    assert plan_hash(dict(plan)) == plan["plan_hash"]


def test_policy_value_must_be_a_boolean(tmp_path):
    (tmp_path / "policy.yaml").write_text("require_second_approver: yes please\n", encoding="utf-8")
    with pytest.raises(pol.PolicyError, match="true or false"):
        pol.load_policy(tmp_path)


def test_machine_policy_on_wins_over_workspace_off(tmp_path, monkeypatch):
    machine = tmp_path / "machine.yaml"
    machine.write_text("require_second_approver: true\n", encoding="utf-8")
    monkeypatch.setenv(pol.MACHINE_POLICY_ENV, str(machine))
    gate = _gate(tmp_path, "require_second_approver: false\n")
    assert pol.second_approver_required(pol.load_policy(gate.workspace_dir)) is True
    assert gate.create_plan(ACTION, [{}])["requested_by"]


def test_tool_arguments_cannot_set_requester(tmp_path):
    gate = _on(tmp_path)
    from revit_mcp_server.errors import BridgeError
    with pytest.raises(BridgeError, match="requested_by"):
        gate.create_plan(ACTION, [{}], extra={"requested_by": "bob"})


def test_panel_route_uses_the_environment_not_arguments(tmp_path, monkeypatch):
    _on(tmp_path)
    provider = ApprovalProvider(WorkspaceMonitor([tmp_path / "ws"]), ProviderRegistry())
    gate = provider.gate
    pid = _draft(gate, monkeypatch, "alice")
    monkeypatch.setenv(APPROVER_ENV, "alice")
    args = {"plan_id": pid, "expected_hash": gate.load_plan(pid)["plan_hash"], "approver": "bob"}
    with pytest.raises(ValueError, match="second approver"):
        asyncio.run(provider.execute_human_tool("approve_plan", args, via="panel"))
    monkeypatch.setenv(APPROVER_ENV, "bob")
    done = asyncio.run(provider.execute_human_tool("approve_plan", args, via="panel"))
    assert done["approved_by"] == "bob"


def test_cli_approve_refuses_requester_and_accepts_other(tmp_path, monkeypatch, capsys):
    gate = _on(tmp_path)
    pid = _draft(gate, monkeypatch, "alice")
    monkeypatch.setattr(approve_cli, "ApprovalGate", lambda *a, **k: gate)
    monkeypatch.setenv("MCP_REVIT_WORKSPACE_DIR", str(gate.workspace_dir))
    monkeypatch.setenv(APPROVER_ENV, "alice")
    rc = approve_cli.main(["approve", pid, "--yes"])
    assert rc == 1 and "second approver" in capsys.readouterr().err
    monkeypatch.setenv(APPROVER_ENV, "bob")
    assert approve_cli.main(["approve", pid, "--yes"]) == 0
    assert gate.load_plan(pid)["approved_by"] == "bob"
