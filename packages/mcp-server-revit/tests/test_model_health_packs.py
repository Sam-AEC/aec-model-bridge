"""docs/examples/rule_packs: workset, level, shared parameter and view template packs, run on fixture snapshots."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from revit_mcp_server.semantic.engine import generate_mock_snapshot
from revit_mcp_server.semantic.models import ElementRecord, ParamVal

PACKS = Path(__file__).resolve().parents[3] / "docs" / "examples" / "rule_packs"
_spec = importlib.util.spec_from_file_location(
    "_qaqc_health_impl", Path(__file__).parent.parent / "src/revit_mcp_server/modules/qaqc_checker/module.py")
_qaqc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_qaqc)

ASSET_CATEGORIES = (
    "OST_Doors", "OST_Windows", "OST_MechanicalEquipment", "OST_ElectricalEquipment", "OST_PlumbingFixtures")


class _WS:
    def __init__(self, root: Path):
        self.allowed_directories = [root]


def _el(uid, element_id, category="OST_Doors", cls="FamilyInstance", params=None, **fields):
    return ElementRecord(
        uid=uid, element_id=element_id, category=category, cls=cls, type_name="T",
        params={k: ParamVal(v=v, storage="String") for k, v in (params or {}).items()}, **fields)


def _level(uid, element_id, name=None, elevation=None):
    params = {} if elevation is None else {"Elevation": ParamVal(v=elevation, storage="Double")}
    return ElementRecord(
        uid=uid, element_id=element_id, category="OST_Levels", cls="Level", name=name, type_name="T", params=params)


def _run_full(tmp_path, pack, elements, drop=()):
    snap = generate_mock_snapshot()
    snap.elements = [e for e in snap.elements if e.category not in drop] + list(elements)
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        snap.model_dump_json(by_alias=True), encoding="utf-8")
    (tmp_path / "rule_packs").mkdir()
    shutil.copy(PACKS / f"{pack}.yaml", tmp_path / "rule_packs" / f"{pack}.yaml")
    result = _qaqc.QaqcCheckerModule().run_check(snapshot_id=snap.snapshot_id, rule_pack=pack, workspace=_WS(tmp_path))
    assert not [r for r in result["rules"] if "error" in r], result["rules"]
    return result


def _run(tmp_path, pack, elements, drop=()):
    result = _run_full(tmp_path, pack, elements, drop)
    return sorted((f["rule_id"], f["element_uid"]) for f in result["findings"])


@pytest.mark.parametrize("pack, severities", [
    ("workset-checks", {"info": 1, "error": 1, "warning": 3}),
    ("level-checks", {"info": 2, "error": 3, "warning": 1}),
    ("shared-parameter-checks", {"info": 2, "error": 1, "warning": 1}),
    ("view-template-checks", {"info": 1, "warning": 1}),
])
def test_pack_validates_and_every_rule_has_a_severity(pack, severities):
    result = _qaqc._validate_file(PACKS / f"{pack}.yaml")
    assert result["errors"] == [] and result["warnings"] == []
    rules = _qaqc._load_yaml_file(PACKS / f"{pack}.yaml")["rules"]
    counted = {}
    for rule in rules:
        assert rule["description"]
        counted[rule["severity"]] = counted.get(rule["severity"], 0) + 1
    assert counted == severities


# ------------------------------------------------------------------ worksets

def test_workset_pass_and_fail(tmp_path):
    elements = [
        _el("ok", 901, workset="Architecture"),
        _el("default", 902, workset="Workset1"),
        _el("default-spaced", 903, workset="workset 1"),
        _el("empty", 904, workset=""),
        _el("lead", 905, workset=" Structure"),
        _el("trail", 906, workset="Structure "),
        _el("double", 907, workset="MEP  Duct"),
        _el("level-ok", 908, "OST_Levels", "Level", workset="Shared Levels and Grids"),
        _el("level-bad", 909, "OST_Levels", "Level", workset="Architecture"),
        _el("grid-bad", 910, "OST_Grids", "Grid", workset="Workset1"),
        _el("grid-uncaptured", 911, "OST_Grids", "Grid"),
        _el("uncaptured", 912),
    ]
    assert _run(tmp_path, "workset-checks", elements) == [
        ("workset_default_name", "default"),
        ("workset_default_name", "default-spaced"),
        ("workset_default_name", "grid-bad"),
        ("workset_levels_grids_not_shared", "grid-bad"),
        ("workset_levels_grids_not_shared", "level-bad"),
        ("workset_name_empty", "empty"),
        ("workset_name_padded", "double"),
        ("workset_name_padded", "lead"),
        ("workset_name_padded", "trail"),
    ]


def test_workset_not_captured_when_no_element_has_one(tmp_path):
    elements = [_el("a", 901), _el("b", 902, "OST_Levels", "Level")]
    result = _run_full(tmp_path, "workset-checks", elements)
    assert [(f["rule_id"], f["severity"]) for f in result["findings"]] == [("workset_not_captured", "info")]


def test_workset_all_valid_has_no_findings(tmp_path):
    elements = [
        _el("a", 901, workset="Architecture"),
        _el("lvl", 902, "OST_Levels", "Level", workset="Shared Levels and Grids"),
    ]
    assert _run(tmp_path, "workset-checks", elements) == []


# -------------------------------------------------------------------- levels

def test_level_pass_and_fail(tmp_path):
    elements = [
        _level("ok-a", 901, "Level 00", 0.0),
        _level("ok-b", 902, "Level 01", 4.0),
        _level("empty", 903, "", 8.0),
        _level("no-name", 904, None, 12.0),
        _level("lead", 905, " Level 04", 16.0),
        _level("trail", 906, "Level 05 ", 20.0),
        _level("double", 907, "Level  06", 24.0),
        _level("no-elevation", 908, "Level 07"),
    ]
    assert _run(tmp_path, "level-checks", elements, drop=("OST_Levels",)) == [
        ("level_elevation_not_captured", "no-elevation"),
        ("level_name_empty", "empty"),
        ("level_name_not_captured", "no-name"),
        ("level_name_padded", "double"),
        ("level_name_padded", "lead"),
        ("level_name_padded", "trail"),
    ]


def test_level_duplicates_name_the_duplicated_value(tmp_path):
    elements = [
        _level("a", 901, "Level 01", 0.0),
        _level("b", 902, "Level 01", 3.0),
        _level("c", 903, "Level 02", 3.0),
        _level("d", 904, "Level 03", 6.0),
    ]
    result = _run_full(tmp_path, "level-checks", elements, drop=("OST_Levels",))
    findings = sorted((f["rule_id"], f["label"], f["severity"]) for f in result["findings"])
    assert findings == [
        ("level_elevation_duplicate", "['Level 01', 'Level 02']", "error"),
        ("level_name_duplicate", "Level 01", "error"),
    ]
    assert all(f["element_uid"] is None for f in result["findings"])


def test_level_all_valid_has_no_findings(tmp_path):
    elements = [_level(f"l{i}", 900 + i, f"Level {i:02d}", 4.0 * i) for i in range(4)]
    assert _run(tmp_path, "level-checks", elements, drop=("OST_Levels",)) == []


# ---------------------------------------------------------- shared parameters

def test_shared_parameter_pass_and_fail(tmp_path):
    full = {"Asset ID": "A-1", "Package Code": "P1"}
    elements = [
        _el("ok-door", 901, params=full),
        _el("ok-window", 902, "OST_Windows", params=full),
        _el("asset-empty", 903, params={"Asset ID": "", "Package Code": "P1"}),
        _el("package-empty", 904, params={"Asset ID": "A-2", "Package Code": ""}),
        _el("asset-missing", 905, params={"Package Code": "P1"}),
        _el("both-missing", 906, "OST_PlumbingFixtures"),
        _el("other-category", 907, "OST_Walls"),
    ]
    assert _run(tmp_path, "shared-parameter-checks", elements, drop=ASSET_CATEGORIES) == [
        ("asset_id_empty", "asset-empty"),
        ("asset_id_not_captured", "asset-missing"),
        ("asset_id_not_captured", "both-missing"),
        ("package_code_empty", "package-empty"),
        ("package_code_not_captured", "both-missing"),
    ]


def test_shared_parameter_all_valid_has_no_findings(tmp_path):
    elements = [
        _el(f"e{i}", 900 + i, c, params={"Asset ID": "A", "Package Code": "P"})
        for i, c in enumerate(ASSET_CATEGORIES)]
    assert _run(tmp_path, "shared-parameter-checks", elements, drop=ASSET_CATEGORIES) == []


# ------------------------------------------------------------- view templates

def _view(uid, element_id, template=None, cls="ViewPlan", category="OST_Views"):
    params = {} if template is None else {"View Template": template}
    return _el(uid, element_id, category, cls, params)


def test_view_template_pass_and_fail(tmp_path):
    elements = [
        _view("ok-plan", 901, "12345"),
        _view("ok-3d", 902, "12345", "View3D"),
        _view("none-id", 903, "-1"),
        _view("blank", 904, ""),
        _view("section-none", 905, "-1", "ViewSection"),
        _view("not-captured", 906),
        _view("schedule", 907, "-1", "ViewSchedule"),
        _view("not-a-view", 908, "-1", "Wall", "OST_Walls"),
    ]
    assert _run(tmp_path, "view-template-checks", elements) == [
        ("view_template_not_captured", "not-captured"),
        ("view_template_unassigned", "blank"),
        ("view_template_unassigned", "none-id"),
        ("view_template_unassigned", "section-none"),
    ]


def test_view_template_all_assigned_has_no_findings(tmp_path):
    assert _run(tmp_path, "view-template-checks", [_view("a", 901, "7"), _view("b", 902, "8", "ViewSection")]) == []
