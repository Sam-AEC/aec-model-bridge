"""Tests for Phase 7 — Model Inspector module (W1–W3)."""
import importlib.util
import pytest
from pathlib import Path
from revit_mcp_server.semantic.engine import generate_mock_snapshot

# Load the module file directly so we bypass the sys.modules conflict
# caused by the module_registry registering the same name as a flat module.
_MODULE_PY = (
    Path(__file__).parent.parent
    / "src/revit_mcp_server/modules/model_inspector/module.py"
)
_spec = importlib.util.spec_from_file_location("_model_inspector_impl", _MODULE_PY)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ModelInspectorModule = _mod.ModelInspectorModule


class MockWorkspace:
    """Minimal workspace stub pointing to tmp_path."""
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def module():
    return ModelInspectorModule()


@pytest.fixture
def snap_and_workspace(tmp_path):
    ws = MockWorkspace(tmp_path)
    snap = generate_mock_snapshot()
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{snap.snapshot_id}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        f.write(snap.model_dump_json(by_alias=True, indent=2))
    return snap, ws


def test_summarize_model_no_snapshot(module, workspace):
    """summarize_model without snapshot_id generates mock."""
    result = module.summarize_model(workspace=workspace)
    assert result["elements_total"] == 6
    assert "OST_Doors" in result["by_category"]
    assert result["rooms"]["total"] == 2
    assert result["rooms"]["placed"] == 1
    assert result["rooms"]["unplaced"] == 1


def test_summarize_model_with_snapshot(module, snap_and_workspace):
    snap, ws = snap_and_workspace
    result = module.summarize_model(snapshot_id=snap.snapshot_id, workspace=ws)
    assert result["elements_total"] == 6
    assert result["rooms"]["total"] == 2


def test_ask_filter_by_category(module, workspace):
    result = module.ask(filter={"category": "OST_Walls"}, workspace=workspace)
    assert result["matches_count"] == 1
    assert result["elements"][0]["category"] == "OST_Walls"


def test_ask_filter_by_parameter_value(module, workspace):
    result = module.ask(filter={"category": "OST_Rooms", "parameter": {"name": "Number", "value": "102"}}, workspace=workspace)
    assert result["matches_count"] == 1
    assert "placed" in result["elements"][0]["uid"] or result["elements"][0]["category"] == "OST_Rooms"


def test_ask_filter_unplaced_rooms(module, workspace):
    result = module.ask(filter={"category": "OST_Rooms", "placed": False}, workspace=workspace)
    assert result["matches_count"] == 1
    assert "unplaced" in result["elements"][0]["uid"]


def test_list_groups_no_groups(module, workspace):
    """Mock snapshot has no groups, result should be empty."""
    result = module.list_groups(workspace=workspace)
    assert result["groups_count"] == 0


def test_inspect_selection_with_door(module, workspace):
    door_uid = "c0326e0e-473d-4952-b8ec-f23696541f44-door-1"
    result = module.inspect_selection(element_uids=[door_uid], workspace=workspace)
    assert result["inspected_count"] == 1
    card = result["elements"][0]
    assert card["uid"] == door_uid
    assert card["category"] == "OST_Doors"
    assert "params" in card


def test_inspect_selection_missing_uid(module, workspace):
    result = module.inspect_selection(element_uids=["nonexistent-uid"], workspace=workspace)
    assert result["inspected_count"] == 0
    assert "nonexistent-uid" in result["missing_uids"]


def test_inspect_selection_room_warnings(module, workspace):
    unplaced_uid = "c0326e0e-473d-4952-b8ec-f23696541f45-room-unplaced"
    result = module.inspect_selection(element_uids=[unplaced_uid], workspace=workspace)
    card = result["elements"][0]
    # Unplaced room should warn
    assert any("not placed" in w or "unplaced" in w.lower() for w in card["warnings"])


def test_save_and_run_saved_query(module, workspace):
    query_name = "all_doors"
    filter_dsl = {"category": "OST_Doors"}
    
    # Save
    save_res = module.save_query(query_name=query_name, filter=filter_dsl, workspace=workspace)
    assert save_res["status"] == "saved"
    
    # List
    list_res = module.list_saved_queries(workspace=workspace)
    assert list_res["count"] == 1
    assert list_res["queries"][0]["name"] == query_name
    
    # Run
    run_res = module.run_saved_query(query_name=query_name, workspace=workspace)
    assert run_res["matches_count"] == 1
    assert run_res["elements"][0]["category"] == "OST_Doors"


def test_run_nonexistent_query_raises(module, workspace):
    with pytest.raises(ValueError, match="No saved query"):
        module.run_saved_query(query_name="does_not_exist", workspace=workspace)
