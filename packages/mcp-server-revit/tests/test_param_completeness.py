"""Tests for the param_completeness module (fill-rate heatmap)."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.param_completeness import module as pc
from revit_mcp_server.modules.param_completeness.module import ParamCompletenessModule


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _door(uid, mark=None, fire=None, level="L1", extra=None):
    params = {"Mark": {"v": mark, "storage": "String"}}
    if fire is not None:
        params["FireRating"] = {"v": fire, "storage": "String"}
    params.update(extra or {})
    return {"uid": uid, "category": "OST_Doors", "level_uid": level, "params": params}


def _wall(uid, comment=None):
    return {"uid": uid, "category": "OST_Walls", "level_uid": "L2",
            "params": {"Comments": {"v": comment, "storage": "String"}}}


def _level(uid, name):
    return {"uid": uid, "category": "OST_Levels", "name": name, "params": {}}


def _snap(ws, sid="s1", elements=None, **extra):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    elements = elements if elements is not None else [
        _level("L1", "Level 1"), _level("L2", "Level 2"),
        _door("d1", "1", "30"), _door("d2", "2", ""), _door("d3", "  ", "60", level="L2"), _door("d4", "4", None),
        _wall("w1", "x"), _wall("w2"),
    ]
    (d / f"{sid}.json").write_text(json.dumps({
        "snapshot_id": sid, "taken_at": "2026-11-01T09:00:00+00:00", "elements": elements, "types": [],
        "source": {"doc_title": "Tower A", "doc_guid": "g-1"}, **extra,
    }), encoding="utf-8")
    return sid


def _run(ws, **kw):
    return ParamCompletenessModule().heatmap(workspace=ws, **kw)


def _cell(res, cat, param, level=None):
    return next(r for r in res["rows"] if r["category"] == cat and r["parameter"] == param
                and (level is None or r.get("level") == level))


def test_fill_rates_for_listed_parameters(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", parameters=["Mark", "FireRating"], categories=["OST_Doors"])
    mark, fire = _cell(res, "OST_Doors", "Mark"), _cell(res, "OST_Doors", "FireRating")
    assert (mark["filled"], mark["total"], mark["percent"]) == (3, 4, 75.0)  # blank text is not a value
    assert (fire["filled"], fire["total"]) == (2, 4)  # "" and a missing parameter both count as empty
    assert res["read_only"] is True and res["partial"] is False and res["categories"] == ["OST_Doors"]


def test_zero_and_false_are_values():
    assert pc.is_filled(0) and pc.is_filled("0") and pc.is_filled(False)
    assert not pc.is_filled(None) and not pc.is_filled("") and not pc.is_filled("   ")


def test_top_n_most_common_per_category(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", top_n=1, categories=["OST_Doors"])
    assert [r["parameter"] for r in res["rows"]] == ["Mark"]  # carried by 4 doors; FireRating by 3
    res = _run(ws, snapshot_id="s1", top_n=5, categories=["OST_Doors"])
    assert [r["parameter"] for r in res["rows"]] == ["Mark", "FireRating"]


def test_by_level_uses_level_names(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", parameters=["Mark"], categories=["OST_Doors"], by_level=True)
    assert _cell(res, "OST_Doors", "Mark", "Level 1")["total"] == 3
    assert _cell(res, "OST_Doors", "Mark", "Level 2")["total"] == 1
    assert _cell(res, "OST_Doors", "Mark", "Level 2")["filled"] == 0


def test_partial_snapshot_is_labelled(ws):
    _snap(ws, counts={"truncated": True, "captured": 8, "candidates": 20})
    res = _run(ws, snapshot_id="s1", parameters=["Mark"])
    assert res["partial"] is True
    assert any("partial" in n.lower() for n in res["notes"])
    assert any(c["item"] == "Truncated" for c in res["coverage"])
    out = _run(ws, snapshot_id="s1", parameters=["Mark"], html_filename="h.html")
    assert "Partial capture" in Path(out["html_file"]).read_text(encoding="utf-8")


def test_category_filtered_snapshot_is_partial(ws):
    _snap(ws, counts={"categories": ["OST_Doors"]})
    assert _run(ws, snapshot_id="s1")["partial"] is True


def test_csv_and_html_files(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", parameters=["Mark"], by_level=True, csv_filename="out/c.csv", html_filename="out/h.html")
    rows = list(csv.reader(Path(res["csv_file"]).open(encoding="utf-8")))
    assert rows[0] == ["category", "parameter", "level", "filled", "total", "percent"]
    assert len(rows) == 1 + res["row_total"]
    text = Path(res["html_file"]).read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "<script" not in text and "http" not in text.split("</style>")[1]
    assert "Level 1" in text and "OST_Doors" in text


def test_html_escapes_model_text(ws):
    _snap(ws, elements=[{"uid": "a", "category": "<img src=x>", "params": {"<b>P</b>": {"v": "1"}}}])
    res = _run(ws, snapshot_id="s1", html_filename="h.html")
    text = Path(res["html_file"]).read_text(encoding="utf-8")
    assert "<img" not in text and "&lt;img src=x&gt;" in text and "<b>P</b>" not in text


def test_csv_neutralises_formulas(ws):
    _snap(ws, elements=[{"uid": "a", "category": "=cmd", "params": {"+P": {"v": "1"}}}])
    res = _run(ws, snapshot_id="s1", csv_filename="c.csv")
    assert "'=cmd,'+P" in Path(res["csv_file"]).read_text(encoding="utf-8")


def test_max_rows_caps_result_not_files(ws):
    _snap(ws)
    res = _run(ws, snapshot_id="s1", parameters=["Mark", "FireRating"], max_rows=2, csv_filename="c.csv")
    assert res["rows_shown"] == 2 and res["row_total"] > 2
    assert len(list(csv.reader(Path(res["csv_file"]).open(encoding="utf-8")))) == 1 + res["row_total"]


@pytest.mark.parametrize("name", ["../x.csv", "x.txt", "/etc/passwd.csv"])
def test_output_paths_are_sandboxed(ws, name):
    _snap(ws)
    with pytest.raises(ValueError):
        _run(ws, snapshot_id="s1", csv_filename=name)


def test_hostile_snapshot_id_refused(ws):
    with pytest.raises(ValueError, match="plain snapshot name"):
        _run(ws, snapshot_id="../secret")


def test_bridge_mode_needs_snapshot(ws, monkeypatch):
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
    from revit_mcp_server.tool_metadata import DESCRIPTIONS

    manifest = json.loads((Path(pc.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert all(not c["is_mutating"] for c in manifest["commands"])
    assert DESCRIPTIONS["param_completeness_heatmap"].endswith("Read-only.")
