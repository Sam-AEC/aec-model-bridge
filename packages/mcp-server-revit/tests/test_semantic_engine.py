import pytest
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.providers.identity_mapper import AECMapperProvider
from revit_mcp_server.providers.semantic_provider import SemanticProvider
from revit_mcp_server.providers.registry import ProviderRegistry
from revit_mcp_server.semantic import engine
from revit_mcp_server.semantic.models import Snapshot, ElementRecord

def test_snapshot_query_and_diff(tmp_path):
    # 1. Create a dummy base snapshot
    snap_base = engine.generate_mock_snapshot()
    
    door_uid = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"
    room_placed_uid = "c0326e0e-473d-4952-b8ec-f23696541f46-room-placed"
    room_unplaced_uid = "c0326e0e-473d-4952-b8ec-f23696541f45-room-unplaced"
    
    # 2. Query filtering tests
    # Match OST_Doors
    doors = engine.snapshot_query(snap_base, {"category": "OST_Doors"})
    assert len(doors) == 1
    assert doors[0].uid == door_uid
    
    # Match Room with Number 102
    rooms_102 = engine.snapshot_query(snap_base, {
        "category": "OST_Rooms",
        "parameter": {"name": "Number", "value": "102"}
    })
    assert len(rooms_102) == 1
    assert rooms_102[0].uid == room_placed_uid

    # Match Unplaced Rooms
    unplaced = engine.snapshot_query(snap_base, {
        "category": "OST_Rooms",
        "placed": False
    })
    assert len(unplaced) == 1
    assert unplaced[0].uid == room_unplaced_uid

    # 3. Create target modified snapshot
    snap_target = Snapshot(**snap_base.model_dump())
    
    # Modify parameter on door
    snap_target.elements[3].params["Mark"].v = "D-101-NEW"
    
    # Add a new element
    new_el = ElementRecord(
        uid="c0326e0e-473d-4952-b8ec-f23696541f47-wall-2",
        element_id=201,
        category="OST_Walls",
        cls="Wall",
        type_uid="wall-type-uid-0001",
        family="Basic Wall",
        type_name="Generic - 200mm",
        level_uid="c0326e0e-473d-4952-b8ec-f23696541f41-level-1",
        params={}
    )
    snap_target.elements.append(new_el)
    
    # Delete Room placed
    snap_target.elements = [el for el in snap_target.elements if el.uid != room_placed_uid]
    
    diff = engine.snapshot_diff(snap_base, snap_target)
    assert len(diff["added"]) == 1
    assert diff["added"][0].uid == "c0326e0e-473d-4952-b8ec-f23696541f47-wall-2"
    assert len(diff["deleted"]) == 1
    assert diff["deleted"][0] == room_placed_uid
    assert len(diff["modified"]) == 1
    assert diff["modified"][0].uid == door_uid

def test_three_way_conflict_detection():
    snap_base = engine.generate_mock_snapshot()
    door_uid = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"
    
    # Proposed Target: modify Door Mark parameter to "D-101-NEW"
    snap_target = Snapshot(**snap_base.model_dump())
    snap_target.elements[3].params["Mark"].v = "D-101-NEW"
    
    # Scenario A: No conflict (Live matches Base)
    snap_live_no_conflict = Snapshot(**snap_base.model_dump())
    recon_a = engine.reconcile_delta(snap_base, snap_target, snap_live_no_conflict)
    assert len(recon_a["conflicts"]) == 0
    assert len(recon_a["actions"]) == 1
    assert recon_a["actions"][0]["action"] == "modify"
    assert recon_a["actions"][0]["param_updates"] == {"Mark": "D-101-NEW"}
    
    # Scenario B: Conflict (Live was modified to "D-101-LIVE-CHANGED" since Base)
    snap_live_conflict = Snapshot(**snap_base.model_dump())
    snap_live_conflict.elements[3].params["Mark"].v = "D-101-LIVE-CHANGED"
    recon_b = engine.reconcile_delta(snap_base, snap_target, snap_live_conflict)
    assert len(recon_b["conflicts"]) == 1
    assert recon_b["conflicts"][0]["uid"] == door_uid
    assert "both in the target plan and in the live model" in recon_b["conflicts"][0]["reason"]

@pytest.mark.anyio
async def test_semantic_provider_and_mapper_registration(tmp_path):
    workspace = WorkspaceMonitor([tmp_path])
    registry = ProviderRegistry()
    
    door_uid = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"
    
    # Register mapper and semantic providers
    mapper = AECMapperProvider(workspace=workspace)
    registry.register(mapper)
    
    semantic = SemanticProvider(workspace=workspace, registry=registry)
    registry.register(semantic)
    
    # 1. Take snapshot
    res = await semantic.execute_tool("snapshot_take", {})
    assert res["status"] == "success"
    snapshot_id = res["snapshot_id"]
    assert snapshot_id
    
    # Verify snapshot file exists
    snapshot_file = tmp_path / "snapshots" / f"{snapshot_id}.json"
    assert snapshot_file.exists()
    
    # 2. Verify mappings registered dynamically in mapper
    trans_res = await mapper.execute_tool("aec_translate_id", {
        "source_id": door_uid,
        "source_format": "revit_unique_id",
        "target_format": "ifc_guid"
    })
    assert trans_res["translated_id"] is not None
    # door-uid-0001 is a GUID prefix-based UID, so it maps deterministically
    assert len(trans_res["translated_id"]) == 22  # IFC compressed GUID length
