"""Proof bundles and revert plans for approved parameter fixes."""
from __future__ import annotations

import json

import pytest

from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_approval_provider import FakeParamStore
from helpers import panel_decide, human_approve
from revit_mcp_server.security.approval import local_user


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
    await panel_decide(approval, "approve_plan", pid)
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
    assert proof["approved_by"] == local_user()  # recorded by the code path, not the caller
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
async def test_proof_records_the_approving_account_not_a_caller_name(env):
    tmp_path, approval, _ = env
    plan = await approval.execute_tool("plan_actions", {"actions": _acts(1)})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    await approval.execute_tool("execute_plan", {"plan_id": plan["plan_id"]})
    proof = _proof_file(tmp_path, plan["plan_id"])
    # The approver is the OS account of the approving process, never a caller-supplied name.
    assert proof["approved_by"] == local_user()
    assert "not an authenticated identity" in proof["approver_note"]
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
    human_approve(approval.gate, pid, approver="someone")
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
    assert not revert["review"]["conflicts"]
    # Not executed: model still holds the fixed values, and execution is gated.
    assert store.values[1]["FireRating"] == "60"
    with pytest.raises(ValueError, match="not 'approved'"):
        await approval.execute_tool("execute_plan", {"plan_id": revert["plan_id"]})
    # After approval + execution the originals are restored and the revert has its own proof.
    await panel_decide(approval, "approve_plan", revert["plan_id"])
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
    assert "conflicts" not in revert  # conflicts live in the hashed review block
    conflicts = revert["review"]["conflicts"]
    assert len(conflicts) == 1
    c = conflicts[0]
    assert (c["element_id"], c["parameter"], c["expected_current"], c["actual_current"], c["revert_to"]) == (
        2, "FireRating", "'60'", "'90'", "'45'")


@pytest.mark.anyio
async def test_plan_revert_tool_metadata(env):
    _, approval, _ = env
    caps = {t.name: t for t in approval.get_capabilities()}
    # Like plan_actions, drafting is not itself gated; execution of the draft is.
    assert caps["plan_revert"].is_mutating is False
    assert "plan_revert" in caps and "get_proof_bundle" in caps


class TypedStore(FakeParamStore):
    """Like the live add-in: values are read back as text, with the Revit storage type."""

    def __init__(self, values, types):
        super().__init__(values)
        self.types = types

    async def execute_tool(self, name, arguments):
        res = await super().execute_tool(name, arguments)
        if name == "revit_get_parameter_value":
            v = res["value"]
            res = {"value": None if v is None else str(v),
                   "storage_type": self.types.get(arguments.get("parameter_name"))}
        return res


def _typed_env(tmp_path, values, types):
    registry = ProviderRegistry()
    approval = ApprovalProvider(WorkspaceMonitor([tmp_path]), registry, approval_mode="required")
    registry.register(approval)
    store = TypedStore(values, types)
    registry.register(store)
    return approval, store


def _set(eid, pname, value):
    return {"tool": "revit_set_parameter_value",
            "arguments": {"element_id": eid, "parameter_name": pname, "value": value}}


@pytest.mark.anyio
async def test_revert_numeric_string_vs_number_is_not_a_conflict(tmp_path):
    approval, store = _typed_env(tmp_path, {1: {"Rating": 30}}, {"Rating": "Integer"})
    pid, _ = await _run(approval, [_set(1, "Rating", 60)])
    assert store.values[1]["Rating"] == 60  # live read returns "60", the proof holds 60
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid})
    assert not revert["review"]["conflicts"]


@pytest.mark.anyio
async def test_revert_numeric_real_conflict_still_refused(tmp_path):
    approval, store = _typed_env(tmp_path, {1: {"Rating": 30}}, {"Rating": "Integer"})
    pid, _ = await _run(approval, [_set(1, "Rating", 60)])
    store.values[1]["Rating"] = 61
    with pytest.raises(ValueError, match="changed since"):
        await approval.execute_tool("plan_revert", {"plan_id": pid})
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid, "allow_conflicts": True})
    assert revert["review"]["conflicts"][0]["actual_current"] == "'61'"


@pytest.mark.anyio
async def test_revert_drafts_typed_values(tmp_path):
    approval, _ = _typed_env(
        tmp_path,
        {1: {"Rating": 30, "Width": 0.5, "Mark": "A-1", "Fixed": 1, "Host": 12},
         },
        {"Rating": "Integer", "Width": "Double", "Mark": "String", "Fixed": "Integer", "Host": "ElementId"},
    )
    pid, _ = await _run(approval, [_set(1, "Rating", 60), _set(1, "Width", 1.25), _set(1, "Mark", "B-2"),
                                   _set(1, "Fixed", 0), _set(1, "Host", 99)])
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid})
    got = {a["arguments"]["parameter_name"]: a["arguments"]["value"] for a in revert["actions"]}
    assert got == {"Rating": 30, "Width": 0.5, "Mark": "A-1", "Fixed": 1, "Host": 12}
    assert type(got["Rating"]) is int and type(got["Width"]) is float and type(got["Mark"]) is str
    assert type(got["Fixed"]) is int and type(got["Host"]) is int
    assert not revert["review"]["assumptions"]
    assert _proof_file(tmp_path, pid)["elements"][0]["before_storage_type"] == "Integer"


@pytest.mark.anyio
async def test_revert_string_that_looks_numeric_stays_string(tmp_path):
    approval, _ = _typed_env(tmp_path, {1: {"Mark": "007"}}, {"Mark": "String"})
    pid, _ = await _run(approval, [_set(1, "Mark", "008")])
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid})
    assert revert["actions"][0]["arguments"]["value"] == "007"


@pytest.mark.anyio
async def test_revert_unknown_storage_type_coerces_conservatively_with_note(tmp_path):
    # No storage_type reported (older reader / older plan): numeric new value -> number, noted.
    approval, _ = _typed_env(tmp_path, {1: {"Rating": 30, "Mark": "12"}}, {})
    pid, _ = await _run(approval, [_set(1, "Rating", 60), _set(1, "Mark", "13")])
    revert = await approval.execute_tool("plan_revert", {"plan_id": pid})
    got = {a["arguments"]["parameter_name"]: a["arguments"]["value"] for a in revert["actions"]}
    assert got["Rating"] == 30 and type(got["Rating"]) is int
    assert got["Mark"] == "12"  # new value was text, so stays text
    notes = revert["review"]["assumptions"]
    assert len(notes) == 2 and all("storage type not recorded" in n for n in notes)
