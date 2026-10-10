"""Tools that used to bypass the approval gate must now be flagged is_mutating and
rejected without a plan_id when approval is required.

UNVERIFIED against live Revit / Rhino / Navisworks: this only checks hub metadata."""
from __future__ import annotations

import pytest
from mcp.types import ToolAnnotations

from revit_mcp_server.errors import BridgeError
from revit_mcp_server.providers.base import ProviderTool
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


# --- approved proxied calls must not leak bridge-only control fields upstream ---
class _StrictSession:
    """Fake upstream session that, like a strict JSON schema, rejects undeclared properties."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments):
        from types import SimpleNamespace

        extra = set(arguments) - {"path", "value"}
        if extra:
            raise ValueError(f"unexpected properties: {sorted(extra)}")
        self.calls.append((name, dict(arguments)))
        return SimpleNamespace(content=[SimpleNamespace(text="ok")], isError=False)


def _strict_proxy():
    prov = McpProxyProvider("http://x/sse", identity="up")
    prov._session = _StrictSession()
    prov._connected = True
    prov._tools = [
        ProviderTool(name="up_write_thing", description="", inputSchema={"type": "object"}, is_mutating=True)
    ]
    return prov


@pytest.mark.anyio
async def test_proxy_strips_control_fields_without_mutating_input():
    prov = _strict_proxy()
    args = {"path": "a", "value": 1, "plan_id": "plan_0123456789ab", "run_async": True, "idempotency_key": "k"}
    original = dict(args)
    res = await prov.execute_tool("up_write_thing", args)
    assert res["result"] == "ok"
    assert prov._session.calls == [("write_thing", {"path": "a", "value": 1})]
    assert args == original


@pytest.mark.anyio
async def test_approved_direct_call_and_execute_plan_reach_strict_upstream(tmp_path):
    from revit_mcp_server.providers.approval_provider import ApprovalProvider
    from revit_mcp_server.providers.registry import ProviderRegistry
    from revit_mcp_server.security.dispatch import gate_before, gate_after
    from helpers import panel_decide

    registry = ProviderRegistry()
    approval = ApprovalProvider(
        workspace=WorkspaceMonitor([tmp_path]), registry=registry, approval_mode="required"
    )
    registry.register(approval)
    prov = _strict_proxy()
    registry.register(prov)
    act = {"tool": "up_write_thing", "arguments": {"path": "a", "value": 1}}

    # direct call path: gate sees the original arguments incl. plan_id, upstream does not
    plan = await approval.execute_tool("plan_actions", {"actions": [act]})
    await panel_decide(approval, "approve_plan", plan["plan_id"])
    args = {"path": "a", "value": 1, "plan_id": plan["plan_id"]}
    claim = gate_before(registry, approval.gate, "up_write_thing", args)
    res = await registry.lookup_tool_provider("up_write_thing").execute_tool("up_write_thing", args)
    gate_after(approval.gate, claim, ok=True)
    assert res["result"] == "ok" and args["plan_id"] == plan["plan_id"]

    # execute_plan path
    plan2 = await approval.execute_tool("plan_actions", {"actions": [act]})
    await panel_decide(approval, "approve_plan", plan2["plan_id"])
    out = await approval.execute_tool("execute_plan", {"plan_id": plan2["plan_id"]})
    assert out["state"] == "executed", out
    assert len(prov._session.calls) == 2
    assert all(c == ("write_thing", {"path": "a", "value": 1}) for c in prov._session.calls)
