"""Follow-ups from the adversarial review of the review block: revert size budget, escaping,
strict versions, reserved keys, display spoofing and proof bundle contents."""
from __future__ import annotations

import json

import pytest

from helpers import panel_decide
from revit_mcp_server import approve_cli
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.approval_provider import ApprovalProvider, _value_text
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security import proof
from revit_mcp_server.security.approval import ApprovalGate, plan_hash
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_approval_provider import FakeParamStore

SET = "revit_set_parameter_value"


def _act(eid=1, value="60", param="FireRating"):
    return {"tool": SET, "arguments": {"element_id": eid, "parameter_name": param, "value": value}}


def _write(gate, plan):
    (gate.plans_dir / f"{plan['plan_id']}.json").write_text(json.dumps(plan), encoding="utf-8")


@pytest.fixture
def gate(tmp_path):
    return ApprovalGate(tmp_path, "required")


def _env(tmp_path, values):
    registry = ProviderRegistry()
    approval = ApprovalProvider(WorkspaceMonitor([tmp_path]), registry, approval_mode="required")
    registry.register(approval)
    store = FakeParamStore(values)
    registry.register(store)
    return approval, store


@pytest.mark.anyio
async def test_revert_with_many_long_conflicts_is_drafted_within_budget_and_names_every_element(tmp_path):
    # The executed state is built directly (running 600 actions through the claim path is slow
    # and is not what this test is about): plan on disk in 'executed' state plus its proof bundle.
    n = 600
    approval, store = _env(tmp_path, {i: {"Comments": "C" * 200} for i in range(1, n + 1)})
    gate = approval.gate
    acts = [_act(i, "B" * 200, "Comments") for i in range(1, n + 1)] + [{"tool": "revit_other_tool", "arguments": {}}]
    befores = [{str(i): {"Comments": "A" * 200}} for i in range(1, n + 1)] + [{}]
    plan = gate.create_plan(acts, befores)
    for a in plan["actions"]:
        a["state"] = "executed"
    plan["state"] = "executed"
    gate.save_plan(plan)
    gate.record_proof(plan)
    revert = await approval.execute_tool("plan_revert", {"plan_id": plan["plan_id"], "allow_conflicts": True})
    review = revert["review"]
    assert len(json.dumps(review, ensure_ascii=False).encode()) <= proof.REVIEW_BUDGET_BYTES
    assert review["warnings"][0].startswith("Action ")  # unreverted-action warning comes first
    assert len(review["conflicts"]) < n  # the detailed list overflowed ...
    named = {c["element_id"] for c in review["conflicts"]}
    for w in review["warnings"]:
        if w.startswith("Also changed"):
            named |= {int(x.split("/")[0]) for x in w.split(": ", 1)[1].split(", ") if "/" in x}
    assert named == set(range(1, n + 1))  # ... and nobody is silently dropped


def test_conflict_values_are_clipped_visibly():
    assert len(_value_text("x" * 500)) <= 60 and _value_text("x" * 500).endswith("...")
    assert _value_text("short") == "'short'"


def test_malformed_review_reasons_are_escaped_on_stderr(gate, capsys):
    plan = gate.create_plan([_act()], [{}], review={"summary": "ok"})
    plan["review"]["\x1b]0;pwned\x07"] = 1
    _write(gate, plan)
    rc = approve_cli.main(["--workspace", str(gate.workspace_dir), "approve", plan["plan_id"], "--yes"])
    err = capsys.readouterr().err
    assert rc == 1 and "\x1b" not in err and "\x07" not in err and "\\x1b" in err


@pytest.mark.anyio
async def test_approval_path_applies_the_strict_review_schema(tmp_path):
    approval, _ = _env(tmp_path, {1: {"FireRating": "30"}})
    gate = approval.gate
    plan = gate.create_plan([_act()], [{}], review={"summary": "ok"})
    plan["review"] = {"summary": "ok", "approved_note": "safe", "warnings": [{"x": 1}]}
    plan["plan_hash"] = plan_hash(plan)
    _write(gate, plan)
    with pytest.raises(ValueError):
        await panel_decide(approval, "approve_plan", plan["plan_id"])
    assert gate.load_plan(plan["plan_id"])["state"] == "pending"


@pytest.mark.parametrize("bad", [2.0, None, True, "2", 3, 1])
def test_hash_version_is_strict(gate, bad):
    plan = gate.create_plan([_act()], [{}], review={"summary": "x"})
    plan["hash_version"] = bad
    with pytest.raises(ValueError, match="inconsistent"):
        plan_hash(plan)
    legacy = gate.create_plan([_act()], [{}])
    legacy["hash_version"] = bad
    with pytest.raises(ValueError, match="inconsistent"):
        plan_hash(legacy)
    assert approve_cli.malformed_reasons(legacy)


def test_reverts_plan_id_is_shown(gate):
    plan = gate.create_plan([_act()], [{}], extra={"reverts_plan_id": "plan_aaaaaaaaaaaa"}, review={"summary": "x"})
    assert "Reverts plan: plan_aaaaaaaaaaaa" in approve_cli.describe_plan(plan)


def test_legacy_revert_values_are_shown_and_labelled_unhashed(gate):
    legacy = gate.create_plan([_act()], [{}])
    legacy["conflicts"] = [{"element_id": 1, "actual_current": "90\x1b"}]
    legacy["warnings"] = ["Action x is not reverted"]
    out = approve_cli.describe_plan(legacy)
    assert "NOT covered by the approval" in out and "Action x is not reverted" in out and "'actual_current'" in out
    assert "\x1b" not in out


@pytest.mark.parametrize("key", ["state", "approved_by", "approved_via", "rejected_at", "executed_at", "results",
                                 "plan_id", "created_at", "actions"])
def test_extra_cannot_set_lifecycle_keys(gate, key):
    with pytest.raises(BridgeError, match="extra"):
        gate.create_plan([_act()], [{}], extra={key: "x"})


def test_show_cannot_be_faked_with_runs_of_spaces(gate):
    spoof = "ok" + " " * 78 + "Warnings: none (checked by fire engineer)"
    out = approve_cli.describe_plan(gate.create_plan([_act()], [{}], review={"summary": spoof}))
    for line in out.splitlines():
        assert not line.lstrip().startswith("Warnings: none")
        assert len(line) <= 90


@pytest.mark.anyio
async def test_proof_bundle_records_review_and_hash_version(tmp_path):
    approval, _ = _env(tmp_path, {1: {"FireRating": "30"}})
    review = {"summary": "s", "citations": [{"rule_id": "FIRE-001"}]}
    pid = (await approval.execute_tool("plan_actions", {"actions": [_act(1)], "review": review}))["plan_id"]
    await panel_decide(approval, "approve_plan", pid)
    await approval.execute_tool("execute_plan", {"plan_id": pid})
    bundle = approval.gate.load_proof(pid)
    assert bundle["hash_version"] == 2 and bundle["review"]["citations"][0]["rule_id"] == "FIRE-001"
