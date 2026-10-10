"""Tools that used to bypass the approval gate must now be flagged is_mutating and
rejected without a plan_id when approval is required.

UNVERIFIED against live Revit / Rhino / Navisworks: this only checks hub metadata."""
from __future__ import annotations

import pytest
from mcp.types import ToolAnnotations

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.proxy import McpProxyProvider, is_proxied_tool_read_only
from revit_mcp_server.registry_factory import build_registry
from revit_mcp_server.security.approval import ApprovalGate
from revit_mcp_server.security.workspace import WorkspaceMonitor

NOW_GATED = [
    "rhino_generate_diagrid_tower",
    "navisworks_append_file",
    "navisworks_refresh",
    "navisworks_activate_viewpoint",
    "revit_render_3d",
    "revit_reflect_get",
    "rhino_reflect_get",
    "navisworks_reflect_get",
    "navisworks_create_viewpoint",
    "navisworks_run_clash_test",
    "navisworks_invoke_method",
    "navisworks_reflect_set",
]

# Fail closed: these are the ONLY Navisworks tools allowed to skip the gate.
NAVISWORKS_READ_ONLY = {
    "navisworks_health", "navisworks_get_document_info", "navisworks_get_model_tree",
    "navisworks_get_selection", "navisworks_list_viewpoints",
    "navisworks_list_clash_tests", "navisworks_get_clash_results",
}


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


def test_navisworks_tools_fail_closed(registry):
    names = {t.name for t in registry.get_all_tools() if t.name.startswith("navisworks_")}
    assert NAVISWORKS_READ_ONLY <= names
    ungated = {n for n in names if not registry.lookup_tool(n).is_mutating}
    assert ungated == NAVISWORKS_READ_ONLY


@pytest.mark.parametrize(
    "name,ann,expected",
    [
        ("create_wall", None, False),
        ("get_thing", None, True),  # no annotations: name verbs only
        ("get_thing", ToolAnnotations(readOnlyHint=True), True),
        ("get_thing", ToolAnnotations(readOnlyHint=False), False),
        ("get_thing", ToolAnnotations(readOnlyHint=True, destructiveHint=True), False),
        ("delete_thing", ToolAnnotations(readOnlyHint=True), False),
        ("search_x", ToolAnnotations(), True),
        ("getaway", None, False),
        ("run_get_", None, False),
    ],
)
def test_proxy_read_only_rule(name, ann, expected):
    assert is_proxied_tool_read_only(name, ann) is expected


def test_proxy_discovered_tools_are_gated_by_default():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock, patch

    def tool(name, ann=None):
        return SimpleNamespace(name=name, description="", inputSchema={"type": "object"}, annotations=ann)

    session = MagicMock()
    session.initialize = AsyncMock()
    session.list_tools = AsyncMock(return_value=SimpleNamespace(tools=[
        tool("create_thing"),
        tool("get_thing"),
        tool("get_thing_ro", ToolAnnotations(readOnlyHint=True)),
        tool("get_thing_rw", ToolAnnotations(readOnlyHint=False)),
        tool("update_thing", ToolAnnotations(readOnlyHint=True)),
    ]))

    class Ctx:
        def __init__(self, v):
            self.v = v

        async def __aenter__(self):
            return self.v

        async def __aexit__(self, *a):
            return False

    prov = McpProxyProvider("http://x/sse", identity="up")
    with patch("revit_mcp_server.providers.proxy.sse_client", return_value=Ctx((1, 2))), patch(
        "revit_mcp_server.providers.proxy.ClientSession", return_value=Ctx(session)
    ):
        asyncio.run(prov._connect_once())
    got = {t.name: t.is_mutating for t in prov.get_capabilities()}
    assert got == {
        "up_create_thing": True,
        "up_get_thing": False,
        "up_get_thing_ro": False,
        "up_get_thing_rw": True,
        "up_update_thing": True,
    }
