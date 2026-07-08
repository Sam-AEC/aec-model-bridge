"""Tests for Phase 9 — Parameter Manager + Family Type Mapper modules (W5, W6)."""
import importlib.util
import csv
import json
import pytest
from pathlib import Path
from revit_mcp_server.semantic.engine import generate_mock_snapshot


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_pm = _load_mod("src/revit_mcp_server/modules/parameter_manager/module.py", "_pm_impl")
ParameterManagerModule = _pm.ParameterManagerModule

_fm = _load_mod("src/revit_mcp_server/modules/familytype_mapper/module.py", "_fm_impl")
FamilytypeMapperModule = _fm.FamilytypeMapperModule


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def pm():
    return ParameterManagerModule()


@pytest.fixture
def fm():
    return FamilytypeMapperModule()


@pytest.fixture
def snap_and_ws(tmp_path):
    ws = MockWorkspace(tmp_path)
    snap = generate_mock_snapshot()
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{snap.snapshot_id}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        f.write(snap.model_dump_json(by_alias=True, indent=2))
    return snap, ws


# ===========================================================================
# ParameterManager tests
# ===========================================================================

def test_filter_params_door_mark(pm, workspace):
    result = pm.filter_params(
        element_filter={"category": "OST_Doors"},
        param_name="Mark",
        workspace=workspace
    )
    assert result["param_name"] == "Mark"
    assert result["rows_with_param"] == 1
    assert result["rows"][0]["value"] == "D-101"


def test_filter_params_excludes_readonly(pm, workspace):
    result = pm.filter_params(
        element_filter={"category": "OST_Levels"},
        param_name="Elevation",
        include_readonly=False,
        workspace=workspace
    )
    # Elevation is readonly on levels, should be excluded
    assert result["rows_with_param"] == 0


def test_filter_params_includes_readonly(pm, workspace):
    result = pm.filter_params(
        element_filter={"category": "OST_Levels"},
        param_name="Elevation",
        include_readonly=True,
        workspace=workspace
    )
    assert result["rows_with_param"] == 2


def test_plan_set_params_valid(pm, workspace):
    result = pm.plan_set_params(
        element_filter={"category": "OST_Doors"},
        param_updates={"Mark": "D-201"},  # String → String: valid
        workspace=workspace,
    )
    assert result["plan_type"] == "action_plan_draft"
    assert result["requires_approval"] is True
    planned = result["preview"]["planned"]
    assert len(planned) == 1
    assert planned[0]["updates"]["Mark"]["after"] == "D-201"
    assert planned[0]["updates"]["Mark"]["before"] == "D-101"


def test_plan_set_params_emits_plan_actions_ready_actions(pm, workspace):
    """result['actions'] must be directly consumable by the approval gate's
    plan_actions tool — this is the bridge that lets a batch parameter change
    actually get applied, not just previewed (see providers/approval_provider.py)."""
    result = pm.plan_set_params(
        element_filter={"category": "OST_Doors"},
        param_updates={"Mark": "D-201"},
        workspace=workspace,
    )
    actions = result["actions"]
    assert len(actions) == 1
    assert actions[0] == {
        "tool": "revit_set_parameter_value",
        "arguments": {"element_id": actions[0]["arguments"]["element_id"], "parameter_name": "Mark", "value": "D-201"},
    }
    assert actions[0]["arguments"]["element_id"] is not None


def test_plan_set_params_blocked_updates_produce_no_actions(pm, workspace):
    result = pm.plan_set_params(
        element_filter={"category": "OST_Levels"},
        param_updates={"Elevation": 10.0},
        workspace=workspace,
    )
    assert result["actions"] == []


def test_plan_set_params_blocks_readonly(pm, workspace):
    result = pm.plan_set_params(
        element_filter={"category": "OST_Levels"},
        param_updates={"Elevation": 10.0},  # Elevation is readonly
        workspace=workspace,
    )
    blocked = result["preview"]["blocked"]
    assert any("read-only" in b["reason"] for b in blocked)
    assert result["preview"]["planned_count"] == 0


def test_plan_set_params_blocks_wrong_storage_type(pm, workspace):
    result = pm.plan_set_params(
        element_filter={"category": "OST_Doors"},
        param_updates={"Mark": 12345},  # Mark is String, not int
        workspace=workspace,
    )
    blocked = result["preview"]["blocked"]
    assert any("storage type" in b["reason"] or "String" in b["reason"] for b in blocked)


def test_export_and_import_params_csv(pm, workspace, tmp_path):
    # 1. Export
    export_result = pm.export_params_csv(
        element_filter={"category": "OST_Doors"},
        param_names=["Mark", "FireRating"],
        output_filename="doors_export.csv",
        workspace=workspace,
    )
    assert export_result["status"] == "exported"
    csv_path = tmp_path / "doors_export.csv"
    assert csv_path.exists()
    
    # Validate CSV content
    rows = list(csv.DictReader(open(csv_path, "r", encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["Mark"] == "D-101"
    
    # 2. Modify CSV and import
    rows[0]["Mark"] = "D-999"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    
    import_result = pm.import_params_csv(
        csv_filename="doors_export.csv",
        workspace=workspace,
    )
    assert import_result["plan_type"] == "action_plan_draft"
    planned = import_result["preview"]["planned"]
    assert len(planned) == 1
    assert planned[0]["updates"]["Mark"]["after"] == "D-999"


# ===========================================================================
# FamilytypeMapper tests
# ===========================================================================

def test_audit_families_no_inplace(fm, workspace):
    result = fm.audit_families(workspace=workspace)
    assert "families_total" in result
    assert result["families_total"] >= 2
    # Mock snapshot uses system + loadable families, no inplace
    assert result["inplace_count"] == 0


def test_audit_families_returns_findings(fm, workspace):
    result = fm.audit_families(workspace=workspace)
    # No findings expected from our clean mock
    assert isinstance(result["findings"], list)


def test_list_type_mappings_all_categories(fm, workspace):
    result = fm.list_type_mappings(workspace=workspace)
    assert result["families_count"] >= 1
    for m in result["mappings"]:
        assert "family" in m
        assert "types" in m
        for t in m["types"]:
            assert "type_name" in t
            assert "instance_count" in t


def test_list_type_mappings_filtered_by_category(fm, workspace):
    result = fm.list_type_mappings(category="OST_Doors", workspace=workspace)
    assert result["category_filter"] == "OST_Doors"
    # Only door families should appear
    for m in result["mappings"]:
        assert m["family"] in ("Single-Flush",)
