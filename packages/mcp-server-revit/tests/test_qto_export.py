"""Tests for the qto_export module (quantity take-off to CSV and BC3)."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.qto_export import module as qto
from revit_mcp_server.modules.qto_export.module import QtoExportModule


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _el(uid, cat, type_name, family="", **q):
    params = {k.capitalize(): {"v": v, "storage": "Double"} for k, v in q.items() if v is not None}
    return {"uid": uid, "category": cat, "family": family, "type_name": type_name, "params": params}


ELEMENTS = [
    _el("w1", "OST_Walls", "Basic 200", "Basic Wall", area=10.0, length=4.0, volume=2.0),
    _el("w2", "OST_Walls", "Basic 200", "Basic Wall", area=5.5, length=2.0, volume=1.1),
    _el("w3", "OST_Walls", "Basic 200", "Basic Wall", length=3.0),  # no area, no volume
    _el("w4", "OST_Walls", "Brick 100", "Basic Wall", area=7.0, length=3.5, volume=0.7),
    _el("f1", "OST_Floors", "Slab 250", "Floor", area=30.0, volume=7.5),
    _el("d1", "OST_Doors", "0915", "Single"),
    _el("d2", "OST_Doors", "0915", "Single"),
    _el("g1", "OST_Grids", None),
]


def _snap(ws, sid="s1", elements=None):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps({
        "snapshot_id": sid, "taken_at": "2026-11-01T09:00:00+00:00",
        "elements": ELEMENTS if elements is None else elements, "types": [],
        "source": {"doc_title": "Tower A", "doc_guid": "g-1"},
    }), encoding="utf-8")
    return sid


def _run(ws, **kw):
    kw.setdefault("snapshot_units", "metres")
    return QtoExportModule().run(workspace=ws, **kw)


def _row(res, cat, type_name):
    return next(r for r in res["rows"] if r["category"] == cat and r["type"] == type_name)


def test_counts_and_sums_per_category_and_type(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1")
    w = _row(res, "OST_Walls", "Basic Wall: Basic 200")
    assert w["count"] == 3
    assert w["area_m2"] == 15.5 and w["area_elements"] == 2
    assert w["length_m"] == 9.0 and w["length_elements"] == 3
    assert w["volume_m3"] == 3.1
    assert _row(res, "OST_Walls", "Basic Wall: Brick 100")["area_m2"] == 7.0
    assert _row(res, "OST_Floors", "Floor: Slab 250")["volume_m3"] == 7.5
    assert res["read_only"] is True and res["element_count"] == 8


def test_missing_quantity_is_none_not_zero(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1")
    door = _row(res, "OST_Doors", "Single: 0915")
    assert door["count"] == 2
    assert door["area_m2"] is None and door["length_m"] is None and door["volume_m3"] is None
    assert door["no_quantity"] == 2
    assert _row(res, "OST_Floors", "Floor: Slab 250")["length_m"] is None


def test_elements_without_quantity_are_listed(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1")
    assert {e["uid"] for e in res["without_quantity"]} == {"d1", "d2", "g1"}  # w3 has a length
    assert res["without_quantity_total"] == 3
    assert next(e for e in res["without_quantity"] if e["uid"] == "g1")["type"] == "(no type)"


def test_csv_matches_expected_counts_and_areas(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", csv_filename="qto/take-off.csv")
    path = Path(res["csv_file"])
    assert path.is_relative_to(ws.allowed_directories[0].resolve())
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    by = {(r["category"], r["type"]): r for r in rows}
    wall = by[("OST_Walls", "Basic Wall: Basic 200")]
    assert (wall["count"], wall["area_m2"], wall["length_m"], wall["volume_m3"]) == ("3", "15.5", "9", "3.1")
    assert by[("OST_Walls", "Basic Wall: Brick 100")]["area_m2"] == "7"
    door = by[("OST_Doors", "Single: 0915")]
    assert door["count"] == "2" and door["area_m2"] == "" and door["no_quantity"] == "2"
    missing = Path(res["no_quantity_file"])
    assert missing.name == "take-off_no_quantity.csv"
    mrows = list(csv.DictReader(missing.read_text(encoding="utf-8").splitlines()))
    assert {r["uid"] for r in mrows} == {"d1", "d2", "g1"}


def test_feet_are_converted_to_metres(ws):
    _snap(ws, elements=[_el("w1", "OST_Walls", "T", area=10.7639104167, length=3.280839895, volume=35.3146667)])
    res = QtoExportModule().run(workspace=ws, snapshot_id="s1")  # default feet
    r = res["rows"][0]
    assert (r["area_m2"], r["length_m"], r["volume_m3"]) == (1.0, 1.0, 1.0)
    assert res["snapshot_units"] == "feet"


def test_category_filter(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", categories=["OST_Floors"])
    assert [r["category"] for r in res["rows"]] == ["OST_Floors"]
    assert res["without_quantity_total"] == 0


def test_csv_neutralises_formula_text(ws):
    _snap(ws, elements=[_el("x", "OST_Walls", "=HYPERLINK(1)", area=1.0)])
    res = _run(ws, snapshot_id="s1", csv_filename="q.csv")
    assert "'=HYPERLINK(1)" in Path(res["csv_file"]).read_text(encoding="utf-8")


def read_bc3(path):
    """Minimal FIEBDC-3 reader: records are ~X|f|f|...|, subfields split on a backslash."""
    text = Path(path).read_bytes().decode("cp1252")
    out = {"V": [], "C": {}, "D": [], "M": []}
    for line in text.split("\r\n"):
        if not line:
            continue
        assert line[0] == "~" and line[2] == "|" and line.endswith("|"), line
        kind, fields = line[1], line[3:-1].split("|")
        if kind == "V":
            out["V"] = fields
        elif kind == "C":
            code, unit, summary, price, _date, ctype = (fields + [""] * 6)[:6]
            out["C"][code] = {"unit": unit, "summary": summary, "price": price, "type": ctype}
        elif kind == "D":
            parts = fields[1].split("\\")
            kids = [(parts[i], parts[i + 1], parts[i + 2]) for i in range(0, len(parts) - 2, 3)]
            out["D"].append((fields[0], kids))
        elif kind == "M":
            parent, child = fields[0].split("\\")
            out["M"].append({"parent": parent, "child": child, "total": float(fields[2]), "lines": fields[3]})
    return out


def test_bc3_parses_and_is_consistent(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", bc3_filename="take-off.bc3")
    bc3 = read_bc3(res["bc3_file"])
    assert bc3["V"][1].startswith("FIEBDC-3") and bc3["V"][4] == "ANSI"
    roots = [c for c in bc3["C"] if c.endswith("##")]
    chapters = [c for c in bc3["C"] if c.endswith("#") and not c.endswith("##")]
    items = [c for c in bc3["C"] if not c.endswith("#")]
    assert len(roots) == 1 and len(chapters) == 4 and len(items) == 5
    decomp = dict(bc3["D"])
    assert {k for k, _, _ in decomp[roots[0]]} == set(chapters)
    for _parent, kids in bc3["D"]:
        assert all(child in bc3["C"] for child, _, _ in kids)
    assert all(bc3["C"][i]["price"] == "" for i in items)  # no pricing
    by_summary = {bc3["C"][i]["summary"]: i for i in items}
    wall = by_summary["Basic Wall: Basic 200"]
    assert bc3["C"][wall]["unit"] == "m2"
    assert next(x for x in bc3["M"] if x["child"] == wall)["total"] == 15.5
    yields = {c: float(y) for kids in decomp.values() for c, _, y in kids}
    assert yields[wall] == 15.5
    door = by_summary["Single: 0915"]
    assert bc3["C"][door]["unit"] == "ud" and yields[door] == 2.0
    assert next(x for x in bc3["M"] if x["child"] == door)["total"] == 2.0


def test_bc3_is_ansi_and_strips_separators(ws):
    _snap(ws, elements=[_el("x", "OST_Walls", "Mur | béton ~ 20\\cm", "Mür", area=2.0)])
    res = _run(ws, snapshot_id="s1", bc3_filename="a.bc3")
    raw = Path(res["bc3_file"]).read_bytes()
    assert "Mür: Mur béton 20 cm".encode("cp1252") in raw
    assert b"\r\n" in raw
    read_bc3(res["bc3_file"])


def test_bc3_measure_override(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", bc3_filename="a.bc3", bc3_measure="length")
    bc3 = read_bc3(res["bc3_file"])
    wall = next(i for i, c in bc3["C"].items() if c["summary"] == "Basic Wall: Basic 200")
    assert bc3["C"][wall]["unit"] == "m"
    assert next(m for m in bc3["M"] if m["child"] == wall)["total"] == 9.0


def test_bc3_falls_back_to_count_when_measure_is_missing(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", bc3_filename="a.bc3", bc3_measure="volume")
    bc3 = read_bc3(res["bc3_file"])
    door = next(i for i, c in bc3["C"].items() if c["summary"] == "Single: 0915")
    assert bc3["C"][door]["unit"] == "ud"


@pytest.mark.parametrize("name", ["../x.csv", "/abs/x.csv", "plans/x.csv", "proofs/x.csv"])
def test_output_outside_workspace_is_refused(ws, name):
    _snap(ws)
    with pytest.raises(ValueError):
        _run(ws, snapshot_id="s1", csv_filename=name)


def test_wrong_suffix_is_refused(ws):
    _snap(ws)
    with pytest.raises(ValueError, match=r"\.bc3"):
        _run(ws, snapshot_id="s1", bc3_filename="x.csv")


def test_bad_snapshot_id_is_refused(ws):
    with pytest.raises(ValueError):
        _run(ws, snapshot_id="../evil")
    with pytest.raises(ValueError, match="not found"):
        _run(ws, snapshot_id="nope")


def test_bridge_mode_requires_snapshot_id(ws, monkeypatch):
    from revit_mcp_server.config import BridgeMode, config

    monkeypatch.setattr(config, "mode", BridgeMode.bridge)
    with pytest.raises(ValueError, match="requires a snapshot_id"):
        _run(ws)


def test_mock_mode_is_labelled(ws, monkeypatch):
    from revit_mcp_server.config import BridgeMode, config

    monkeypatch.setattr(config, "mode", BridgeMode.mock)
    res = _run(ws)
    assert res["mock"] is True and "MOCK" in res["data_source"]


def test_read_only_manifest_and_description():
    from revit_mcp_server.tool_metadata import DESCRIPTIONS, REPORT_FILE_WRITERS

    manifest = json.loads((Path(qto.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert all(not c["is_mutating"] for c in manifest["commands"])
    assert DESCRIPTIONS["qto_export_run"].endswith("Read-only.")
    assert "qto_export_run" in REPORT_FILE_WRITERS
