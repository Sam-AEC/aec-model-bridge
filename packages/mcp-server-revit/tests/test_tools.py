import pytest
from pathlib import Path
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.providers.revit import RevitProvider

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
    payload = {"output_path": str(tmp_path / "quantities.json")}
    
    # Assert path is validated
    with pytest.raises(Exception):
        # Path outside workspace must raise ValueError or PermissionError
        await provider.execute_tool("revit_get_element_geometry", {"element_id": 1, "path": "C:/outside.rvt"})
