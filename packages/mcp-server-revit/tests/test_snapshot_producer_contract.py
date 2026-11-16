"""Producer-shaped records survive the typed reader and reach the QA consumers.

These fixtures exercise the serialization boundary, not a running Revit session.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.model_changes.module import ModelChangesModule, compare_snapshot_data
from revit_mcp_server.modules.naming_checker.module import _names_from_snapshot
from revit_mcp_server.semantic.models import Snapshot


def _element(uid, category, cls, **extra):
    return {"uid": uid, "element_id": 1, "category": category, "class": cls, **extra}


def _round_trip(elements, **extra):
    raw = {"schema": "amb.snapshot/1", "snapshot_id": "snapshot", "elements": elements, **extra}
    return json.loads(Snapshot(**raw).model_dump_json(by_alias=True))


def test_stable_names_survive_reader_and_reach_naming_checker():
    elements = [
        _element("sheet", "OST_Sheets", "ViewSheet", name="Plattegrond", sheet_number="A-101",
                 params={"Bladnummer": {"v": "A-101", "storage": "String"},
                         "SHEET_NUMBER": {"v": "A-101", "storage": "String"}}),
        _element("view", "OST_Views", "ViewDrafting", name="Detail 01"),
        _element("level", "OST_Levels", "Level", name="00 begane grond"),
        _element("grid", "OST_Grids", "Grid", name="A"),
    ]
    stored = _round_trip(elements)
    names, info = _names_from_snapshot(stored)
    assert names["sheet_numbers"] == ["A-101"]
    assert names["sheet_names"] == ["Plattegrond"]
    assert names["view_names"] == ["Detail 01"]
    assert names["level_names"] == ["00 begane grond"]
    assert names["grid_names"] == ["A"]
    assert not info["missing"] and not info["typed"]
    assert stored["elements"][0]["params"]["Bladnummer"]["v"] == "A-101"


@pytest.mark.parametrize("change", ["movement", "rotation"])
def test_point_locations_survive_reader_and_reach_change_comparison(change):
    point = {"kind": "point", "xyz": [0.3048, 0.6096, 0.9144], "rotation": 0.0}
    old = _round_trip([_element("door", "OST_Doors", "FamilyInstance", location=point)])
    updated = {**point, "xyz": [1.3048, 0.6096, 0.9144]} if change == "movement" else {**point, "rotation": 1.5708}
    new = _round_trip([_element("door", "OST_Doors", "FamilyInstance", location=updated)])
    result = compare_snapshot_data(old, new)
    assert result["totals"]["modified"] == 1
    assert result["modified"][0]["other_changes"] == ["location"]
    assert result["elements_compared_on_location"] == 1


def test_unsupported_curve_location_remains_uncovered():
    snap = _round_trip([_element("wall", "OST_Walls", "Wall", location=None)])
    result = compare_snapshot_data(snap, snap)
    assert result["elements_missing_location"] == 1
    assert result["not_enough_data"][0]["check"] == "location"


@pytest.mark.parametrize("metadata", [{"dirty_only": True}, {"counts": {"dirty_only": True}}])
def test_dirty_capture_survives_reader_and_is_refused_as_complete(tmp_path, metadata):
    partial = _round_trip([], **metadata)
    folder = tmp_path / "snapshots"
    folder.mkdir()
    for sid, data in (("old", _round_trip([_element("door", "OST_Doors", "FamilyInstance")])),
                      ("new", partial)):
        (folder / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="partial capture"):
        ModelChangesModule().compare_snapshots(
            "old", "new", workspace=SimpleNamespace(allowed_directories=[tmp_path]))


def test_producer_uses_si_point_locations_and_stable_metadata():
    """Guard the C# half of the boundary until an add-in harness can run Revit."""
    root = Path(__file__).resolve().parents[3]
    source = (root / "packages/revit-bridge-addin/src/Bridge/BridgeCommandFactory.cs").read_text(encoding="utf-8")
    point = source.split("private static object? GetSnapshotPointLocation(", 1)[1].split(
        "private static void AddSnapshotNameAliases(", 1)[0]
    assert point.count("UnitUtils.ConvertFromInternalUnits(") == 3
    assert point.count("UnitTypeId.Meters") == 3
    assert "rotation = point.Rotation" in point
    body = source.split("private static object ExecuteExtractSnapshot(", 1)[1]
    assert 'name = elem.Name' in body and 'sheet_number = (elem as ViewSheet)?.SheetNumber' in body
    assert 'level_uid = elem.LevelId != ElementId.InvalidElementId' in body
    assert 'location = GetSnapshotPointLocation(elem)' in body
    assert '["dirty_only"] = dirtyOnly' in body and 'dirty_only = dirtyOnly' in body
