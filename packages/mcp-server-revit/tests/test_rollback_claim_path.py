"""Issue #144: rollback_plan uses the same claim, lock and verify path as execute_plan.

- the plan is never written as 'approved' mid-rollback (a crash leaves it 'executed');
- each inverse action gets its own claim marker before its write runs;
- only an executed, unchanged plan can be rolled back.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from helpers import human_approve
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.security.approval import ApprovalGate


class SimulatedCrash(BaseException):
    """Stands in for a killed process: not an Exception, so no handler may swallow it."""


def _executed_plan(tmp_path, n=2):
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")
    actions = [{"tool": "revit_set_parameter_value",
                "arguments": {"element_id": i, "parameter_name": "FireRating", "value": "60"}}
               for i in range(1, n + 1)]
    plan = gate.create_plan(actions, [{str(i): {"FireRating": f"old{i}"}} for i in range(1, n + 1)])
    plan_id = plan["plan_id"]
    human_approve(gate, plan_id)
    gate.update_plan_state(plan_id, "executed")
    return gate, plan_id


def _markers(tmp_path, plan_id):
    return sorted(p.name for p in (tmp_path / "plans" / ".rollback_claims").glob(f"{plan_id}.*")) \
        if (tmp_path / "plans" / ".rollback_claims").exists() else []


def _disk_state(gate, plan_id):
    return json.loads(gate._get_plan_path(plan_id).read_text(encoding="utf-8"))["state"]


@pytest.mark.anyio
async def test_crash_mid_rollback_leaves_plan_executed_never_approved(tmp_path):
    gate, plan_id = _executed_plan(tmp_path)
    seen = []

    async def crashing(tool, args):
        seen.append(_disk_state(gate, plan_id))
        raise SimulatedCrash()

    with pytest.raises(SimulatedCrash):
        await gate.rollback_plan(plan_id, crashing)

    assert seen == ["executed"]  # never 'approved' while the inverse write ran
    assert _disk_state(gate, plan_id) == "executed"


@pytest.mark.anyio
async def test_state_is_executed_on_disk_during_every_inverse_write(tmp_path):
    gate, plan_id = _executed_plan(tmp_path, n=3)
    seen = []

    async def ok(tool, args):
        seen.append(_disk_state(gate, plan_id))
        return {"status": "success"}

    plan = await gate.rollback_plan(plan_id, ok)
    assert seen == ["executed"] * 3
    assert plan["state"] == "rolled_back"
    assert "approved" not in seen


@pytest.mark.anyio
async def test_rollback_hash_check_is_independent_of_execution_approval_expiry(tmp_path):
    gate, plan_id = _executed_plan(tmp_path, n=1)
    plan = gate.load_plan(plan_id)
    plan["approved_at"] = (datetime.now(timezone.utc) - timedelta(seconds=gate.approval_ttl + 1)).isoformat()
    gate.save_plan(plan)
    calls = []

    async def ok(tool, args):
        calls.append(args["element_id"])
        return {"status": "success"}

    result = await gate.rollback_plan(plan_id, ok)
    assert calls == [1]
    assert result["state"] == "rolled_back"


@pytest.mark.anyio
async def test_a_claim_marker_is_written_per_inverse_action_before_the_write(tmp_path):
    gate, plan_id = _executed_plan(tmp_path, n=2)
    action_ids = [a["action_id"] for a in gate.load_plan(plan_id)["actions"]]
    at_write = []

    async def ok(tool, args):
        at_write.append(len(_markers(tmp_path, plan_id)))
        return {"status": "success"}

    await gate.rollback_plan(plan_id, ok)

    assert at_write == [1, 2]  # the marker exists before the write runs
    assert _markers(tmp_path, plan_id) == sorted(f"{plan_id}.{a}" for a in action_ids)


@pytest.mark.anyio
async def test_an_action_already_claimed_by_an_earlier_rollback_is_not_written_again(tmp_path):
    gate, plan_id = _executed_plan(tmp_path, n=2)

    async def crash_on_second(tool, args):
        if args["element_id"] == 1:  # rollback runs in reverse: element 2 first, then 1
            raise SimulatedCrash()
        return {"status": "success"}

    with pytest.raises(SimulatedCrash):
        await gate.rollback_plan(plan_id, crash_on_second)
    assert _disk_state(gate, plan_id) == "executed"

    calls = []

    async def ok(tool, args):
        calls.append(args["element_id"])
        return {"status": "success"}

    with pytest.raises(BridgeError, match="already claimed"):
        await gate.rollback_plan(plan_id, ok)
    assert calls == []  # both were claimed before: never replayed blindly
    assert _disk_state(gate, plan_id) == "partial_rollback"


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["pending", "approved", "rejected", "partial", "rolled_back", "partial_rollback"])
async def test_rollback_of_a_non_executed_plan_is_refused_and_writes_nothing(tmp_path, state):
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")
    plan = gate.create_plan(
        [{"tool": "revit_set_parameter_value",
          "arguments": {"element_id": 1, "parameter_name": "P", "value": "x"}}],
        [{"1": {"P": "old"}}])
    plan_id = plan["plan_id"]
    if state != "pending":
        human_approve(gate, plan_id)
        stored = gate.load_plan(plan_id)
        stored["state"] = state
        gate.save_plan(stored)
    calls = []

    async def ok(tool, args):
        calls.append(args)
        return {}

    with pytest.raises(ValueError, match="cannot rollback"):
        await gate.rollback_plan(plan_id, ok)
    assert calls == []
    assert _markers(tmp_path, plan_id) == []
    assert _disk_state(gate, plan_id) == state


@pytest.mark.anyio
async def test_rollback_of_a_plan_edited_after_approval_is_refused(tmp_path):
    gate, plan_id = _executed_plan(tmp_path, n=1)
    stored = gate.load_plan(plan_id)
    stored["actions"][0]["diff"]["before"]["1"]["FireRating"] = "tampered"
    gate.save_plan(stored)
    calls = []

    async def ok(tool, args):
        calls.append(args)
        return {}

    with pytest.raises(BridgeError, match="changed after it was approved"):
        await gate.rollback_plan(plan_id, ok)
    assert calls == []
    assert _markers(tmp_path, plan_id) == []
    assert _disk_state(gate, plan_id) == "executed"


@pytest.mark.anyio
async def test_a_failed_inverse_write_still_ends_partial_rollback_without_approved(tmp_path):
    gate, plan_id = _executed_plan(tmp_path, n=2)
    seen = []

    async def failing(tool, args):
        seen.append(_disk_state(gate, plan_id))
        raise RuntimeError("revit said no")

    with pytest.raises(BridgeError, match="Rollback encountered errors"):
        await gate.rollback_plan(plan_id, failing)
    assert set(seen) == {"executed"}
    assert _disk_state(gate, plan_id) == "partial_rollback"
