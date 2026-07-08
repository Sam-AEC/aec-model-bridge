"""Tests for Phase 8 — Selection Tools module (W2 write side, W4)."""
import importlib.util
import json
import pytest
from pathlib import Path
from revit_mcp_server.semantic.engine import generate_mock_snapshot

# Load the module file directly to bypass sys.modules namespace conflict
_MODULE_PY = (
    Path(__file__).parent.parent
    / "src/revit_mcp_server/modules/selection_tools/module.py"
)
_spec = importlib.util.spec_from_file_location("_selection_tools_impl", _MODULE_PY)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SelectionToolsModule = _mod.SelectionToolsModule


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def module():
    return SelectionToolsModule()


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


# --- Selection tests ---

def test_set_selection_creates_pending_file(module, workspace, tmp_path):
    uids = ["uid-1", "uid-2"]
    result = module.set_selection(element_uids=uids, workspace=workspace)
    assert result["status"] == "staged"
    assert result["element_count"] == 2
    pending_path = tmp_path / "pending_selection.json"
    assert pending_path.exists()
    data = json.loads(pending_path.read_text())
    assert data["element_uids"] == uids


def test_save_and_restore_selection(module, workspace):
    uids = ["wall-uid-abc", "door-uid-xyz"]
    module.save_selection(selection_name="test_sel", element_uids=uids, workspace=workspace)
    
    res = module.restore_selection(selection_name="test_sel", workspace=workspace)
    assert res["status"] == "staged"
    assert res["element_count"] == 2


def test_restore_nonexistent_raises(module, workspace):
    with pytest.raises(ValueError, match="No saved selection"):
        module.restore_selection(selection_name="does_not_exist", workspace=workspace)


def test_list_saved_selections(module, workspace):
    module.save_selection("sel_a", ["uid-1"], workspace=workspace)
    module.save_selection("sel_b", ["uid-2", "uid-3"], workspace=workspace)
    result = module.list_saved_selections(workspace=workspace)
    assert result["count"] == 2
    names = {s["name"] for s in result["selections"]}
    assert "sel_a" in names
    assert "sel_b" in names


def test_select_by_query_doors(module, workspace):
    result = module.select_by_query(filter={"category": "OST_Doors"}, workspace=workspace)
    assert result["status"] == "staged"
    assert result["element_count"] == 1


def test_select_by_query_with_snapshot(module, snap_and_workspace):
    snap, ws = snap_and_workspace
    result = module.select_by_query(
        filter={"category": "OST_Walls"},
        snapshot_id=snap.snapshot_id,
        workspace=ws
    )
    assert result["element_count"] == 1


# --- Group write plan tests ---

def test_group_rename_returns_action_plan(module, workspace):
    result = module.group_rename(group_uid="some-group-uid", new_name="Lobby_Group_A", workspace=workspace)
    assert result["plan_type"] == "action_plan_draft"
    assert result["requires_approval"] is True
    assert result["arguments"]["new_name"] == "Lobby_Group_A"
    assert "Lobby_Group_A" in result["preview"]["description"]


def test_group_ungroup_returns_plan_with_member_count(module, workspace):
    result = module.group_ungroup(group_uid="some-group-uid", workspace=workspace)
    assert result["plan_type"] == "action_plan_draft"
    assert result["tool"] == "group_ungroup"
    assert "member_count" in result["preview"]
    # Unsupported cases are documented
    assert "nested groups" in result["preview"]["unsupported_cases"]


def test_group_convert_returns_action_plan(module, workspace):
    result = module.group_convert_to_detail(group_uid="some-group-uid", workspace=workspace)
    assert result["plan_type"] == "action_plan_draft"
    assert result["tool"] == "group_convert_to_detail"
