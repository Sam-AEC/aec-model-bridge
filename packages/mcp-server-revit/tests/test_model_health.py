"""Tests for the model_health module (score formula and trend)."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.model_health import module as mh
from revit_mcp_server.modules.model_health.module import ModelHealthModule, compute_components


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _el(uid, cat="OST_Doors", mark="1", **kw):
    return {"uid": uid, "category": cat, "level_uid": "L1", "params": {"Mark": {"v": mark}}, **kw}


def _data(elements, types=None, counts=None, sid="s"):
    return {"snapshot_id": sid, "taken_at": "", "source": {}, "elements": elements,
            "types": types or [], "counts": counts or {}, "is_mock": False}


def _comp(res, name):
    return next(c for c in res["components"] if c["name"] == name)


def _write(ws, sid, elements, taken_at="2026-11-01T09:00:00+00:00", guid="g-1", types=None, **extra):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({
        "snapshot_id": sid, "taken_at": taken_at, "elements": elements, "types": types or [],
        "source": {"doc_title": "T", "doc_guid": guid}, **extra,
    }), encoding="utf-8")


# ---- formula -------------------------------------------------------------------------------

def test_warnings_component_formula():
    res = compute_components(_data([_el(f"e{i}") for i in range(100)], counts={"warnings": 4}))
    c = _comp(res, "warnings")
    assert c["inputs"]["warnings_per_1000_elements"] == 40.0
    assert c["subscore"] == 0.0  # 100 - 5 x 40, floored at 0
    res = compute_components(_data([_el(f"e{i}") for i in range(1000)], counts={"warnings": 4}))
    assert _comp(res, "warnings")["subscore"] == 80.0


def test_unplaced_rooms_component():
    rooms = [{"uid": f"r{i}", "category": "OST_Rooms", "params": {}} for i in range(3)]
    rooms[0]["level_uid"] = "L1"
    res = compute_components(_data(rooms))
    c = _comp(res, "unplaced_rooms")
    assert c["inputs"] == {"rooms": 3, "unplaced": 2} and c["subscore"] == 33.3


def test_unused_types_component_and_partial_exclusion():
    types = [{"uid": "t1", "family": "F", "type_name": "A", "family_source": "loadable"},
             {"uid": "t2", "family": "F", "type_name": "B", "family_source": "loadable"},
             {"uid": "t3", "family": "W", "type_name": "G", "family_source": "system"}]
    els = [_el("e1", type_uid="t1"), _el("e2", type_uid="t1")]
    res = compute_components(_data(els, types))
    assert _comp(res, "unused_types")["inputs"] == {"types": 2, "unused": 1}
    assert _comp(res, "unused_types")["subscore"] == 50.0
    part = compute_components(_data(els, types, counts={"truncated": True}))
    assert "unused_types" not in [c["name"] for c in part["components"]]
    assert any(e["name"] == "unused_types" and "partial" in e["reason"] for e in part["excluded"])
    assert part["partial"] is True


def test_completeness_component():
    res = compute_components(_data([_el("a", mark="1"), _el("b", mark="")]))
    c = _comp(res, "completeness")
    assert c["subscore"] == 50.0 and c["inputs"]["filled"] == 1 and c["inputs"]["total"] == 2


def test_qa_component_only_with_rule_pack(ws):
    doors = [_el(f"d{i}", mark="") for i in range(2)] + [_el("ok", mark="9")]
    assert "qa_findings" not in [c["name"] for c in compute_components(_data(doors))["components"]]
    res = compute_components(_data(doors, sid="x"), rule_pack="core", workspace=ws)
    c = _comp(res, "qa_findings")
    flagged = c["inputs"]["elements_flagged"]
    assert flagged >= 2 and c["subscore"] == round(100 * (1 - flagged / 3), 1)


def test_score_is_weighted_mean_of_used_components():
    # warnings 0 (weight 25) and completeness 100 (weight 15): (25*0 + 15*100) / 40 = 37.5
    els = [_el(f"e{i}") for i in range(100)]
    res = compute_components(_data(els, counts={"warnings": 4}))
    assert [c["name"] for c in res["components"]] == ["warnings", "completeness"]
    assert res["score"] == 37.5


def test_missing_inputs_are_listed_not_zeroed():
    res = compute_components(_data([_el("a")]))
    assert [c["name"] for c in res["components"]] == ["completeness"]
    assert res["score"] == 100.0  # the missing inputs did not drag it down
    assert {e["name"] for e in res["excluded"]} == {"warnings", "qa_findings", "unplaced_rooms", "unused_types"}
    assert all(e["reason"] for e in res["excluded"])


def test_no_inputs_gives_no_score():
    res = compute_components(_data([]))
    assert res["score"] is None and res["components"] == []


def test_score_is_deterministic():
    data = _data([_el(f"e{i}", mark="" if i % 3 else "1") for i in range(30)], counts={"warnings": 2})
    assert compute_components(data) == compute_components(data)


# ---- trend ---------------------------------------------------------------------------------

def test_trend_sorted_by_capture_time_with_deltas(ws):
    full = [_el("a", mark="1"), _el("b", mark="1")]
    half = [_el("a", mark="1"), _el("b", mark="")]
    _write(ws, "late", full, taken_at="2026-11-03T09:00:00+00:00")
    _write(ws, "early", half, taken_at="2026-11-01T09:00:00+00:00")
    _write(ws, "mid", half, taken_at="2026-11-02T09:00:00+00:00")
    res = ModelHealthModule().score(snapshot_id="mid", workspace=ws)
    pts = res["trend"]["points"]
    assert [p["snapshot_id"] for p in pts] == ["early", "mid", "late"]
    assert [p["score"] for p in pts] == [50.0, 50.0, 100.0]
    assert [p["delta"] for p in pts] == [None, 0.0, 50.0]
    assert pts[0]["delta_note"] == "First point."
    assert res["score"] == 50.0 and res["snapshot_id"] == "mid"


def test_trend_filters_by_document(ws):
    _write(ws, "a1", [_el("a")], guid="doc-A", taken_at="2026-11-01T09:00:00+00:00")
    _write(ws, "a2", [_el("a")], guid="doc-A", taken_at="2026-11-02T09:00:00+00:00")
    _write(ws, "b1", [_el("a")], guid="doc-B", taken_at="2026-11-01T12:00:00+00:00")
    res = ModelHealthModule().score(snapshot_id="a2", workspace=ws)
    assert [p["snapshot_id"] for p in res["trend"]["points"]] == ["a1", "a2"]
    assert res["trend"]["snapshots_of_document"] == 2


def test_no_doc_guid_means_no_trend(ws):
    _write(ws, "s1", [_el("a")], guid="")
    res = ModelHealthModule().score(snapshot_id="s1", workspace=ws)
    assert res["trend"]["points"] == [] and "doc_guid" in res["trend"]["note"]


def test_delta_withheld_for_partial_or_different_components(ws):
    _write(ws, "s1", [_el("a", mark="1")], taken_at="2026-11-01T09:00:00+00:00")
    _write(ws, "s2", [_el("a", mark="")], taken_at="2026-11-02T09:00:00+00:00", counts={"truncated": True})
    _write(ws, "s3", [_el("a", mark="")], taken_at="2026-11-03T09:00:00+00:00", counts={"warnings": 0})
    pts = ModelHealthModule().score(snapshot_id="s3", workspace=ws)["trend"]["points"]
    assert pts[1]["partial"] is True and pts[1]["delta"] is None and "partial" in pts[1]["delta_note"]
    assert pts[2]["delta"] is None  # previous point is partial
    _write(ws, "s2", [_el("a", mark="")], taken_at="2026-11-02T09:00:00+00:00")
    pts = ModelHealthModule().score(snapshot_id="s3", workspace=ws)["trend"]["points"]
    assert pts[2]["comparable"] is False and "different components" in pts[2]["delta_note"]


def test_trend_off_and_max_points(ws):
    for i in range(4):
        _write(ws, f"s{i}", [_el("a")], taken_at=f"2026-11-0{i + 1}T09:00:00+00:00")
    assert ModelHealthModule().score(snapshot_id="s3", include_trend=False, workspace=ws)["trend"] == {"included": False}
    res = ModelHealthModule().score(snapshot_id="s3", max_points=2, workspace=ws)
    assert [p["snapshot_id"] for p in res["trend"]["points"]] == ["s2", "s3"]
    assert any("latest 2 of 4" in n for n in res["notes"])


def test_csv_output(ws):
    _write(ws, "s1", [_el("a")], taken_at="2026-11-01T09:00:00+00:00")
    _write(ws, "s2", [_el("a", mark="")], taken_at="2026-11-02T09:00:00+00:00")
    res = ModelHealthModule().score(snapshot_id="s2", csv_filename="reports/health.csv", workspace=ws)
    rows = list(csv.DictReader(Path(res["csv_file"]).open(encoding="utf-8")))
    assert [r["snapshot_id"] for r in rows] == ["s1", "s2"]
    assert rows[1]["delta"] == "-100.0" and rows[1]["completeness"] == "0.0"
    for bad in ("../h.csv", "h.txt"):
        with pytest.raises(ValueError):
            ModelHealthModule().score(snapshot_id="s2", csv_filename=bad, workspace=ws)


def test_hostile_id_and_bridge_mode(ws, monkeypatch):
    with pytest.raises(ValueError, match="plain snapshot name"):
        ModelHealthModule().score(snapshot_id="../x", workspace=ws)
    from revit_mcp_server.config import BridgeMode, config

    monkeypatch.setattr(config, "mode", BridgeMode.bridge)
    with pytest.raises(ValueError, match="requires a snapshot_id"):
        ModelHealthModule().score(workspace=ws)
    monkeypatch.setattr(config, "mode", BridgeMode.mock)
    res = ModelHealthModule().score(workspace=ws)
    assert res["mock"] is True and res["trend"]["points"] == []


def test_read_only_manifest_and_description():
    from revit_mcp_server.tool_metadata import DESCRIPTIONS

    manifest = json.loads((Path(mh.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert all(not c["is_mutating"] for c in manifest["commands"])
    assert DESCRIPTIONS["model_health_score"].endswith("Read-only.")
