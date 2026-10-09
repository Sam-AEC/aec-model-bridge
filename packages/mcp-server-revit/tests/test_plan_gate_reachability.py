"""Regression: draft-only plan tools must be reachable under approval_mode="required".

`parameter_manager_plan_set_params` and `parameter_manager_import_params_csv` only
DRAFT an ActionPlan (no model write), so they must not be flagged `is_mutating`,
otherwise the gate demands a `plan_id` before a plan can ever be drafted. Tools that
really write must stay gated.
"""
from __future__ import annotations

import pytest

from revit_mcp_server.config import BridgeMode, Config, config
from revit_mcp_server.errors import BridgeError
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.approval_provider import ApprovalProvider
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.security.workspace import WorkspaceMonitor

from test_approval_provider import FakeParamStore

DRAFT_ONLY = ("parameter_manager_plan_set_params", "parameter_manager_import_params_csv")


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "mode", BridgeMode.mock)
    registry = ProviderRegistry()
    workspace = WorkspaceMonitor([tmp_path])
    approval = ApprovalProvider(workspace=workspace, registry=registry, approval_mode="required")
    registry.register(approval)
    store = FakeParamStore({1: {"Mark": "D-101"}})
    registry.register(store)
    cfg = Config(workspace_dir=tmp_path, allowed_directories=[tmp_path],
                 audit_log=tmp_path / "audit.log", enable_user_modules=False)
    modules = ModuleRegistry(config_obj=cfg)
    modules.discover_and_load()
    mp = ModuleProvider(module_registry=modules, workspace=workspace, tool_registry=registry)
    registry.register(mp)
    return registry, approval, store, mp


def _gate_applies(registry, name, arguments, gate):
    """Mirror of the call_tool / panel / agent gate step."""
    tool_def = registry.lookup_tool(name)
    if tool_def and tool_def.is_mutating:
        gate.check_tool_execution(name, arguments)


@pytest.mark.parametrize("name", DRAFT_ONLY)
def test_draft_only_tools_pass_gate_without_plan_id(stack, name):
    registry, approval, *_ = stack
    assert registry.lookup_tool(name).is_mutating is False
    _gate_applies(registry, name, {}, approval.gate)  # must not raise


@pytest.mark.parametrize("name", [
    "revit_set_parameter_value",
    "selection_tools_set_selection",
    "selection_tools_group_rename",
    "selection_tools_group_ungroup",
    "selection_tools_group_convert_to_detail",
])
def test_writing_tools_stay_mutating_and_blocked(stack, name):
    registry, approval, *_ = stack
    assert registry.lookup_tool(name).is_mutating is True
    with pytest.raises(BridgeError, match="requires a valid 'plan_id'"):
        _gate_applies(registry, name, {}, approval.gate)


@pytest.mark.anyio
async def test_draft_approve_execute_end_to_end(stack):
    registry, approval, store, mp = stack
    gate = approval.gate

    # 1. Draft: passes the gate with no plan_id.
    _gate_applies(registry, "parameter_manager_plan_set_params", {}, gate)
    draft = await mp.execute_tool("parameter_manager_plan_set_params", {
        "element_filter": {"category": "OST_Doors"},
        "param_updates": {"Mark": "D-201"},
    })
    assert draft["plan_type"] == "action_plan_draft"
    assert draft["actions"]
    action = draft["actions"][0]
    action["arguments"]["element_id"] = 1  # map onto the fake store

    # 2. Review: register the draft as a pending plan.
    plan = await approval.execute_tool("plan_actions", {"actions": [action]})
    plan_id = plan["plan_id"]
    assert plan["state"] == "pending"

    # The writing tool is blocked until approved.
    with pytest.raises(BridgeError, match="not 'approved'"):
        _gate_applies(registry, "revit_set_parameter_value", {"plan_id": plan_id}, gate)
    assert store.values[1]["Mark"] == "D-101"

    # 3. Approve, then execute.
    await approval.execute_tool("approve_plan", {"plan_id": plan_id})
    _gate_applies(registry, "revit_set_parameter_value", {"plan_id": plan_id}, gate)
    result = await approval.execute_tool("execute_plan", {"plan_id": plan_id})
    assert result["state"] == "executed"
    assert store.values[1]["Mark"] == "D-201"
