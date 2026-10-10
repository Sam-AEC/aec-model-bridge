"""Tools that used to bypass the approval gate must now be flagged is_mutating and
rejected without a plan_id when approval is required.

UNVERIFIED against live Revit / Rhino / Navisworks: this only checks hub metadata."""
from __future__ import annotations

import pytest

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import ApprovalGate
from revit_mcp_server.security.workspace import WorkspaceMonitor

NOW_GATED = [
    "rhino_generate_diagrid_tower",
    "navisworks_append_file",
    "navisworks_refresh",
    "navisworks_activate_viewpoint",
    "revit_render_3d",
]


@pytest.fixture(scope="module")
def registry(tmp_path_factory):
    reg, *_ = build_registry(WorkspaceMonitor([tmp_path_factory.mktemp("gate-ws")]))
    return reg


@pytest.mark.parametrize("tool", NOW_GATED)
def test_tool_is_flagged_mutating_in_registry(registry, tool):
    tool_def = registry.lookup_tool(tool)
    assert tool_def is not None, tool
    assert tool_def.is_mutating, f"{tool} bypasses the approval gate"


@pytest.mark.parametrize("tool", NOW_GATED)
def test_gate_blocks_tool_without_plan(registry, tool, tmp_path):
    # The gate is only consulted for tools the registry flags as mutating.
    assert registry.lookup_tool(tool).is_mutating
    gate = ApprovalGate(workspace_dir=tmp_path, approval_mode="required")
    with pytest.raises(BridgeError, match="plan_id"):
        gate.check_tool_execution(tool, {})
