"""Proof bundles and revert plans for approved parameter fixes."""
from __future__ import annotations

import json

import pytest

from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_approval_provider import FakeParamStore


@pytest.fixture
def env(tmp_path):
    registry = ProviderRegistry()
    approval = ApprovalProvider(WorkspaceMonitor([tmp_path]), registry, approval_mode="required")
    registry.register(approval)
    store = FakeParamStore({1: {"FireRating": "30"}, 2: {"FireRating": "45"}})
    registry.register(store)
    return tmp_path, approval, store


def _acts(*ids, value="60"):
    return [
        {"tool": "revit_set_parameter_value",
         "arguments": {"element_id": i, "parameter_name": "FireRating", "value": value}}
        for i in ids
    ]


async def _run(approval, actions, **plan_kwargs):
    plan = await approval.execute_tool("plan_actions", {"actions": actions, **plan_kwargs})
    pid = plan["plan_id"]
    await approval.execute_tool("approve_plan", {"plan_id": pid, "approver": "coordinator@example.com"})
    result = await approval.execute_tool("execute_plan", {"plan_id": pid})
    return pid, result


def _proof_file(tmp_path, pid):
    return json.loads((tmp_path / "proofs" / f"{pid}.json").read_text(encoding="utf-8"))


@pytest.mark.anyio
async def test_proof_written_on_success(env):
    tmp_path, approval, store = env
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / "snap1.json").write_text(json.dumps({
        "source": {"doc_guid": "guid-1", "doc_title": "Tower.rvt"},
        "elements": [{"uid": "uid-1", "element_id": 1}],
    }), encoding="utf-8")

    pid, result = await _run(
        approval, _acts(1, 2), snapshot_id="snap1",
        skipped=[{"uid": "uid-9", "param": "FireRating", "reason": "read-only"}],
    )
    assert result["state"] == "executed"
    proof = _proof_file(tmp_path, pid)
    assert proof["outcome"] == "success"
    assert proof["plan_id"] == pid
    assert proof["tool"] == "revit_set_parameter_value"
    assert proof["approved_by"] == "coordinator@example.com"
    assert proof["created_at"] and proof["approved_at"] and proof["executed_at"]
    assert proof["document"] == {"snapshot_id": "snap1", "doc_guid": "guid-1", "doc_title": "Tower.rvt"}
    assert proof["plan_hash"].startswith("sha256:")
    assert proof["skipped"][0]["reason"] == "read-only"
    e1 = next(e for e in proof["elements"] if e["element_id"] == 1)
    assert (e1["before"], e1["new"], e1["uid"], e1["parameter"]) == ("30", "60", "uid-1", "FireRating")

    # Hash is reproducible from the stored plan content.
    from revit_mcp_server.security.proof import plan_content_hash
    assert plan_content_hash(approval.gate.load_plan(pid)) == proof["plan_hash"]


@pytest.mark.anyio
async def test_proof_without_approver_says_so(env):
    tmp_path, approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": _acts(1)})
    await approval.execute_tool("approve_plan", {"plan_id": plan["plan_id"]})
    await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    proof = _proof_file(tmp_path, plan["plan_id"])
    assert proof["approved_by"] is None
    assert "not recorded" in proof["approver_note"]
    assert proof["document"] is None


@pytest.mark.anyio
async def test_proof_partial_never_marked_success(env):
    tmp_path, approval, store = env
    store.fail_on.add(2)
    pid, result = await _run(approval, _acts(1, 2))
    assert result["state"] == "partial"
    proof = _proof_file(tmp_path, pid)
    assert proof["outcome"] == "partial"
    assert [e["element_id"] for e in proof["elements"]] == [1]
    assert proof["skipped"][0]["element_id"] == 2
    assert "simulated failure" in proof["skipped"][0]["reason"]


@pytest.mark.anyio
async def test_proof_failed_when_nothing_applied(env):
    tmp_path, approval, store = env
    store.fail_on.update({1, 2})
    pid, _ = await _run(approval, _acts(1, 2))
    proof = _proof_file(tmp_path, pid)
    assert proof["outcome"] == "failed"
    assert proof["elements"] == []
    assert len(proof["skipped"]) == 2


@pytest.mark.anyio
async def test_direct_tool_path_writes_proof(env):
    tmp_path, approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": _acts(1)})
    pid = plan["plan_id"]
    approval.gate.update_plan_state(pid, "approved", approver="someone")
    approval.gate.update_plan_state(pid, "executed")  # what mcp_server/panel do after a direct call
    proof = _proof_file(tmp_path, pid)
    assert proof["approved_by"] == "someone"
    # No per-action result was recorded on this path, so it must not claim success.
    assert proof["outcome"] != "success"


@pytest.mark.anyio
async def test_get_proof_bundle_and_read_only(env):
    tmp_path, approval, _ = env
    pid, _ = await _run(approval, _acts(1))
    before = (tmp_path / "proofs" / f"{pid}.json").read_bytes()
    plan_before = (tmp_path / "plans" / f"{pid}.json").read_bytes()
    bundle = await approval.execute_tool("get_proof_bundle", {"plan_id": pid})
    assert bundle["plan_id"] == pid and bundle["outcome"] == "success"
    assert (tmp_path / "proofs" / f"{pid}.json").read_bytes() == before
    assert (tmp_path / "plans" / f"{pid}.json").read_bytes() == plan_before
    tool = next(t for t in approval.get_capabilities() if t.name == "get_proof_bundle")
    assert tool.is_mutating is False
    with pytest.raises(ValueError, match="No proof bundle"):
        await approval.execute_tool("get_proof_bundle", {"plan_id": "plan_nope"})
    with pytest.raises(ValueError, match="Invalid plan_id"):
        await approval.execute_tool("get_proof_bundle", {"plan_id": "../../etc/passwd"})


@pytest.mark.anyio
async def test_plan_revert_content_and_never_auto_executes(env):
    tmp_path, approval, store = env
    pid, _ = await _run(approval, _acts(1, 2))
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid})
    assert revert["state"] == "pending"
    assert revert["reverts_plan_id"] == pid
    got = {(a["arguments"]["element_id"], a["arguments"]["value"]) for a in revert["actions"]}
    assert got == {(1, "30"), (2, "45")}
    assert all(a["tool"] == "revit_set_parameter_value" for a in revert["actions"])
    assert "conflicts" not in revert
    # Not executed: model still holds the fixed values, and execution is gated.
    assert store.values[1]["FireRating"] == "60"
    with pytest.raises(ValueError, match="not 'approved'"):
        await approval.execute_tool("execute_plan", {"plan_id": revert["plan_id"]})
    # After approval + execution the originals are restored and the revert has its own proof.
    await approval.execute_tool("approve_plan", {"plan_id": revert["plan_id"]})
    await approval.execute_tool("execute_plan", {"plan_id": revert["plan_id"]})
    assert store.values[1]["FireRating"] == "30" and store.values[2]["FireRating"] == "45"
    assert _proof_file(tmp_path, revert["plan_id"])["reverts_plan_id"] == pid


@pytest.mark.anyio
async def test_plan_revert_refused_when_not_executed(env):
    _, approval, store = env
    plan = await approval.execute_tool("plan_actions", {"actions": _acts(1)})
    with pytest.raises(ValueError, match="no proof bundle"):
        await approval.execute_tool("plan_revert", {"plan_id": plan["plan_id"]})

    store.fail_on.add(2)
    pid, _ = await _run(approval, _acts(1, 2))
    with pytest.raises(ValueError, match="'partial'"):
        await approval.execute_tool("plan_revert", {"plan_id": pid})


@pytest.mark.anyio
async def test_plan_revert_refused_when_before_missing(env):
    _, approval, store = env
    store.values[3] = {}  # parameter has no value, so no before value is captured
    pid, _ = await _run(approval, _acts(3))
    with pytest.raises(ValueError, match="no before value was recorded"):
        await approval.execute_tool("plan_revert", {"plan_id": pid})


@pytest.mark.anyio
async def test_plan_revert_refused_when_stale_unless_conflicts_allowed(env):
    _, approval, store = env
    pid, _ = await _run(approval, _acts(1, 2))
    store.values[2]["FireRating"] = "90"  # someone changed it after the fix

    with pytest.raises(ValueError, match="changed since"):
        await approval.execute_tool("plan_revert", {"plan_id": pid})

    revert = await approval.execute_tool("plan_revert", {"plan_id": pid, "allow_conflicts": True})
    assert revert["state"] == "pending"
    assert len(revert["conflicts"]) == 1
    c = revert["conflicts"][0]
    assert (c["element_id"], c["expected_current"], c["actual_current"], c["revert_to"]) == (2, "60", "90", "45")


@pytest.mark.anyio
async def test_plan_revert_tool_metadata(env):
    _, approval, _ = env
    caps = {t.name: t for t in approval.get_capabilities()}
    # Like plan_actions, drafting is not itself gated; execution of the draft is.
    assert caps["plan_revert"].is_mutating is False
    assert "plan_revert" in caps and "get_proof_bundle" in caps
