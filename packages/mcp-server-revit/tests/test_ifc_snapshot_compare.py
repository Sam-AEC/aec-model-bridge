"""Tests for ifc_diff.compare_snapshot: a delivered IFC against a saved snapshot, matched by GlobalId."""
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.ifc_diff.module import IfcDiffModule

ifcopenshell_guid = pytest.importorskip("ifcopenshell.guid")

HEAD = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');
FILE_NAME('t.ifc','2026-11-24T20:04:05+00:00',(''),(''),'x','x','x');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0mdBLkBf99OOc4SMy9vGfy',$,'Tiny',$,$,$,$,$,$);
"""


def ifc(entities):
    lines = [HEAD]
    for n, (cls, guid, name) in enumerate(entities, start=10):
        extra = ",$" * (4 if cls == "IFCDOOR" else 0)
        lines.append(f"#{n}={cls}('{guid}',$,'{name}',$,$,$,$,$,${extra});\n")
    lines.append("ENDSEC;\nEND-ISO-10303-21;\n")
    return "".join(lines)


EPISODE = "c0326e0e-473d-4952-b8ec-f23696541f40"


def revit_uid(element_id):
    return f"{EPISODE}-{element_id:08x}"


def derived_guid(element_id):
    raw = bytearray(uuid.UUID(EPISODE).bytes)
    for i, b in enumerate(element_id.to_bytes(4, "big")):
        raw[12 + i] ^= b
    return ifcopenshell_guid.compress(bytes(raw).hex())


G_WALL_1 = derived_guid(0x100)  # matched by UniqueId
G_WALL_2 = derived_guid(0x101)  # in snapshot only
G_DOOR = "4a2B3c4D5e6F7g8H9i0J1k"  # matched by an IfcGUID parameter
G_EXTRA = "5a2B3c4D5e6F7g8H9i0J1k"  # in IFC only


def element(uid, category, name, **params):
    return {
        "uid": uid, "element_id": 1, "category": category, "class": "X", "name": name,
        "params": {k: {"v": v, "storage": "String"} for k, v in params.items()},
    }


SNAPSHOT = {
    "snapshot_id": "snap1",
    "elements": [
        element(revit_uid(0x100), "OST_Walls", "Wall 1"),
        element(revit_uid(0x101), "OST_Walls", "Wall 2"),
        element("door-uid-not-hex", "OST_Doors", "Door 1", IfcGUID=G_DOOR),
        element("room-uid-not-hex", "OST_Rooms", "Room 1"),
    ],
}

IFC_TEXT = ifc([
    ("IFCWALL", G_WALL_1, "Wall 1"),
    ("IFCDOOR", G_DOOR, "Door 1"),
    ("IFCWALL", G_EXTRA, "Extra wall"),
])


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "snap1.json").write_text(json.dumps(SNAPSHOT), encoding="utf-8")
    (tmp_path / "delivered.ifc").write_text(IFC_TEXT, encoding="utf-8")
    return SimpleNamespace(allowed_directories=[tmp_path])


def run(ws, **kw):
    kw.setdefault("snapshot_id", "snap1")
    kw.setdefault("ifc_path", "delivered.ifc")
    return IfcDiffModule().compare_snapshot(workspace=ws, **kw)


def test_missing_extra_matched_and_unmatched(ws):
    res = run(ws)
    assert res["read_only"] is True
    assert sorted(e["global_id"] for e in res["matched"]) == sorted([G_WALL_1, G_DOOR])
    assert [e["global_id"] for e in res["missing_from_ifc"]] == [G_WALL_2]
    assert [e["global_id"] for e in res["extra_in_ifc"]] == [G_EXTRA]
    assert [e["uid"] for e in res["unmatched_no_guid"]] == ["room-uid-not-hex"]
    assert res["counts"] == {
        "snapshot_elements": 4, "ifc_elements": 3, "matched": 2,
        "missing_from_ifc": 1, "extra_in_ifc": 1, "unmatched_no_guid": 1, "unmatched_duplicate_guid": 0,
    }


def test_by_category_and_guid_sources(ws):
    res = run(ws)
    assert res["by_category"] == {
        "OST_Walls": {"matched": 1, "missing_from_ifc": 1, "unmatched_no_guid": 0, "unmatched_duplicate_guid": 0},
        "OST_Doors": {"matched": 1, "missing_from_ifc": 0, "unmatched_no_guid": 0, "unmatched_duplicate_guid": 0},
        "OST_Rooms": {"matched": 0, "missing_from_ifc": 0, "unmatched_no_guid": 1, "unmatched_duplicate_guid": 0},
    }
    assert res["extra_by_ifc_class"] == {"IfcWall": 1}
    assert res["guid_sources"] == {"IfcGUID parameter": 1, "derived from UniqueId": 2, "none": 1}


def test_category_filter_limits_the_snapshot_side(ws):
    res = run(ws, categories=["OST_Walls"])
    assert res["counts"]["snapshot_elements"] == 2
    assert [e["global_id"] for e in res["missing_from_ifc"]] == [G_WALL_2]
    assert res["unmatched_no_guid"] == []


def test_ifc_class_filter_limits_the_ifc_side(ws):
    res = run(ws, ifc_class="IfcDoor")
    assert res["counts"]["ifc_elements"] == 1 and res["extra_in_ifc"] == []


def test_snapshot_without_guid_data_says_so(ws):
    snap = {"snapshot_id": "snap1", "elements": [element("a-b", "OST_Walls", "W")]}
    (Path(ws.allowed_directories[0]) / "snapshots" / "snap1.json").write_text(json.dumps(snap), encoding="utf-8")
    res = run(ws)
    assert res["counts"]["matched"] == 0 and res["counts"]["unmatched_no_guid"] == 1
    assert any("IfcGUID" in n for n in res["notes"])


def test_duplicate_guid_is_unmatched_not_dropped(ws):
    snap = {"snapshot_id": "snap1", "elements": [
        element("u1", "OST_Walls", "A", IfcGUID=G_DOOR), element("u2", "OST_Walls", "B", IfcGUID=G_DOOR)]}
    (Path(ws.allowed_directories[0]) / "snapshots" / "snap1.json").write_text(json.dumps(snap), encoding="utf-8")
    res = run(ws)
    assert res["counts"]["matched"] == 1
    assert res["unmatched_no_guid"] == []
    assert [e["uid"] for e in res["unmatched_duplicate_guid"]] == ["u2"]
    assert res["unmatched_duplicate_guid"][0]["reason"] == "duplicate GUID"
    assert res["counts"]["unmatched_no_guid"] == 0 and res["counts"]["unmatched_duplicate_guid"] == 1
    assert res["by_category"]["OST_Walls"]["unmatched_duplicate_guid"] == 1
    assert res["by_category"]["OST_Walls"]["unmatched_no_guid"] == 0


def test_missing_guid_library_is_reported_not_silent(ws, monkeypatch):
    monkeypatch.setitem(sys.modules, "ifcopenshell.guid", None)
    res = run(ws)
    assert res["guid_sources"]["derived from UniqueId"] == 0
    assert res["counts"]["unmatched_no_guid"] == 3
    assert all("ifcopenshell.guid is not available" in e["reason"] for e in res["unmatched_no_guid"])
    assert any("ifcopenshell.guid is not available" in n for n in res["notes"])


def test_guid_library_present_adds_no_such_note(ws):
    assert not any("ifcopenshell.guid is not available" in n for n in run(ws)["notes"])


def test_lists_are_capped_with_complete_counts(ws):
    res = run(ws, max_items=1)
    assert res["counts"]["matched"] == 2 and len(res["matched"]) == 1
    assert any("cut at 1" in n for n in res["notes"])


@pytest.mark.parametrize("snapshot_id", ["../snap1", "snap1.json", "a/b", "", None])
def test_snapshot_id_is_a_plain_name(ws, snapshot_id):
    with pytest.raises(ValueError, match="snapshot_id"):
        run(ws, snapshot_id=snapshot_id)


def test_missing_snapshot_is_refused(ws):
    with pytest.raises(ValueError, match="not found"):
        run(ws, snapshot_id="nope")


def test_ifc_outside_workspace_is_refused(ws, tmp_path):
    with pytest.raises(Exception, match="outside the allowed workspace"):
        run(ws, ifc_path="../elsewhere.ifc")


def test_manifest_command_is_read_only():
    from revit_mcp_server.modules.ifc_diff import module as mod

    manifest = json.loads((Path(mod.__file__).parent / "module.json").read_text(encoding="utf-8"))
    cmd = {c["id"]: c for c in manifest["commands"]}["compare_snapshot"]
    assert cmd["is_mutating"] is False
    assert set(cmd["input_schema"]["required"]) == {"snapshot_id", "ifc_path"}


def test_result_is_json_serialisable(ws):
    json.dumps(run(ws))
