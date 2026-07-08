import pytest
from revit_mcp_server.security.approval import ApprovalGate
from revit_mcp_server.errors import BridgeError


@pytest.mark.anyio
async def test_approval_gate_lifecycle(tmp_path):
    # 1. Setup ApprovalGate in required mode
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")

    # 2. Assert mutating tool without plan is rejected
    with pytest.raises(BridgeError) as exc_info:
        gate.check_tool_execution("revit_create_wall", {})
    assert "requires a valid 'plan_id' parameter" in str(exc_info.value)

    # 3. Create plan
    actions = [
        {
            "tool": "revit_set_parameter_value",
            "arguments": {
                "element_id": 123,
                "parameter_name": "FireRating",
                "value": "60"
            }
        }
    ]
    before_states = [{ "123": { "FireRating": "30" } }]
    plan = gate.create_plan(actions, before_states)
    plan_id = plan["plan_id"]
    assert plan["state"] == "pending"
    assert len(plan["actions"]) == 1

    # 4. Assert execution is blocked when plan is pending
    with pytest.raises(BridgeError) as exc_info:
        gate.check_tool_execution("revit_set_parameter_value", { "plan_id": plan_id })
    assert "is in state 'pending', not 'approved'" in str(exc_info.value)

    # 5. Approve plan
    gate.update_plan_state(plan_id, "approved")

    # 6. Assert check passes when plan is approved
    gate.check_tool_execution("revit_set_parameter_value", { "plan_id": plan_id })

    # 7. Execute rollback
    # Mock execution function — must be async: production passes an async
    # `execute_helper` (see providers/approval_provider.py), and rollback_plan
    # awaits it. A sync mock here would mask the exact bug this test guards
    # against (a bare, un-awaited call to an async execute_fn is a silent no-op).
    executed_calls = []
    async def mock_execute(tool_name, arguments):
        executed_calls.append((tool_name, arguments))
        return { "status": "success" }

    # Transition state to executed first
    gate.update_plan_state(plan_id, "executed")

    # Execute rollback
    await gate.rollback_plan(plan_id, mock_execute)

    # Verify rollback inverse call
    assert len(executed_calls) == 1
    assert executed_calls[0][0] == "revit_set_parameter_value"
    assert executed_calls[0][1]["value"] == "30"
    assert executed_calls[0][1]["element_id"] == 123

    # Verify state transitioned to rolled_back
    updated_plan = gate.load_plan(plan_id)
    assert updated_plan["state"] == "rolled_back"


@pytest.mark.anyio
async def test_rollback_generalizes_to_a_batch_of_actions(tmp_path):
    """A plan with N revit_set_parameter_value actions (one per element) rolls
    every one of them back — no per-tool special-casing needed for batches,
    since a "batch" is just multiple actions of an already-supported tool."""
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")

    actions = [
        {"tool": "revit_set_parameter_value", "arguments": {"element_id": 1, "parameter_name": "FireRating", "value": "60"}},
        {"tool": "revit_set_parameter_value", "arguments": {"element_id": 2, "parameter_name": "FireRating", "value": "60"}},
        {"tool": "revit_set_parameter_value", "arguments": {"element_id": 3, "parameter_name": "FireRating", "value": "60"}},
    ]
    before_states = [
        {"1": {"FireRating": "30"}},
        {"2": {"FireRating": "45"}},
        {"3": {"FireRating": None}},
    ]
    plan = gate.create_plan(actions, before_states)
    plan_id = plan["plan_id"]
    gate.update_plan_state(plan_id, "approved")
    gate.update_plan_state(plan_id, "executed")

    calls = []
    async def mock_execute(tool_name, arguments):
        calls.append(arguments)
        return {"status": "success"}

    await gate.rollback_plan(plan_id, mock_execute)

    # Element 3's before-value was None (never had the param set) — skipped, not errored.
    assert len(calls) == 2
    assert {c["element_id"] for c in calls} == {1, 2}
    assert next(c["value"] for c in calls if c["element_id"] == 1) == "30"
    assert next(c["value"] for c in calls if c["element_id"] == 2) == "45"
    assert gate.load_plan(plan_id)["state"] == "rolled_back"
