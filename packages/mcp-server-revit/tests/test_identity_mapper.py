import pytest
from pathlib import Path
from revit_mcp_server.providers.identity_mapper import AECMapperProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor


@pytest.mark.anyio
async def test_deterministic_guid_translation(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = AECMapperProvider(workspace=workspace)

    # Revit UniqueId (with instance suffix) to IFC GlobalId
    revit_id = "2b6b2b73-09be-48dc-b6c8-52d3c368d0a8-0002ab1f"
    res1 = await provider.execute_tool("aec_translate_id", {
        "source_id": revit_id,
        "source_format": "revit_unique_id",
        "target_format": "ifc_guid"
    })
    assert res1["translated_id"] == "0hQojp2Rv8tBR8KjF3QD2e"
    assert res1["source"] == "deterministic_guid_compression"

    # IFC GlobalId to Revit GUID
    ifc_id = "0hQojp2Rv8tBR8KjF3QD2e"
    res2 = await provider.execute_tool("aec_translate_id", {
        "source_id": ifc_id,
        "source_format": "ifc_guid",
        "target_format": "revit_unique_id"
    })
    assert res2["translated_id"] == "2b6b2b73-09be-48dc-b6c8-52d3c368d0a8"
    assert res2["source"] == "deterministic_ifc_expansion"


@pytest.mark.anyio
async def test_custom_registered_mapping(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = AECMapperProvider(workspace=workspace)

    # Register custom mappings
    reg = await provider.execute_tool("aec_register_mapping", {
        "mappings": [
            {
                "revit_unique_id": "my-revit-element-id-123-abc",
                "rhino_uuid": "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"
            }
        ]
    })
    assert reg["status"] == "success"
    assert reg["count_registered"] == 1

    # Translate using registered mappings
    res = await provider.execute_tool("aec_translate_id", {
        "source_id": "my-revit-element-id-123-abc",
        "source_format": "revit_unique_id",
        "target_format": "rhino_uuid"
    })
    assert res["translated_id"] == "f81d4fae-7dec-11d0-a765-00a0c91e6bf6"
    assert res["source"] == "custom_registry"


@pytest.mark.anyio
async def test_workspace_path_mapping(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = AECMapperProvider(workspace=workspace)

    test_file = tmp_path / "subdir" / "project.rvt"
    test_file.parent.mkdir(exist_ok=True)
    test_file.touch()

    # Relative format
    rel_res = await provider.execute_tool("aec_map_workspace_path", {
        "path": str(test_file),
        "target_format": "relative"
    })
    assert rel_res["mapped_path"] == "subdir/project.rvt"

    # Windows Absolute format
    win_res = await provider.execute_tool("aec_map_workspace_path", {
        "path": str(test_file),
        "target_format": "absolute_windows"
    })
    assert "\\" in win_res["mapped_path"]

    # POSIX Absolute format
    posix_res = await provider.execute_tool("aec_map_workspace_path", {
        "path": str(test_file),
        "target_format": "absolute_posix"
    })
    assert "/" in posix_res["mapped_path"]
    assert ":" not in posix_res["mapped_path"]


@pytest.mark.anyio
async def test_path_mapping_traversal_protection(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    provider = AECMapperProvider(workspace=workspace)

    outside_file = tmp_path.parent / "unauthorized.txt"
    
    with pytest.raises(Exception) as exc:
        await provider.execute_tool("aec_map_workspace_path", {
            "path": str(outside_file),
            "target_format": "relative"
        })
    assert "outside the allowed workspace" in str(exc.value).lower()
