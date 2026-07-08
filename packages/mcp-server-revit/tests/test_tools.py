import pytest
from revit_mcp_server.config import BridgeMode
from revit_mcp_server.errors import WorkspaceViolation
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.providers.revit import RevitProvider


class FakeBridge:
    """Stands in for the 'live' Revit bridge — records whether a call ever
    reached it, so tests can prove an unsafe request never got that far."""

    def __init__(self, base_url: str, token: str | None = None):
        self.calls = []

    def send_tool(self, tool_name, payload):
        self.calls.append((tool_name, payload))
        return {"ok": True}


def test_all_handlers_registered(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RevitProvider(workspace=workspace)
    tools = [t.name for t in provider.get_capabilities()]
    assert "revit_health" in tools
    assert "revit_create_wall" in tools
    assert len(tools) >= 25

@pytest.mark.anyio
async def test_export_quantities_uses_workspace(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = RevitProvider(workspace=workspace)

    # Assert path is validated
    with pytest.raises(Exception):
        # Path outside workspace must raise ValueError or PermissionError
        await provider.execute_tool("revit_get_element_geometry", {"element_id": 1, "path": "C:/outside.rvt"})


@pytest.mark.anyio
async def test_bridge_mode_never_forwards_an_out_of_workspace_path(tmp_path):
    """An out-of-workspace path must be rejected before reaching the live bridge,
    not just in mock mode. This exercises RevitProvider in BridgeMode.bridge with
    an injected fake bridge standing in for the real C# add-in — if the sandbox
    check were ever silently downgraded to a warning (as the legacy-handler path
    in execute_tool used to do for WorkspaceViolation specifically), the fake
    bridge would see the call anyway."""
    workspace = WorkspaceMonitor([tmp_path])
    fake_bridge = FakeBridge("http://127.0.0.1:3000")
    provider = RevitProvider(
        workspace=workspace,
        mode=BridgeMode.bridge,
        bridge_factory=lambda u, t=None: fake_bridge,
    )

    with pytest.raises(WorkspaceViolation):
        await provider.execute_tool(
            "revit_batch_create_sheets_from_csv",
            {"csv_path": "C:/outside/sheets.csv", "titleblock_name": "A1"},
        )

    assert fake_bridge.calls == []
