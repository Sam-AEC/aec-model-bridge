"""Signed approval records (#313) and at-most-once claims in Auto mode (#314)."""
from __future__ import annotations

import json
import os
import stat
from typing import Any, Dict

import pytest

from helpers import human_approve, panel_decide
from test_approval_provider import FakeParamStore
from revit_mcp_server import approve_cli
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import approval_override as override_mod
from revit_mcp_server.security import approval_signing as signing
from revit_mcp_server.security.approval import ApprovalGate
from revit_mcp_server.security.workspace import WorkspaceMonitor

SET = "revit_set_parameter_value"
NOT_VERIFIED = "approval record does not verify; approve it again"
TOKEN = "A" * 43


def _args(element_id=1, value="60"):
    return {"element_id": element_id, "parameter_name": "FireRating", "value": value}


@pytest.fixture(autouse=True)
def _token_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_PANEL_TOKEN_FILE", str(tmp_path / "panel-hub.token"))


@pytest.fixture
def gate(tmp_path):
    g = ApprovalGate(tmp_path / "ws", "ask_first")
    g.override_token = TOKEN
    return g


def _approved(gate, via="cli", binding=None):
    kw = {} if binding is None else {"binding": binding}
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], **kw)["plan_id"]
    human_approve(gate, pid, via=via)
    return pid


def _rewrite(gate, plan: Dict[str, Any]) -> None:
    """Write a plan file directly, the way another local process could."""
    (gate.plans_dir / f"{plan['plan_id']}.json").write_text(json.dumps(plan), encoding="utf-8")


class CountingStore(FakeParamStore):
    def __init__(self, values):
        super().__init__(values)
        self.writes = 0

    async def execute_tool(self, name, arguments):
        if name == SET:
            self.writes += 1
        return await super().execute_tool(name, arguments)


def _provider(tmp_path, mode="required"):
    registry = ProviderRegistry()
    approval = ApprovalProvider(WorkspaceMonitor([tmp_path]), registry, approval_mode=mode)
    approval.gate.override_token = TOKEN
    registry.register(approval)
    store = CountingStore({1: {"FireRating": "30"}, 2: {"FireRating": "45"}})
    registry.register(store)
    return approval, store


# ---- signing on every approval channel -------------------------------------------------


@pytest.mark.parametrize("via", ["cli", "panel"])
def test_gate_approval_on_each_channel_is_signed_and_verifies(gate, via):
    plan = gate.load_plan(_approved(gate, via=via))
    assert plan["approved_via"] == via
    assert plan["approval_sig"]["alg"] == "HMAC-SHA256" and plan["approval_sig"]["v"] == 1
    assert signing.verify_plan_signature(gate.plans_dir, plan)
    gate.verify_approved(plan)


@pytest.mark.anyio
async def test_panel_route_produces_a_verifiable_signature(tmp_path):
    approval, _ = _provider(tmp_path)
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": _args()}]})
    result = await panel_decide(approval, "approve_plan", plan["plan_id"])
    assert result["approved_via"] == "panel"
    assert signing.verify_plan_signature(approval.gate.plans_dir, approval.gate.load_plan(plan["plan_id"]))


def test_cli_command_produces_a_verifiable_signature(gate, monkeypatch):
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    monkeypatch.setattr(approve_cli, "_gate", lambda ws: gate)
    assert approve_cli.main(["approve", pid, "--yes"]) == 0
    plan = gate.load_plan(pid)
    assert plan["approved_via"] == "cli"
    assert signing.verify_plan_signature(gate.plans_dir, plan)


def test_rejecting_and_pending_plans_carry_no_signature(gate):
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    assert "approval_sig" not in gate.load_plan(pid)
    gate.update_plan_state(pid, "rejected", via="cli")
    assert "approval_sig" not in gate.load_plan(pid)


# ---- tampering, legacy plans, key problems ----------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("approved_hash", "0" * 64),
    ("approved_via", "panel"),
    ("approved_by", "someone-else"),
    ("approved_at", "2020-01-01T00:00:00+00:00"),
    ("plan_id", "plan_000000000000"),
])
def test_tampering_with_any_signed_field_fails_verification(gate, field, value):
    plan = gate.load_plan(_approved(gate))
    assert signing.verify_plan_signature(gate.plans_dir, plan)
    assert not signing.verify_plan_signature(gate.plans_dir, {**plan, field: value})


def test_tampering_with_the_binding_fails_verification(gate):
    binding = {"doc_guid": "g-1", "central_path_hash": None, "doc_title": "Villa",
               "revit_version": "2024", "active_view_id": None}
    plan = gate.load_plan(_approved(gate, binding=binding))
    assert signing.verify_plan_signature(gate.plans_dir, plan)
    assert not signing.verify_plan_signature(gate.plans_dir, {**plan, "binding": {**binding, "doc_guid": "g-2"}})
    assert not signing.verify_plan_signature(gate.plans_dir, {k: v for k, v in plan.items() if k != "binding"})


@pytest.mark.parametrize("sig", [
    None, {}, "abc", {"v": 1, "alg": "HMAC-SHA256"}, {"v": 2, "alg": "HMAC-SHA256", "mac": "00"},
    {"v": 1, "alg": "HMAC-SHA1", "mac": "00"}, {"v": 1, "alg": "HMAC-SHA256", "mac": 5},
])
def test_malformed_signature_fails_verification(gate, sig):
    plan = gate.load_plan(_approved(gate))
    assert not signing.verify_plan_signature(gate.plans_dir, {**plan, "approval_sig": sig})


def test_edited_approved_at_on_disk_is_refused_with_the_plain_message(gate):
    pid = _approved(gate)
    plan = gate.load_plan(pid)
    plan["approved_at"] = "2099-01-01T00:00:00+00:00"
    _rewrite(gate, plan)
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        gate.claim_action(SET, {**_args(), "plan_id": pid})
    assert gate.load_plan(pid)["actions"][0]["state"] == "pending"


def test_hand_marked_approval_is_refused(gate):
    """A process that writes state=approved and a matching approved_hash cannot forge an approval."""
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    plan = gate.load_plan(pid)
    plan.update(state="approved", approved_hash=plan["plan_hash"], approved_via="cli", approved_by="me",
                approved_at=plan["created_at"])
    _rewrite(gate, plan)
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        gate.claim_action(SET, {**_args(), "plan_id": pid})


@pytest.mark.anyio
async def test_unsigned_legacy_approved_plan_is_refused_by_execute_plan(tmp_path):
    approval, store = _provider(tmp_path)
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": _args()}]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    legacy = approval.gate.load_plan(plan["plan_id"])
    del legacy["approval_sig"]  # an approval recorded before signing existed
    _rewrite(approval.gate, legacy)
    with pytest.raises(BridgeError) as refused:
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert str(refused.value) == signing.NOT_VERIFIED_MESSAGE
    assert store.writes == 0
    assert approval.gate.load_plan(plan["plan_id"])["actions"][0]["state"] == "pending"


def test_missing_key_is_refused_and_not_recreated(gate):
    pid = _approved(gate)
    key = signing.key_path(gate.plans_dir)
    key.unlink()
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        gate.verify_approved(gate.load_plan(pid))
    assert not key.exists()


def test_wrong_key_is_refused(gate):
    pid = _approved(gate)
    key = signing.key_path(gate.plans_dir)
    os.chmod(key, 0o600)
    key.write_bytes(b"\x01" * signing.KEY_BYTES)
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        gate.verify_approved(gate.load_plan(pid))


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_key_is_32_bytes_owner_only_and_reused(gate):
    _approved(gate)
    key = signing.key_path(gate.plans_dir)
    first = key.read_bytes()
    assert len(first) == 32
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    _approved(gate)
    assert key.read_bytes() == first


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_key_readable_by_others_is_refused_for_signing_and_verifying(gate):
    pid = _approved(gate)
    key = signing.key_path(gate.plans_dir)
    os.chmod(key, 0o644)
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        gate.verify_approved(gate.load_plan(pid))
    other = gate.create_plan([{"tool": SET, "arguments": _args(2)}], [{}])["plan_id"]
    with pytest.raises(ValueError, match="readable by other users.*not approved"):
        human_approve(gate, other)
    assert gate.load_plan(other)["state"] == "pending"


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")
def test_symlinked_key_is_refused(gate, tmp_path):
    pid = _approved(gate)
    key = signing.key_path(gate.plans_dir)
    elsewhere = tmp_path / "elsewhere.key"
    elsewhere.write_bytes(key.read_bytes())
    os.chmod(elsewhere, 0o600)
    key.unlink()
    key.symlink_to(elsewhere)
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        gate.verify_approved(gate.load_plan(pid))


@pytest.mark.anyio
async def test_key_is_never_in_tool_output_or_logs(tmp_path, caplog):
    approval, _ = _provider(tmp_path)
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": _args()}]})
    with caplog.at_level("DEBUG"):
        approved = await panel_decide(approval, "approve_plan", plan["plan_id"])
        result = await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    key = signing.key_path(approval.gate.plans_dir).read_bytes()
    text = json.dumps([approved, result]) + caplog.text
    assert key.hex() not in text and key.hex().upper() not in text
    assert repr(key) not in text


def test_key_lives_in_the_reserved_plans_folder(tmp_path):
    from revit_mcp_server.errors import WorkspaceViolation

    gate = ApprovalGate(tmp_path, "ask_first")
    _approved(gate)
    with pytest.raises(WorkspaceViolation):
        WorkspaceMonitor([tmp_path]).assert_in_workspace(signing.key_path(gate.plans_dir))


@pytest.mark.anyio
async def test_rollback_needs_a_verified_approval_record(tmp_path):
    approval, store = _provider(tmp_path)
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": _args()}]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    executed = approval.gate.load_plan(plan["plan_id"])
    assert executed["state"] == "executed"
    del executed["approval_sig"]
    _rewrite(approval.gate, executed)
    writes = store.writes
    with pytest.raises(BridgeError, match=NOT_VERIFIED):
        await panel_decide(approval, "rollback_plan", plan["plan_id"])
    assert store.writes == writes


# ---- #314: Auto mode keeps the claim markers --------------------------------------------


def _reset_on_disk(gate, pid):
    """Put the plan back to approved with every action pending, as an edit on disk would."""
    plan = gate.load_plan(pid)
    plan["state"] = "approved"
    plan.pop("executed_at", None)
    for action in plan["actions"]:
        action["state"] = "pending"
        action.pop("claimed_at", None)
    _rewrite(gate, plan)


@pytest.mark.anyio
@pytest.mark.parametrize("auto", ["timed", "configured"])
async def test_auto_mode_never_reruns_a_reset_action(tmp_path, auto):
    approval, store = _provider(tmp_path, mode="auto" if auto == "configured" else "required")
    plan = await approval.execute_tool("plan_actions", {"actions": [{"tool": SET, "arguments": _args()}]})
    pid = plan["plan_id"]
    await panel_decide(approval, "approve_plan", pid)
    if auto == "timed":
        override_mod.enable_auto(approval.gate.workspace_dir, 10, token=TOKEN)
    assert approval.gate.approval_mode == "auto" and not approval.gate.dev_mode
    first = await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert first["ok"] is True and store.writes == 1

    _reset_on_disk(approval.gate, pid)
    with pytest.raises(BridgeError, match="at most once"):
        await approval.execute_tool("execute_plan", {"plan_id": pid})
    with pytest.raises(BridgeError, match="at most once"):
        approval.gate.claim_action(SET, {**_args(), "plan_id": pid})
    assert store.writes == 1


@pytest.mark.parametrize("auto", ["timed", "configured"])
def test_auto_mode_claims_actions_of_an_unapproved_plan_once(tmp_path, auto):
    gate = ApprovalGate(tmp_path / "ws", "auto" if auto == "configured" else "ask_first")
    gate.override_token = TOKEN
    if auto == "timed":
        override_mod.enable_auto(gate.workspace_dir, 10, token=TOKEN)
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    claim = gate.claim_action(SET, {**_args(), "plan_id": pid})
    assert claim and claim["plan_id"] == pid
    gate.finish_action(claim, ok=True)
    _reset_on_disk(gate, pid)
    plan = gate.load_plan(pid)
    plan["state"] = "pending"
    _rewrite(gate, plan)
    with pytest.raises(BridgeError, match="at most once"):
        gate.claim_action(SET, {**_args(), "plan_id": pid})


@pytest.mark.parametrize("auto", ["timed", "configured"])
def test_auto_mode_still_allows_unplanned_and_unmatched_calls(tmp_path, auto):
    gate = ApprovalGate(tmp_path / "ws", "auto" if auto == "configured" else "ask_first")
    gate.override_token = TOKEN
    if auto == "timed":
        override_mod.enable_auto(gate.workspace_dir, 10, token=TOKEN)
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    assert gate.claim_action(SET, _args()) is None
    assert gate.claim_action(SET, {**_args(2), "plan_id": pid}) is None
    assert gate.claim_action(SET, {**_args(), "plan_id": "plan_000000000000"}) is None
