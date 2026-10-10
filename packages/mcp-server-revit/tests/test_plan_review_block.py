"""The plan hash covers the review block (rationale, citations, warnings), so an approval
binds to what the person read, and plans without a review keep verifying."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from helpers import human_approve, panel_decide
from revit_mcp_server import approve_cli
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import proof
from revit_mcp_server.security.approval import ApprovalGate, plan_hash
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_approval_provider import FakeParamStore

SET = "revit_set_parameter_value"


def _act(eid=1, value="60"):
    return {"tool": SET, "arguments": {"element_id": eid, "parameter_name": "FireRating", "value": value}}


REVIEW = {
    "summary": "Raise fire rating to 60",
    "reasoning": "Corridor walls need 60 min.\nSee clause.",
    "citations": [{"rule_id": "FIRE-001", "clause": "B3.2", "source": "Approved Document B"}],
    "assumptions": ["Walls are load bearing"],
    "excluded": [{"element_id": 9, "reason": "linked model"}],
    "warnings": ["Check with the fire engineer"],
}


def _rewrite(gate, plan_id, mutate):
    plan = gate.load_plan(plan_id)
    mutate(plan)
    path = gate.plans_dir / f"{plan_id}.json"
    path.write_text(json.dumps(plan), encoding="utf-8")


@pytest.fixture
def gate(tmp_path):
    return ApprovalGate(tmp_path, "required")


@pytest.fixture
def env(tmp_path):
    registry = ProviderRegistry()
    approval = ApprovalProvider(WorkspaceMonitor([tmp_path]), registry, approval_mode="required")
    registry.register(approval)
    store = FakeParamStore({1: {"FireRating": "30"}, 2: {"FireRating": "45"}})
    registry.register(store)
    return tmp_path, approval, store


# ---- the finding: editing reviewable text after approval --------------------------


def test_editing_review_after_approval_blocks_execution(gate):
    pid = gate.create_plan([_act()], [{}], review=REVIEW)["plan_id"]
    human_approve(gate, pid)
    plan = gate.load_plan(pid)
    gate.verify_approved(plan)  # intact: fine
    _rewrite(gate, pid, lambda p: p["review"].update(reasoning="Harmless cosmetic change"))
    with pytest.raises(BridgeError, match="changed after it was approved"):
        gate.verify_approved(gate.load_plan(pid))
    with pytest.raises(BridgeError):
        gate.claim_action(SET, {"element_id": 1, "parameter_name": "FireRating", "value": "60", "plan_id": pid})


def test_editing_review_between_show_and_approve_is_refused(gate):
    pid = gate.create_plan([_act()], [{}], review=REVIEW)["plan_id"]
    shown = plan_hash(gate.load_plan(pid))
    _rewrite(gate, pid, lambda p: p["review"]["warnings"].clear())
    with pytest.raises(ValueError, match="not the plan that was shown"):
        gate.update_plan_state(pid, "approved", via="cli", expected_hash=shown)


def test_removing_review_or_downgrading_is_refused(gate):
    pid = gate.create_plan([_act()], [{}], review=REVIEW)["plan_id"]
    human_approve(gate, pid)

    def strip(p):
        p.pop("review")
        p.pop("hash_version")
    _rewrite(gate, pid, strip)
    with pytest.raises(BridgeError):
        gate.verify_approved(gate.load_plan(pid))


def test_old_plan_cannot_gain_an_unhashed_review(gate):
    pid = gate.create_plan([_act()], [{}])["plan_id"]
    _rewrite(gate, pid, lambda p: p.update(review={"summary": "injected"}))
    with pytest.raises(ValueError, match="inconsistent"):
        plan_hash(gate.load_plan(pid))
    with pytest.raises(ValueError):
        gate.update_plan_state(pid, "approved", via="cli", expected_hash="sha256:x")
    # version 2 without a review is mixed too
    pid2 = gate.create_plan([_act()], [{}])["plan_id"]
    _rewrite(gate, pid2, lambda p: p.update(hash_version=2))
    with pytest.raises(ValueError, match="inconsistent"):
        plan_hash(gate.load_plan(pid2))


def test_metadata_in_extra_is_not_hashed_and_is_listed(gate):
    plan = gate.create_plan([_act()], [{}], extra={"reasoning": "free text", "reverts_plan_id": None}, review=REVIEW)
    assert "reasoning" in proof.unhashed_metadata_keys(plan)
    before = plan_hash(plan)
    plan["reasoning"] = "changed"
    assert plan_hash(plan) == before  # documented: metadata is not approved content


def test_extra_cannot_smuggle_review_or_hash_fields(gate):
    for key in ("review", "hash_version", "plan_hash", "approved_hash"):
        with pytest.raises(BridgeError, match="extra"):
            gate.create_plan([_act()], [{}], extra={key: {}})


# ---- schema, caps ------------------------------------------------------------------


@pytest.mark.parametrize("bad", [
    {"unknown": 1},
    {"summary": 5},
    {"summary": "x" * 2001},
    {"reasoning": "x" * 8001},
    {"citations": "nope"},
    {"citations": [{"rule_id": "A", "extra": 1}]},
    {"citations": [{"clause": "no rule id"}]},
    {"citations": [{"rule_id": "x" * 501}]},
    {"assumptions": [1]},
    {"assumptions": ["x"] * 101},
    {"excluded": [{"element_id": True, "reason": "r"}]},
    {"excluded": [{"element_id": 1, "reason": "r", "extra": 1}]},
    {"warnings": [{"a": 1}]},
])
def test_invalid_review_is_rejected(gate, bad):
    with pytest.raises(BridgeError, match="Invalid review block"):
        gate.create_plan([_act()], [{}], review=bad)


def test_review_size_cap(gate):
    big = {"assumptions": ["x" * 1000] * 100}  # 100 KB of text, within per-field limits
    with pytest.raises(BridgeError, match="too large"):
        gate.create_plan([_act()], [{}], review=big)
    with pytest.raises(BridgeError, match="Invalid review"):
        gate.create_plan([_act()], [{}], review="not an object")


def test_review_is_canonicalised_and_stores_text_as_given(gate):
    nasty = "evil\x1b[2J‮ABC"
    plan = gate.create_plan([_act()], [{}], review={"summary": nasty})
    assert plan["review"]["summary"] == nasty
    assert plan["review"]["citations"] == [] and plan["review"]["warnings"] == []
    assert set(plan["review"]) == set(proof.REVIEW_KEYS)
    assert plan["hash_version"] == 2


# ---- display ------------------------------------------------------------------------


def test_cli_show_prints_review_escaped(gate, capsys):
    review = {"summary": "ok\x1b[31mRED", "reasoning": "line1\nline2‮hidden",
              "citations": [{"rule_id": "R\x07", "clause": "c", "source": "s"}],
              "warnings": ["w\rcarriage"]}
    pid = gate.create_plan([_act()], [{}], review=review)["plan_id"]
    out = approve_cli.describe_plan(gate.load_plan(pid))
    for raw in ("\x1b", "‮", "\x07", "\r"):
        assert raw not in out
    assert "\\x1b" in out and "\\u202e" in out and "\\x07" in out and "\\x0d" in out
    assert "line1" in out and "line2" in out and "covered by the plan hash" in out
    assert "Not part of the approval" not in out  # review and reverts_plan_id are hashed, so not listed


def test_cli_show_lists_unhashed_metadata_and_malformed_review_blocks_approval(gate, capsys):
    pid = gate.create_plan([_act()], [{}], extra={"note_from_model": "hi"}, review=REVIEW)["plan_id"]
    assert "note_from_model" in approve_cli.describe_plan(gate.load_plan(pid))
    _rewrite(gate, pid, lambda p: p["review"].update(sneaky=1))
    plan = gate.load_plan(pid)
    assert any("review block is invalid" in r for r in approve_cli.malformed_reasons(plan))
    assert "MALFORMED" in approve_cli.describe_plan(plan)
    assert approve_cli.main(["--workspace", str(gate.workspace_dir), "approve", pid, "--yes"]) == 1
    assert gate.load_plan(pid)["state"] == "pending"


# ---- old plans ---------------------------------------------------------------------


def _legacy_hash(plan):
    content = {
        "plan_id": plan.get("plan_id"), "created_at": plan.get("created_at"),
        "snapshot_id": plan.get("snapshot_id"), "skipped": plan.get("skipped", []),
        "actions": [{"action_id": a["action_id"], "tool": a["tool"],
                     "arguments": {k: v for k, v in a["arguments"].items() if k != "plan_id"},
                     "before": (a.get("diff") or {}).get("before")} for a in plan["actions"]],
    }
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


@pytest.mark.anyio
async def test_old_plan_without_review_still_approves_and_executes(env):
    tmp_path, approval, store = env
    plan = await approval.execute_tool("plan_actions", {"actions": [_act(1), _act(2)]})
    pid = plan["plan_id"]
    assert "review" not in plan and "hash_version" not in plan
    assert plan["plan_hash"] == _legacy_hash(plan)  # the original rule, unchanged
    await panel_decide(approval, "approve_plan", pid)
    result = await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert result["state"] == "executed" and store.values[1]["FireRating"] == "60"


@pytest.mark.anyio
async def test_plan_actions_with_review_approves_executes_and_proof_hash_matches(env):
    _, approval, store = env
    plan = await approval.execute_tool("plan_actions", {"actions": [_act(1)], "review": REVIEW})
    pid = plan["plan_id"]
    assert plan["hash_version"] == 2 and plan["review"]["citations"][0]["rule_id"] == "FIRE-001"
    await panel_decide(approval, "approve_plan", pid)
    _rewrite(approval.gate, pid, lambda p: p["review"].update(summary="swapped after approval"))
    with pytest.raises(BridgeError):
        await approval.execute_tool("execute_plan", {"plan_id": pid})
    assert store.values[1]["FireRating"] == "30"  # nothing was written


@pytest.mark.anyio
async def test_plan_actions_rejects_invalid_review(env):
    _, approval, _ = env
    with pytest.raises(BridgeError, match="Invalid review"):
        await approval.execute_tool("plan_actions", {"actions": [_act(1)], "review": {"bogus": 1}})


# ---- plan_revert --------------------------------------------------------------------


@pytest.mark.anyio
async def test_plan_revert_puts_conflicts_notes_and_warnings_in_the_hashed_review(env):
    _, approval, store = env
    plan = await approval.execute_tool("plan_actions", {"actions": [_act(1), _act(2)]})
    pid = plan["plan_id"]
    await panel_decide(approval, "approve_plan", pid)
    await approval.execute_tool("execute_plan", {"plan_id": pid})
    store.values[2]["FireRating"] = "90"
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid, "allow_conflicts": True})
    for loose in ("conflicts", "notes", "warnings"):
        assert loose not in revert  # nothing reviewable sits outside the hash
    assert revert["hash_version"] == 2 and revert["reverts_plan_id"] == pid
    assert any("CONFLICT 2/FireRating" in w for w in revert["review"]["warnings"])
    # editing the conflict warning after drafting changes the hash (so approval is refused)
    gate = approval.gate
    shown = plan_hash(gate.load_plan(revert["plan_id"]))
    _rewrite(gate, revert["plan_id"], lambda p: p["review"]["warnings"].clear())
    with pytest.raises(ValueError, match="not the plan that was shown"):
        gate.update_plan_state(revert["plan_id"], "approved", via="cli", expected_hash=shown)
    # and the CLI shows the conflict
    assert "CONFLICT 2/FireRating" in approve_cli.describe_plan(copy.deepcopy(revert))
