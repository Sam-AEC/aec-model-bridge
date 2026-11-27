"""Tests for param_completeness_loin_report (LOIN completeness per category)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from revit_mcp_server.modules.param_completeness import module as pc_module
from revit_mcp_server.modules.param_completeness.module import ParamCompletenessModule

REQUIREMENTS = {
    "requirements": [
        {"category": "OST_Doors", "stage": "S3", "parameters": ["Mark", "FireRating", "Acoustic"]},
        {"category": "OST_Walls", "stage": "S3", "parameters": ["Comments"]},
        {"category": "OST_Doors", "stage": "S5", "parameters": ["Mark", "Manufacturer"]},
        {"category": "OST_Windows", "stage": "S3", "parameters": ["Mark"]},
    ]
}


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _el(uid, cat, **params):
    return {"uid": uid, "category": cat, "level_uid": "L1",
            "params": {k: {"v": v, "storage": "String"} for k, v in params.items()}}


def _snap(ws, sid="s1", **extra):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    elements = [
        _el("d1", "OST_Doors", Mark="1", FireRating="30"),
        _el("d2", "OST_Doors", Mark="2", FireRating=""),
        _el("d3", "OST_Doors", Mark="  ", FireRating="60"),
        _el("d4", "OST_Doors", Mark="4", FireRating=None),
        _el("w1", "OST_Walls", Comments="x"),
        _el("w2", "OST_Walls", Comments=None),
    ]
    (d / f"{sid}.json").write_text(json.dumps({
        "snapshot_id": sid, "taken_at": "2026-11-01T09:00:00+00:00", "elements": elements, "types": [],
        "source": {"doc_title": "Tower A", "doc_guid": "g-1"}, **extra,
    }), encoding="utf-8")


def _req(ws, name="tower", suffix=".yaml", data=None):
    d = ws.allowed_directories[0] / "loin"
    d.mkdir(exist_ok=True)
    data = REQUIREMENTS if data is None else data
    text = yaml.safe_dump(data) if suffix in (".yaml", ".yml") else json.dumps(data)
    (d / f"{name}{suffix}").write_text(text, encoding="utf-8")


def _run(ws, **kw):
    kw.setdefault("snapshot_id", "s1")
    kw.setdefault("requirements", "tower")
    return ParamCompletenessModule().loin_report(workspace=ws, **kw)


def _cat(res, cat, stage):
    return next(c for c in res["categories"] if c["category"] == cat and c["stage"] == stage)


def _param(c, name):
    return next(p for p in c["parameters"] if p["parameter"] == name)


def test_per_category_completeness_and_not_captured(ws):
    _snap(ws)
    _req(ws)
    res = _run(ws, stage="S3")
    assert res["read_only"] is True and res["stage"] == "S3"
    doors = _cat(res, "OST_Doors", "S3")
    mark, fire, ac = _param(doors, "Mark"), _param(doors, "FireRating"), _param(doors, "Acoustic")
    assert (mark["status"], mark["filled"], mark["total"], mark["percent"]) == ("captured", 3, 4, 75.0)
    assert (fire["status"], fire["filled"], fire["empty"]) == ("captured", 2, 2)
    assert ac["status"] == "not_captured" and ac["filled"] is None and ac["percent"] is None
    assert doors["not_captured_parameters"] == ["Acoustic"]
    assert doors["captured_parameters"] == ["Mark", "FireRating"]
    assert doors["percent"] == 62.5  # 5 of 8 cells on the two captured parameters
    assert doors["status"] == "incomplete"
    walls = _cat(res, "OST_Walls", "S3")
    assert walls["percent"] == 50.0 and walls["not_captured_parameters"] == []
    assert all(c["stage"] == "S3" for c in res["categories"])


def test_category_missing_from_snapshot_is_not_captured(ws):
    _snap(ws)
    _req(ws)
    win = _cat(_run(ws, stage="S3"), "OST_Windows", "S3")
    assert win["status"] == "not_captured" and win["total"] == 0 and win["percent"] is None
    assert win["not_captured_parameters"] == ["Mark"]


def test_all_stages_when_no_stage_given(ws):
    _snap(ws)
    _req(ws)
    res = _run(ws)
    assert {(c["category"], c["stage"]) for c in res["categories"]} == {
        ("OST_Doors", "S3"), ("OST_Walls", "S3"), ("OST_Doors", "S5"), ("OST_Windows", "S3")}
    assert _param(_cat(res, "OST_Doors", "S5"), "Manufacturer")["status"] == "not_captured"


def test_snapshot_parameter_filter_decides_what_was_captured(ws):
    _snap(ws, counts={"params": ["Mark"]})
    _req(ws)
    doors = _cat(_run(ws, stage="S3"), "OST_Doors", "S3")
    assert _param(doors, "FireRating")["status"] == "not_captured"  # carried by elements but outside the capture
    assert _param(doors, "Mark")["status"] == "captured"


def test_complete_category(ws):
    _snap(ws)
    _req(ws, data=[{"category": "OST_Walls", "stage": "S3", "parameters": ["Comments"]}])
    _snap(ws, sid="s2")
    p = ws.allowed_directories[0] / "snapshots" / "s2.json"
    data = json.loads(p.read_text())
    data["elements"] = [_el("w1", "OST_Walls", Comments="a"), _el("w2", "OST_Walls", Comments="b")]
    p.write_text(json.dumps(data))
    c = _cat(_run(ws, snapshot_id="s2"), "OST_Walls", "S3")
    assert c["status"] == "complete" and c["percent"] == 100.0


def test_json_requirement_file(ws):
    _snap(ws)
    _req(ws, suffix=".json")
    assert _cat(_run(ws, stage="S3"), "OST_Walls", "S3")["percent"] == 50.0


def test_stage_is_case_insensitive(ws):
    _snap(ws)
    _req(ws)
    assert {c["stage"] for c in _run(ws, stage="s5")["categories"]} == {"S5"}


def test_partial_snapshot_is_labelled(ws):
    _snap(ws, counts={"truncated": True})
    _req(ws)
    res = _run(ws, stage="S3")
    assert res["partial"] is True and any("partial" in n.lower() for n in res["notes"])


@pytest.mark.parametrize("name", ["../tower", "a/b", "tower.yaml", "", "..%x"])
def test_requirement_name_must_be_plain(ws, name):
    _snap(ws)
    _req(ws)
    with pytest.raises(ValueError, match="plain"):
        _run(ws, requirements=name)


def test_missing_requirement_file_is_refused(ws):
    _snap(ws)
    with pytest.raises(ValueError, match="not found"):
        _run(ws, requirements="nope")


@pytest.mark.parametrize("data", [
    {"requirements": "x"},
    {"requirements": [{"stage": "S3", "parameters": ["Mark"]}]},
    {"requirements": [{"category": "OST_Doors", "stage": "S3", "parameters": []}]},
    {"requirements": [{"category": "OST_Doors", "stage": "S3", "parameters": "Mark"}]},
    {"requirements": []},
    {"other": 1},
])
def test_malformed_requirements_are_refused(ws, data):
    _snap(ws)
    _req(ws, data=data)
    with pytest.raises(ValueError):
        _run(ws)


def test_unknown_stage_is_refused(ws):
    _snap(ws)
    _req(ws)
    with pytest.raises(ValueError, match="S9"):
        _run(ws, stage="S9")


def test_unparseable_file_is_refused(ws):
    _snap(ws)
    d = ws.allowed_directories[0] / "loin"
    d.mkdir()
    (d / "bad.yaml").write_text("a: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="could not be read"):
        _run(ws, requirements="bad")


def test_registered_as_read_only_tool(ws):
    from revit_mcp_server.tool_metadata import DESCRIPTIONS
    assert DESCRIPTIONS["param_completeness_loin_report"].endswith("Read-only.")
    manifest = json.loads((Path(pc_module.__file__).parent / "module.json").read_text(encoding="utf-8"))
    cmd = next(c for c in manifest["commands"] if c["id"] == "loin_report")
    assert cmd["is_mutating"] is False

def test_null_elements_is_a_value_error(ws):
    _snap(ws, elements=None)
    _req(ws)
    with pytest.raises(ValueError, match="elements"):
        _run(ws)
