"""ADR 0017: approvals and drafts expire, and a plan is bound to the Revit document it was drafted for.

Every rule here only makes approval stricter. None of it can be reached from tool arguments."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from helpers import human_approve, panel_decide
from test_approval_provider import FakeParamStore
from revit_mcp_server import approve_cli
from revit_mcp_server.config import APPROVAL_TTL_DEFAULT, PENDING_TTL_DEFAULT, Config, normalize_ttl
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import proof as proof_mod
from revit_mcp_server.security.approval import ApprovalExpired, ApprovalGate, plan_hash
from revit_mcp_server.security.workspace import WorkspaceMonitor

SET = "revit_set_parameter_value"
HOUR = 3600
DAY = 86400


def _args(element_id=1, value="60", **extra):
    return {"element_id": element_id, "parameter_name": "FireRating", "value": value, **extra}


def _stamp(plan_id, gate, key, seconds_ago):
    """Move a stored timestamp (approved_at / created_at) into the past, outside the hash."""
    plan = gate.load_plan(plan_id)
    plan[key] = (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()
    gate.save_plan(plan)


def _approved(gate, **kw):
    plan = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], **kw)
    human_approve(gate, plan["plan_id"])
    return plan["plan_id"]


def ctx(guid="g-1", title="Villa", view=311, version="2024"):
    return {"ok": True, "revit": {"version": version},
            "document": {"title": title, "guid": guid, "is_workshared": False, "central_path": None,
                         "active_view": {"id": view, "name": "Level 1"}}}


@pytest.fixture
def gate(tmp_path):
    return ApprovalGate(tmp_path, "ask_first", approval_ttl=8 * HOUR, pending_ttl=14 * DAY)


# ---- config -------------------------------------------------------------------------


def test_ttl_defaults_and_fail_closed_parsing(monkeypatch):
    assert APPROVAL_TTL_DEFAULT == 8 * HOUR and PENDING_TTL_DEFAULT == 14 * DAY
    assert normalize_ttl("0", 5) == 0 and normalize_ttl(" 60 ", 5) == 60 and normalize_ttl(90, 5) == 90
    for bad in (-1, "-5", -0.5, "-0.5", "0.5", "-1e-9999", "1e-9999",
                "soon", None, True, "", float("nan"), float("inf")):
        assert normalize_ttl(bad, 5) == 5  # restrictive default, never "off"
    monkeypatch.setenv("MCP_REVIT_APPROVAL_TTL", "120")
    monkeypatch.setenv("MCP_REVIT_PENDING_TTL", "0")
    cfg = Config()
    assert cfg.approval_ttl == 120 and cfg.pending_ttl == 0
    monkeypatch.setenv("MCP_REVIT_APPROVAL_TTL", "abc")
    assert Config().approval_ttl == APPROVAL_TTL_DEFAULT


@pytest.mark.parametrize("value", ["-0.5", "0.5", "-1e-9999", "1e-9999"])
def test_fractional_ttl_configuration_keeps_expiry_enabled(monkeypatch, value):
    monkeypatch.setenv("MCP_REVIT_APPROVAL_TTL", value)
    monkeypatch.setenv("MCP_REVIT_PENDING_TTL", value)
    cfg = Config()
    assert cfg.approval_ttl == APPROVAL_TTL_DEFAULT
    assert cfg.pending_ttl == PENDING_TTL_DEFAULT


# ---- approval expiry ----------------------------------------------------------------


def test_expiry_boundary_is_exact(gate):
    pid = _approved(gate)
    plan = gate.load_plan(pid)
    at = datetime.fromisoformat(plan["approved_at"])
    assert gate.expiry_reason(plan, now=at + timedelta(seconds=8 * HOUR)) is None  # on the limit: still valid
    assert gate.expiry_reason(plan, now=at + timedelta(seconds=8 * HOUR, milliseconds=1)) is not None
    assert gate.expiry_reason(plan, now=at) is None


def test_clock_set_back_or_missing_time_counts_as_expired(gate):
    plan = gate.load_plan(_approved(gate))
    at = datetime.fromisoformat(plan["approved_at"])
    assert gate.expiry_reason(plan, now=at - timedelta(seconds=1)) is not None
    del plan["approved_at"]
    assert gate.expiry_reason(plan) is not None


def test_just_inside_ttl_still_executes_and_ttl_zero_never_expires(tmp_path):
    gate = ApprovalGate(tmp_path, "ask_first", approval_ttl=100)
    pid = _approved(gate)
    _stamp(pid, gate, "approved_at", 95)
    claim = gate.claim_action(SET, {**_args(), "plan_id": pid})
    assert claim["plan_id"] == pid

    off = ApprovalGate(tmp_path / "off", "ask_first", approval_ttl=0)
    pid = _approved(off)
    _stamp(pid, off, "approved_at", 400 * DAY)
    assert off.claim_action(SET, {**_args(), "plan_id": pid})["plan_id"] == pid


def test_expired_approval_cannot_execute_and_moves_to_expired(gate):
    pid = _approved(gate)
    _stamp(pid, gate, "approved_at", 8 * HOUR + 5)
    with pytest.raises(ApprovalExpired, match="A person must approve again"):
        gate.claim_action(SET, {**_args(), "plan_id": pid})
    stored = gate.load_plan(pid)
    assert stored["state"] == "expired" and stored["expired_reason"] == "approval_ttl" and stored["expired_at"]
    assert stored["actions"][0]["state"] == "pending"  # nothing ran, nothing consumed
    with pytest.raises(BridgeError, match="'expired', not 'approved'"):
        gate.claim_action(SET, {**_args(), "plan_id": pid})
    with pytest.raises(BridgeError):
        gate.check_tool_execution(SET, {**_args(), "plan_id": pid})


def test_expired_plan_cannot_be_approved_again(gate):
    pid = _approved(gate)
    _stamp(pid, gate, "approved_at", 9 * HOUR)
    with pytest.raises(ApprovalExpired):
        gate.claim_action(SET, {**_args(), "plan_id": pid})
    with pytest.raises(ValueError, match="only a pending plan can be approved"):
        human_approve(gate, pid)
    assert gate.load_plan(pid)["state"] == "expired"


def test_expired_state_cannot_be_forged_back_by_editing_state_only(gate):
    """Setting state back to approved on an expired plan still hits the age check."""
    pid = _approved(gate)
    _stamp(pid, gate, "approved_at", 9 * HOUR)
    forged = gate.load_plan(pid)
    forged["state"] = "approved"
    gate.save_plan(forged)
    with pytest.raises(ApprovalExpired):
        gate.claim_action(SET, {**_args(), "plan_id": pid})


# ---- pending expiry -----------------------------------------------------------------


def test_expired_pending_is_hidden_counted_and_never_deleted(gate):
    old = gate.create_plan([{"tool": SET, "arguments": _args(1)}], [{}])["plan_id"]
    fresh = gate.create_plan([{"tool": SET, "arguments": _args(2)}], [{}])["plan_id"]
    _stamp(old, gate, "created_at", 14 * DAY + 60)
    plans, hidden = gate.pending_listing()
    assert [p["plan_id"] for p in plans] == [fresh] and hidden == 1
    assert [p["plan_id"] for p in gate.list_pending_plans()] == [fresh]
    shown, hidden = gate.pending_listing(include_expired=True)
    assert {p["plan_id"] for p in shown} == {old, fresh} and hidden == 0
    assert next(p for p in shown if p["plan_id"] == old)["expired"] is True
    assert (gate.plans_dir / f"{old}.json").exists() and gate.load_plan(old)["state"] == "pending"


def test_expired_pending_cannot_be_approved_but_can_be_rejected(gate):
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    shown = plan_hash(gate.load_plan(pid))
    _stamp(pid, gate, "created_at", 15 * DAY)
    with pytest.raises(ValueError, match="expired"):
        gate.update_plan_state(pid, "approved", via="cli", expected_hash=shown)
    assert gate.load_plan(pid)["state"] == "pending"
    gate.update_plan_state(pid, "rejected", via="cli")
    assert gate.load_plan(pid)["state"] == "rejected"


def test_pending_ttl_zero_keeps_old_drafts_listed(tmp_path):
    gate = ApprovalGate(tmp_path, "ask_first", pending_ttl=0)
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    _stamp(pid, gate, "created_at", 400 * DAY)
    stored = gate.load_plan(pid)
    stored["plan_hash"] = plan_hash(stored)  # created_at is hashed: re-hash the aged draft
    gate.save_plan(stored)
    assert gate.pending_listing() == ([stored], 0)
    human_approve(gate, pid)


def test_cli_list_hides_expired_and_all_shows_them(gate, monkeypatch, capsys):
    old = gate.create_plan([{"tool": SET, "arguments": _args(1)}], [{}])["plan_id"]
    fresh = gate.create_plan([{"tool": SET, "arguments": _args(2)}], [{}])["plan_id"]
    _stamp(old, gate, "created_at", 20 * DAY)
    monkeypatch.setattr(approve_cli, "_gate", lambda ws: gate)
    assert approve_cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert fresh in out and old not in out and "1 expired pending plan(s) not shown" in out
    assert approve_cli.main(["list", "--all"]) == 0
    out = capsys.readouterr().out
    assert old in out and "[EXPIRED]" in out and "not shown" not in out


def test_cli_refuses_to_approve_an_expired_plan_and_show_says_why(gate, monkeypatch, capsys):
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    _stamp(pid, gate, "created_at", 20 * DAY)
    monkeypatch.setattr(approve_cli, "_gate", lambda ws: gate)
    assert approve_cli.main(["show", pid]) == 0
    assert "EXPIRED:" in capsys.readouterr().out
    assert approve_cli.main(["approve", pid, "--yes"]) == 1
    assert "has expired" in capsys.readouterr().err
    assert gate.load_plan(pid)["state"] == "pending"


def test_cli_bulk_reject_still_clears_expired_drafts(gate, monkeypatch, capsys):
    pid = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}])["plan_id"]
    _stamp(pid, gate, "created_at", 20 * DAY)
    monkeypatch.setattr(approve_cli, "_gate", lambda ws: gate)
    assert approve_cli.main(["reject", "--all-pending", "--yes"]) == 0
    assert gate.load_plan(pid)["state"] == "rejected"


# ---- document binding ---------------------------------------------------------------


@pytest.fixture
def provider(tmp_path):
    registry = ProviderRegistry()
    approval = ApprovalProvider(WorkspaceMonitor([tmp_path]), registry, approval_mode="required")
    registry.register(approval)
    registry.register(FakeParamStore({1: {"FireRating": "30"}}))
    approval.gate.approval_ttl, approval.gate.pending_ttl = 8 * HOUR, 14 * DAY
    live = {"context": ctx()}
    approval.gate.binding_probe = lambda: live["context"]
    return approval, live


async def _draft(approval, **arguments):
    return await approval.execute_tool(
        "plan_actions", {"actions": [{"tool": SET, "arguments": _args(**arguments)}]})


@pytest.mark.anyio
async def test_draft_stores_a_hashed_binding_and_same_document_executes(provider):
    approval, live = provider
    plan = await _draft(approval)
    assert plan["binding"] == {"doc_guid": "g-1", "central_path_hash": None, "doc_title": "Villa",
                               "revit_version": "2024", "active_view_id": None}
    assert proof_mod.plan_content_hash(plan) == plan["plan_hash"]
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    live["context"] = ctx(view=999)  # another view is fine: this plan is not view-specific
    result = await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert result["ok"] is True and result["state"] == "executed"


@pytest.mark.anyio
async def test_other_document_is_refused_and_nothing_is_consumed(provider):
    approval, live = provider
    plan = await _draft(approval)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    live["context"] = ctx(guid="g-2", title="Office")
    with pytest.raises(BridgeError) as refused:
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    error = str(refused.value)
    assert "'Villa'" in error and "'Office'" in error and "Nothing ran" in error
    stored = approval.gate.load_plan(plan["plan_id"])
    assert stored["state"] == "approved" and stored["actions"][0]["state"] == "pending"
    with pytest.raises(BridgeError, match="was drafted for Revit document"):
        approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})
    live["context"] = ctx()  # back in the right model: the same approval still works
    assert approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})


@pytest.mark.anyio
async def test_bound_plan_with_unreadable_live_document_fails_closed(provider):
    approval, live = provider
    plan = await _draft(approval)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    for broken in ({"ok": True, "document": None, "busy": True}, {"mock": True}):
        live["context"] = broken
        with pytest.raises(BridgeError, match="could not be read"):
            approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})

    def boom():
        raise BridgeError("Revit is gone")
    approval.gate.binding_probe = boom
    with pytest.raises(BridgeError, match="could not be read"):
        approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})
    approval.gate.binding_probe = None
    with pytest.raises(BridgeError, match="could not be read"):
        approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})


@pytest.mark.anyio
async def test_null_binding_is_recorded_and_never_refuses(provider):
    approval, live = provider
    live["context"] = {"ok": True, "mock": True, "server": {}}  # mock mode: no Revit
    plan = await _draft(approval)
    assert plan["binding"] is None and "binding" in plan
    assert proof_mod.plan_content_hash(plan) == plan["plan_hash"]
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    live["context"] = ctx(guid="anything-else")
    claim = approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})
    assert claim["plan_id"] == plan["plan_id"]


@pytest.mark.anyio
async def test_no_probe_and_probe_errors_at_draft_time_give_a_null_binding(provider):
    approval, live = provider
    approval.gate.binding_probe = None
    assert (await _draft(approval))["binding"] is None

    def boom():
        raise RuntimeError("no bridge")
    approval.gate.binding_probe = boom
    assert (await _draft(approval, element_id=1))["binding"] is None


@pytest.mark.anyio
async def test_view_specific_actions_also_bind_the_active_view(provider):
    approval, live = provider
    plan = await _draft(approval, view_id=311)
    assert plan["binding"]["active_view_id"] == 311
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    live["context"] = ctx(view=312)
    with pytest.raises(BridgeError, match="active view id"):
        approval.gate.claim_action(SET, {**_args(view_id=311), "plan_id": plan["plan_id"]})


@pytest.mark.anyio
async def test_workshared_central_path_is_stored_as_a_hash_only(provider):
    approval, live = provider
    live["context"] = {"revit": {"version": "2024"}, "document": {
        "title": "Tower_jane", "guid": None, "is_workshared": True, "central_path": "C:/Central/Tower.rvt",
        "active_view": {"id": 1}}}
    plan = await _draft(approval)
    assert plan["binding"]["central_path_hash"].startswith("sha256:")
    assert "Central" not in json.dumps(plan["binding"])
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    live["context"]["document"]["central_path"] = "C:/Other/Tower.rvt"
    with pytest.raises(BridgeError, match="central model path differs"):
        approval.gate.claim_action(SET, {**_args(), "plan_id": plan["plan_id"]})


@pytest.mark.anyio
async def test_revert_plans_are_bound_too(provider):
    approval, live = provider
    plan = await _draft(approval)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    revert = await approval.execute_tool("plan_revert", {"plan_id": plan["plan_id"]})
    assert revert["binding"]["doc_guid"] == "g-1"


@pytest.mark.anyio
async def test_expired_running_plan_finishes_with_proof_and_can_be_reverted(provider, monkeypatch):
    approval, live = provider
    store = approval.registry.lookup_tool_provider(SET)
    execute = store.execute_tool

    async def delayed_write(name, arguments):
        result = await execute(name, arguments)
        if name == SET:
            return {"status": "running", "request_id": "delayed-write"}
        return result

    monkeypatch.setattr(store, "execute_tool", delayed_write)
    plan = await _draft(approval)
    pid = plan["plan_id"]
    await panel_decide(approval, "approve_plan", pid)
    result = await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert result["pending_results"] and approval.gate.load_proof(pid) is None
    _stamp(pid, approval.gate, "approved_at", 9 * HOUR)
    with pytest.raises(ApprovalExpired):
        await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert approval.gate.settle_in_flight("delayed-write", ok=True)
    assert approval.gate.load_plan(pid)["state"] == "executed"
    assert approval.gate.load_proof(pid)["outcome"] == "success"
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid})
    assert revert["actions"][0]["arguments"]["value"] == "30"


@pytest.mark.anyio
async def test_expiry_between_actions_preserves_partial_proof_and_blocks_the_rest(provider, monkeypatch):
    approval, live = provider
    store = approval.registry.lookup_tool_provider(SET)
    execute = store.execute_tool
    plan = await approval.execute_tool("plan_actions", {
        "actions": [{"tool": SET, "arguments": _args(element_id=i)} for i in (1, 2)]})
    pid = plan["plan_id"]
    await panel_decide(approval, "approve_plan", pid)

    async def expire_after_write(name, arguments):
        result = await execute(name, arguments)
        if name == SET:
            _stamp(pid, approval.gate, "approved_at", 9 * HOUR)
        return result

    monkeypatch.setattr(store, "execute_tool", expire_after_write)
    result = await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert result["ok"] is False and result["state"] == "partial"
    assert store.values == {1: {"FireRating": "60"}}
    proof = approval.gate.load_proof(pid)
    assert proof["outcome"] == "partial"
    assert [e["element_id"] for e in proof["elements"]] == [1]
    with pytest.raises(ValueError, match="not 'approved'"):
        await approval.execute_tool("execute_plan", {"plan_id": pid})
    with pytest.raises(ValueError, match="only a pending plan"):
        await panel_decide(approval, "approve_plan", pid)


# ---- hash compatibility -------------------------------------------------------------

OLD_ACTION = {"action_id": "act_0123456789ab", "tool": SET, "state": "pending",
              "arguments": {"element_id": 1, "parameter_name": "FireRating", "value": "60"},
              "diff": {"before": {"1": {"FireRating": "30"}}}}
# Hashes produced by the code before binding existed (origin/dev), for these exact plans.
OLD_V1_HASH = "sha256:33da61c60e6007411d9e9832a02ec3d2cadcbcadf7f8fa78fe8eb45f463f6b32"
OLD_V2_HASH = "sha256:0a5afc88a384323e0b9e05d12c2b99bdf550bd24528c325dd48c3930cad5f33c"


def _old_plan(**more):
    return {"plan_id": "plan_0123456789ab", "created_at": "2026-01-01T00:00:00+00:00", "state": "pending",
            "actions": [json.loads(json.dumps(OLD_ACTION))], **more}


def test_old_stored_plans_without_binding_still_verify_and_execute(tmp_path):
    gate = ApprovalGate(tmp_path, "ask_first", pending_ttl=0)  # the fixed 2026-01-01 draft is "old"
    v1 = _old_plan()
    v2 = _old_plan(hash_version=2, review=proof_mod.normalize_review({"summary": "s"}))
    assert proof_mod.plan_content_hash(v1) == OLD_V1_HASH
    assert proof_mod.plan_content_hash(v2) == OLD_V2_HASH
    assert proof_mod.unhashed_metadata_keys(v1) == [] and "binding" not in v1

    v1["plan_hash"] = OLD_V1_HASH
    gate.save_plan(v1)
    human_approve(gate, v1["plan_id"])
    assert gate.claim_action(SET, {**OLD_ACTION["arguments"], "plan_id": v1["plan_id"]})  # no binding: no check


def test_binding_cannot_be_added_removed_or_edited_after_the_hash(gate):
    plan = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], binding={
        "doc_guid": "g-1", "central_path_hash": None, "doc_title": "Villa", "revit_version": "2024",
        "active_view_id": None})
    pid = plan["plan_id"]
    human_approve(gate, pid)
    stored = gate.load_plan(pid)
    del stored["binding"]  # strip it to dodge the check
    gate.save_plan(stored)
    with pytest.raises(BridgeError, match="changed after it was approved"):
        gate.claim_action(SET, {**_args(), "plan_id": pid})

    other = gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], binding=None)["plan_id"]
    edited = gate.load_plan(other)
    edited["binding"] = {"doc_guid": "g-2"}
    gate.save_plan(edited)
    with pytest.raises(ValueError):
        human_approve(gate, other)


def test_malformed_binding_is_refused(gate):
    with pytest.raises(BridgeError, match="malformed document binding"):
        gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], binding={"evil": 1})
    with pytest.raises(ValueError, match="malformed document binding"):
        proof_mod.plan_content_hash(_old_plan(binding="Villa"))


# ---- nothing here can be bypassed by tool arguments ---------------------------------


@pytest.mark.anyio
async def test_tool_arguments_cannot_set_binding_or_ttl(provider):
    approval, live = provider
    plan = await approval.execute_tool("plan_actions", {
        "actions": [{"tool": SET, "arguments": _args()}],
        "binding": None, "approval_ttl": 0, "pending_ttl": 0, "include_expired": True,
    })
    assert plan["binding"]["doc_guid"] == "g-1"  # taken from the live document, not from the call
    with pytest.raises(BridgeError, match="'extra' cannot set"):
        approval.gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], extra={"binding": None})
    with pytest.raises(BridgeError, match="'extra' cannot set"):
        approval.gate.create_plan([{"tool": SET, "arguments": _args()}], [{}], extra={"expired": False})

    pid = plan["plan_id"]
    await panel_decide(approval, "approve_plan", pid)
    _stamp(pid, approval.gate, "approved_at", 9 * HOUR)
    with pytest.raises(ApprovalExpired):
        await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert approval.gate.load_plan(pid)["state"] == "expired"
    for extra in ({"approval_ttl": 0}, {"force": True}, {"binding": None}, {"include_expired": True}):
        with pytest.raises(ValueError, match="not 'approved'"):
            await approval.execute_tool("execute_plan", {"plan_id": pid, **extra})
    with pytest.raises(BridgeError):
        approval.gate.claim_action(SET, {**_args(), "plan_id": pid, "approval_ttl": 0, "binding": None})
    with pytest.raises(ValueError, match="only a pending plan"):
        await approval.execute_human_tool("approve_plan", {"plan_id": pid, "expected_hash": plan["plan_hash"],
                                                           "approval_ttl": 0}, via="panel")


@pytest.mark.anyio
async def test_expired_pending_cannot_be_approved_even_if_listing_flags_are_passed(provider):
    approval, live = provider
    plan = await _draft(approval)
    _stamp(plan["plan_id"], approval.gate, "created_at", 20 * DAY)
    hidden = await approval.execute_tool("list_pending_plans", {})
    assert hidden["plans"] == [] and hidden["expired_hidden"] == 1
    shown = await approval.execute_tool("list_pending_plans", {"include_expired": True})
    assert [p["plan_id"] for p in shown["plans"]] == [plan["plan_id"]] and shown["expired_hidden"] == 0
    with pytest.raises(ValueError, match="expired"):
        await panel_decide(approval, "approve_plan", plan["plan_id"], include_expired=True, pending_ttl=0)
    assert approval.gate.load_plan(plan["plan_id"])["state"] == "pending"
    # A non-boolean flag does not count as asking for the full list.
    assert (await approval.execute_tool("list_pending_plans", {"include_expired": "yes"}))["plans"] == []


# ---- follow-ups (#152) -----------------------------------------------------------------


def ctx_proc(pid, started="2026-01-01T08:00:00Z", **kw):
    c = ctx(**kw)
    c["revit"].update({"pid": pid, "started_at": started})
    return c


@pytest.mark.anyio
async def test_same_file_in_another_revit_process_is_refused(provider):
    approval, live = provider
    live["context"] = ctx_proc(1)
    plan = await _draft(approval)
    assert plan["binding"]["revit_pid"] == 1 and plan["binding"]["revit_started_at"] == "2026-01-01T08:00:00Z"
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    live["context"] = ctx_proc(2)
    with pytest.raises(BridgeError, match="different Revit process"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    live["context"] = ctx_proc(1, started="2026-01-02T08:00:00Z")  # recycled pid, later start
    with pytest.raises(BridgeError, match="different Revit process"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    live["context"] = ctx()  # a Revit that does not report its process cannot confirm: refused
    with pytest.raises(BridgeError, match="different Revit process"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    live["context"] = ctx_proc(1)
    result = await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert result["state"] == "executed"


@pytest.mark.anyio
async def test_twenty_action_plan_probes_once(provider):
    approval, live = provider
    calls = []

    def probe():
        calls.append(1)
        return live["context"]
    approval.gate.binding_probe = probe
    actions = [{"tool": SET, "arguments": _args(element_id=1, value=str(i))} for i in range(20)]
    plan = await approval.execute_tool("plan_actions", {"actions": actions})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    calls.clear()
    result = await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert result["ok"] is True and len(result["results"]) == 20
    assert len(calls) == 1


@pytest.mark.anyio
async def test_probe_is_repeated_when_the_reused_read_is_too_old(provider, monkeypatch):
    approval, live = provider
    # A frozen clock stands in for Windows' coarse monotonic clock: two reads in the
    # same tick must still not reuse a probe when max_age is 0.
    import revit_mcp_server.security.approval as approval_mod
    monkeypatch.setattr(approval_mod.time, "monotonic", lambda: 100.0)
    calls = []
    approval.gate.binding_probe = lambda: calls.append(1) or live["context"]
    plan = await _draft(approval)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    calls.clear()
    with approval.gate.reuse_binding_probe(max_age_s=0.0):
        approval.gate.verify_binding(approval.gate.load_plan(plan["plan_id"]))
        approval.gate.verify_binding(approval.gate.load_plan(plan["plan_id"]))
    assert len(calls) == 2


@pytest.mark.anyio
async def test_proof_bundle_carries_the_binding(provider):
    approval, live = provider
    plan = await _draft(approval)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    bundle = approval.gate.load_proof(plan["plan_id"])
    assert bundle["binding"] == plan["binding"]


def test_panel_guard_warns_when_redaction_changes_the_binding():
    plan = {"plan_id": "p", "state": "pending", "created_at": "t", "actions": [], "binding": {"doc_title": "Villa"}}
    assert proof_mod.approved_content(plan)["binding"] == {"doc_title": "Villa"}
    assert "binding" not in proof_mod.approved_content({"actions": []})

    def narrow(x):
        return json.loads(json.dumps(x).replace("Villa", "***"))
    out = proof_mod.panel_plans_redacted({"plans": [plan]}, lambda x: x, narrow)
    assert out["plans"][0]["review_view"]["status"] == "invalid"
    out = proof_mod.panel_plans_redacted({"plans": [plan]}, lambda x: x, lambda x: x)
    assert out["plans"][0]["review_view"]["status"] != "invalid"


@pytest.mark.anyio
async def test_refusal_before_the_first_action_leaves_the_plan_approved(provider):
    approval, live = provider
    plan = await _draft(approval)
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    real = approval.gate.claim_action

    def refuse(tool, args):
        raise BridgeError("not now")
    approval.gate.claim_action = refuse
    with pytest.raises(BridgeError, match="not now"):
        await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    stored = approval.gate.load_plan(plan["plan_id"])
    assert stored["state"] == "approved" and stored["actions"][0]["state"] == "pending"
    approval.gate.claim_action = real  # cause fixed: the same plan runs
    result = await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    assert result["ok"] is True and result["state"] == "executed"
