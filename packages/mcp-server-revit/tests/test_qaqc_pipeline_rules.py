"""QA/QC rules written as snapshot_compute pipelines (rule field `pipeline`)."""
import importlib.util
import shutil
from pathlib import Path

import pytest

from revit_mcp_server.semantic.engine import generate_mock_snapshot
from revit_mcp_server.semantic.models import ElementRecord, LocationPoint, ParamVal, TypeRecord


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_qaqc = _load_mod("src/revit_mcp_server/modules/qaqc_checker/module.py", "_qaqc_pipeline_impl")
EXAMPLES = Path(__file__).resolve().parents[3] / "docs" / "examples" / "rule_packs"
LEVEL_1 = "c0326e0e-473d-4952-b8ec-f23696541f41-level-1"
WALL = "c0326e0e-473d-4952-b8ec-f23696541f43-wall-1"


class _WS:
    def __init__(self, root: Path):
        self.allowed_directories = [root]


def _door(uid, element_id, mark=None, placed=True, host=WALL, rating=None):
    params = {}
    if mark is not None:
        params["Mark"] = ParamVal(v=mark, storage="String")
    if rating is not None:
        params["Fire Rating"] = ParamVal(v=rating, storage="String")
    return ElementRecord(
        uid=uid, element_id=element_id, category="OST_Doors", cls="FamilyInstance",
        type_uid="door-type-uid-0001", family="Single-Flush", type_name="0915 x 2134mm",
        level_uid=LEVEL_1 if placed else None, host_uid=host, params=params,
        location=LocationPoint(xyz=[1.0, 0.0, 0.0]) if placed else None,
    )


def _snapshot_with_issues():
    """The mock snapshot plus elements that break each converted rule at least once."""
    snap = generate_mock_snapshot()
    wall = next(e for e in snap.elements if e.uid == WALL)
    wall.params["Fire Rating"] = ParamVal(v="60", storage="String")
    snap.elements += [
        _door("door-no-mark", 310),
        _door("door-empty-mark", 311, mark=""),
        _door("door-unplaced", 312, mark="D-900", placed=False, host=None),
        _door("door-low-rating", 313, mark="D-901", rating="30"),
        _door("door-ok-rating", 314, mark="D-902", rating="90"),
        ElementRecord(uid="room-no-number", element_id=410, category="OST_Rooms", cls="Room", type_name="Store",
                      level_uid=LEVEL_1, params={"Area": ParamVal(v=4.0, storage="Double")}),
        ElementRecord(uid="room-empty-number", element_id=411, category="OST_Rooms", cls="Room", type_name="Hall",
                      params={"Number": ParamVal(v="", storage="String")}),
        ElementRecord(uid="wall-no-type", element_id=210, category="OST_Walls", cls="Wall"),
    ]
    snap.types.append(TypeRecord(uid="inplace-type", category="OST_GenericModel", family="Blob",
                                 type_name="Blob", family_source="inplace"))
    return snap


@pytest.fixture
def ws_and_snap(tmp_path):
    snap = _snapshot_with_issues()
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / f"{snap.snapshot_id}.json").write_text(
        snap.model_dump_json(by_alias=True), encoding="utf-8"
    )
    (tmp_path / "rule_packs").mkdir()
    return _WS(tmp_path), snap


def _keys(result, rule_ids=None):
    return sorted(
        (f["rule_id"], f["element_uid"], f["label"], f["severity"])
        for f in result["findings"] if rule_ids is None or f["rule_id"] in rule_ids
    )


def test_example_pipeline_pack_finds_the_same_issues_as_door_room_basics(ws_and_snap):
    ws, snap = ws_and_snap
    for name in ("door-room-basics", "door-room-pipeline"):
        shutil.copy(EXAMPLES / f"{name}.yaml", ws.allowed_directories[0] / "rule_packs" / f"{name}.yaml")
    module = _qaqc.QaqcCheckerModule()
    filtered = module.run_check(snapshot_id=snap.snapshot_id, rule_pack="door-room-basics", workspace=ws)
    piped = module.run_check(snapshot_id=snap.snapshot_id, rule_pack="door-room-pipeline", workspace=ws)
    converted = {"door_mark_missing", "door_not_placed", "room_number_missing"}

    assert _keys(piped, converted) == _keys(filtered)
    assert {f["rule_id"] for f in filtered["findings"]} == converted  # every rule found something
    assert [r for r in piped["rules"] if "error" in r] == []
    # The rule filter cannot express: door rated below its host wall.
    assert _keys(piped, {"door_rating_below_wall"}) == [
        ("door_rating_below_wall", "door-low-rating", "0915 x 2134mm", "error"),
    ]
    issues = module.list_issues(workspace=ws)["issues"]
    assert {(i["rule_pack"], i["element_uid"]) for i in issues} >= {
        ("door-room-pipeline", "door-no-mark"), ("door-room-pipeline", "door-low-rating"),
    }


CORE_AS_PIPELINES = """rules:
  - id: room_not_placed
    severity: error
    description: "Room exists but is not placed on a level."
    pipeline:
      - where:
          - {field: category, value: OST_Rooms}
          - {field: level_uid, op: exists, value: false}
          - {field: location, op: exists, value: false}
  - id: door_no_host
    severity: error
    description: "Door is not hosted (missing host_uid)."
    pipeline:
      - where: [{field: category, value: OST_Doors}, {field: host_uid, op: empty}]
  - id: wall_missing_type
    severity: error
    description: "Wall has no type_name set."
    pipeline:
      - where: [{field: category, value: OST_Walls}, {field: type_name, op: empty}]
  - id: inplace_family_used
    severity: warning
    description: "In-place families are present."
    pipeline:
      - from: types
        where: {field: family_source, value: inplace}
"""


def test_core_rules_as_pipelines_match_the_core_pack(ws_and_snap):
    """Both assertion kinds and family_source rules, on the mock snapshot and on the generated mock."""
    ws, snap = ws_and_snap
    (ws.allowed_directories[0] / "rule_packs" / "core-piped.yaml").write_text(CORE_AS_PIPELINES, encoding="utf-8")
    module = _qaqc.QaqcCheckerModule()
    ids = {"room_not_placed", "door_no_host", "wall_missing_type", "inplace_family_used"}
    core = module.run_check(snapshot_id=snap.snapshot_id, rule_pack="core", workspace=ws)
    piped = module.run_check(snapshot_id=snap.snapshot_id, rule_pack="core-piped", workspace=ws)
    assert _keys(piped) == _keys(core, ids)
    assert {f["rule_id"] for f in piped["findings"]} == ids

    core_mock = module.run_check(rule_pack="core", workspace=ws)
    piped_mock = module.run_check(rule_pack="core-piped", workspace=ws)
    assert _keys(piped_mock) == _keys(core_mock, ids) == [
        ("room_not_placed", "c0326e0e-473d-4952-b8ec-f23696541f45-room-unplaced", "Office 1", "error"),
    ]


def test_pipeline_rules_use_snapshot_relations(ws_and_snap):
    ws, snap = ws_and_snap
    pack = """rules:
  - id: hosted_by_relation
    severity: info
    description: "Door hosted through a relation record."
    pipeline:
      - join: [{rel: relation_in, kind: hosts, as: hosts}]
        where: [{field: category, value: OST_Doors}, {field: hosts, op: empty, value: false}]
"""
    (ws.allowed_directories[0] / "rule_packs" / "rel.yaml").write_text(pack, encoding="utf-8")
    module = _qaqc.QaqcCheckerModule()
    found = module.run_check(snapshot_id=snap.snapshot_id, rule_pack="rel", workspace=ws)["findings"]
    assert [f["element_uid"] for f in found] == ["c0326e0e-473d-4952-b8ec-f23696541f44-door-1"]
    mock = module.run_check(rule_pack="rel", workspace=ws)["findings"]
    assert [f["element_uid"] for f in mock] == ["c0326e0e-473d-4952-b8ec-f23696541f44-door-1"]

    rg = _load_mod("src/revit_mcp_server/modules/report_generator/module.py", "_rg_pipeline_impl")
    data = rg._load_review_snapshot(snap.snapshot_id, ws)
    groups = rg._review_findings(data["elements"], data["types"], "doc", "rel", ws, [], data.get("relations"))
    assert len(groups) == 1


@pytest.mark.parametrize(
    ("rule", "field", "message"),
    [
        ({"pipeline": [{"where": {"field": "x", "op": "regex", "value": "a"}}]}, "pipeline", "unknown op"),
        ({"pipeline": [{"lambda": 1}]}, "pipeline", "unknown keys"),
        ({"pipeline": []}, "pipeline", "non-empty"),
        ({"pipeline": "doors"}, "pipeline", "non-empty"),
        ({"pipeline": [{"from": "link:other"}]}, "pipeline", "not available"),
        ({"pipeline": [{"group_by": "category", "aggregate": {"n": {"op": "median", "field": "x"}}}]},
         "pipeline", "unknown aggregate"),
        ({"pipeline": [{"group_by": ["category"], "aggregate": {"n": {"op": "sum"}}}]}, "pipeline", "needs a field"),
        ({"pipeline": [{}], "filter": {"category": "OST_Doors"}}, "filter", "has no filter"),
        ({"pipeline": [{}], "assertion": "element_count == 0"}, "assertion", "has no assertion"),
    ],
)
def test_invalid_pipeline_rules_are_refused(rule, field, message):
    data = {"rules": [{"id": "r", "severity": "error", "description": "d", **rule}]}
    errors = _qaqc._validate_pack_data(data)["errors"]
    assert any(e["field"] == field and message in e["message"] for e in errors), errors


def test_valid_pipeline_rule_has_no_warnings():
    data = {"rules": [{"id": "r", "severity": "error", "description": "d", "pipeline": [{"limit": 1}]}]}
    assert _qaqc._validate_pack_data(data) == {"errors": [], "warnings": [], "rules_count": 1}


def test_example_pipeline_pack_validates(tmp_path):
    module = _qaqc.QaqcCheckerModule()
    ws = _WS(tmp_path)
    copy = tmp_path / "door-room-pipeline.yaml"
    shutil.copy(EXAMPLES / "door-room-pipeline.yaml", copy)
    result = module.validate_rule_pack(path=str(copy), workspace=ws)
    assert result["valid"], result["errors"]
    assert result["rules_count"] == 4 and result["warnings"] == []


def test_pipeline_rows_with_a_non_text_uid_fail_the_rule_not_the_run(ws_and_snap):
    ws, snap = ws_and_snap
    pack = """rules:
  - id: uid_list
    severity: info
    description: "Grouped uids."
    pipeline:
      - group_by: category
        aggregate: {uid: {op: list, field: uid}}
  - id: rooms
    severity: info
    description: "Rooms."
    pipeline:
      - where: {field: category, value: OST_Rooms}
"""
    (ws.allowed_directories[0] / "rule_packs" / "bad-uid.yaml").write_text(pack, encoding="utf-8")
    result = _qaqc.QaqcCheckerModule().run_check(snapshot_id=snap.snapshot_id, rule_pack="bad-uid", workspace=ws)
    by_id = {r["id"]: r for r in result["rules"]}
    assert "uid" in by_id["uid_list"]["error"]
    assert by_id["rooms"]["findings"] > 0
    assert all(isinstance(f["label"], str) for f in result["findings"])
