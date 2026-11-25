"""Optional snapshot blocks (issue 146): types, cad and rooms behind `include`.

The snapshots here are built by hand to the shape the add-in writes. The add-in half (C#) is
UNVERIFIED in live Revit; these tests guard the server side and the two audits that read the keys.
"""
import asyncio
import json

import pytest

from revit_mcp_server.modules.model_bloat.module import ModelBloatModule
from revit_mcp_server.modules.schedule_consistency.module import ScheduleConsistencyModule
from revit_mcp_server.providers.revit import _snapshot_payload as revit_payload
from revit_mcp_server.providers.semantic_provider import SemanticProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.semantic import engine
from revit_mcp_server.semantic.models import Snapshot


class WS:
    def __init__(self, tmp_path):
        self.allowed_directories = [tmp_path]


def _write(tmp_path, data, sid="s1"):
    d = tmp_path / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")
    return sid


def _type(uid, family, name, count=None, source="loadable"):
    t = {"uid": uid, "category": "OST_Furniture", "family": family, "type_name": name,
         "family_source": source, "params": {}}
    if count is not None:
        t["instance_count"] = count
    return t


def _inst(i, family, name, type_uid):
    return {"uid": f"e{i}", "element_id": i, "category": "OST_Furniture", "class": "FamilyInstance",
            "family": family, "type_name": name, "type_uid": type_uid, "params": {}}


# --- model_bloat ----------------------------------------------------------------------------

def _old_snapshot():
    """What a default add-in snapshot carries: elements only, no types, no CAD keys."""
    return {"schema": "amb.snapshot/1", "snapshot_id": "s1", "elements": [_inst(1, "Chair", "Std", "10")],
            "counts": {"truncated": False, "categories": [], "dirty_only": False}}


def test_old_snapshot_without_new_keys_is_still_not_rated(tmp_path):
    sid = _write(tmp_path, _old_snapshot())
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert r["cleanliness"]["score"] is None and r["cleanliness"]["label"] == "not rated"
    assert r["checks"]["imported_cad"]["status"] == "not_enough_data"
    assert r["checks"]["unused_families_and_types"]["status"] == "not_enough_data"
    assert "not rated" in r["summary"]


def test_snapshot_with_types_and_cad_is_rated_and_lists_unused_types(tmp_path):
    data = _old_snapshot()
    data["types"] = [_type("10", "Chair", "Std", 1), _type("11", "Chair", "Spare", 0),
                     _type("20", "OldTable", "A", 0)]
    data["cad_scanned"] = True
    data["cad"] = []
    data["counts"]["include"] = ["types", "cad"]
    sid = _write(tmp_path, data)
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert isinstance(r["cleanliness"]["score"], int)
    assert all(c["status"] == "ran" for c in r["checks"].values())
    assert [f["family"] for f in r["unused_families"]["items"]] == ["OldTable"]
    assert [(t["family"], t["type_name"]) for t in r["unused_types"]["items"]] == [("Chair", "Spare")]
    assert r["imported_cad"]["total"] == 0
    assert "instance count the add-in read" in " ".join(r["notes"])


def test_instance_counts_are_used_even_when_elements_are_a_partial_capture(tmp_path):
    # Only some elements were captured (categories filter), but the add-in counted the whole model.
    data = {"elements": [], "types": [_type("10", "Chair", "Std", 40), _type("11", "Chair", "Spare", 0)],
            "cad_scanned": True, "counts": {"categories": ["OST_Doors"], "include": ["types", "cad"]}}
    sid = _write(tmp_path, data)
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert r["usage_counts_available"] is True
    assert [(t["family"], t["type_name"]) for t in r["unused_types"]["items"]] == [("Chair", "Spare")]


def test_types_without_counts_keep_the_element_based_rule(tmp_path):
    # One type has no instance_count: counts are not trusted and a partial capture proves nothing.
    data = {"elements": [_inst(1, "Chair", "Std", "10")],
            "types": [_type("10", "Chair", "Std", 1), _type("11", "Chair", "Spare")],
            "cad_scanned": True, "counts": {"categories": ["OST_Furniture"]}}
    sid = _write(tmp_path, data)
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert r["usage_counts_available"] is False
    assert r["checks"]["unused_families_and_types"]["status"] == "not_enough_data"


def test_cad_records_are_listed_and_a_link_is_not_an_import(tmp_path):
    data = {"elements": [], "types": [_type("10", "Chair", "Std", 1)], "cad_scanned": True,
            "cad": [{"element_id": 5, "name": "site.dwg", "is_link": False, "view_specific": False},
                    {"element_id": 6, "name": "xref.dwg", "is_link": True, "view_specific": False},
                    {"element_id": 7, "name": "detail.dwg", "is_link": False, "view_specific": True}],
            "counts": {}}
    sid = _write(tmp_path, data)
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    kinds = {c["name"]: c["kind"] for c in r["imported_cad"]["items"]}
    assert kinds == {"site.dwg": "imported", "detail.dwg": "imported", "xref.dwg": "linked"}


def test_cad_records_are_not_double_counted_with_element_records(tmp_path):
    el = {"uid": "c5", "element_id": 5, "category": "OST_ImportObjectStyles", "class": "ImportInstance",
          "type_name": "site.dwg", "params": {}}
    data = {"elements": [el], "types": [_type("10", "Chair", "Std", 1)], "cad_scanned": True,
            "cad": [{"element_id": 5, "name": "site.dwg", "is_link": False, "view_specific": False}], "counts": {}}
    sid = _write(tmp_path, data)
    r = ModelBloatModule().audit(snapshot_id=sid, workspace=WS(tmp_path))
    assert r["imported_cad"]["total"] == 1


def test_cad_scanned_with_no_records_trusts_none_found_but_old_files_do_not(tmp_path):
    scanned = {"elements": [], "types": [_type("10", "Chair", "Std", 1)], "cad_scanned": True, "cad": []}
    unscanned = {"elements": [], "types": [_type("10", "Chair", "Std", 1)]}
    a = ModelBloatModule().audit(snapshot_id=_write(tmp_path, scanned, "a"), workspace=WS(tmp_path))
    b = ModelBloatModule().audit(snapshot_id=_write(tmp_path, unscanned, "b"), workspace=WS(tmp_path))
    assert a["checks"]["imported_cad"]["status"] == "ran"
    assert b["checks"]["imported_cad"]["status"] == "not_enough_data"


# --- schedule_consistency -------------------------------------------------------------------

def _door(i, mark, frm=None, to=None):
    params = {"Mark": {"v": mark}}
    if frm is not False:
        params["From Room"] = {"v": frm, "storage": "String", "instance": True, "readonly": True}
        params["To Room"] = {"v": to, "storage": "String", "instance": True, "readonly": True}
    return {"uid": f"d{i}", "element_id": i, "category": "OST_Doors", "type_name": "Door", "params": params}


def _room(i, number, with_place=True):
    rec = {"uid": f"r{i}", "element_id": 1000 + i, "category": "OST_Rooms", "type_name": f"Room {i}",
           "params": {"Number": {"v": number}, "Area": {"v": 12.5}}}
    if with_place:
        rec["level_uid"] = "30"
        rec["location"] = {"kind": "point", "xyz": [1.0, 2.0, 0.0], "rotation": 0.0}
    return rec


def _schedule(tmp_path, elements, **counts):
    sid = _write(tmp_path, {"elements": elements, "counts": counts})
    return ScheduleConsistencyModule().check_doors_and_rooms(snapshot_id=sid, workspace=WS(tmp_path))


def test_old_snapshot_without_room_keys_is_incomplete(tmp_path):
    els = [_door(1, "D1", False), _room(1, "101", with_place=False), _room(2, "102", with_place=False)]
    res = _schedule(tmp_path, els)
    assert res["complete"] is False
    skipped = {s["check_id"] for s in res["skipped"]}
    assert {"door_missing_room", "door_same_room", "door_in_unnumbered_room"} <= skipped
    assert "NOT run" in res["summary"]


def test_snapshot_with_room_keys_level_and_location_is_complete(tmp_path):
    els = [_door(1, "D1", "r1", "r2"), _door(2, "D2", "r2", ""), _room(1, "101"), _room(2, "102")]
    res = _schedule(tmp_path, els, include=["rooms"])
    assert res["complete"] is True
    assert [s["check_id"] for s in res["skipped"]] == ["door_mark_pattern_mismatch"]
    # The door with an empty To Room is a real finding, not a skipped check.
    assert res["counts"]["door_missing_room"] == 1
    assert "d2" in res["findings"][0]["unique_ids"]


def test_zero_area_room_placement_is_known_with_level_and_location(tmp_path):
    zero = _room(3, "103")
    zero["params"]["Area"] = {"v": 0.0}
    res = _schedule(tmp_path, [_door(1, "D1", "r1", "r2"), _room(1, "101"), _room(2, "102"), zero])
    group = next(f for f in res["findings"] if f["check_id"] == "room_zero_area")
    assert group["affected"][0]["placed"] is True
    assert not any(s["check_id"] == "room_placement_status" for s in res["skipped"])


def test_door_with_only_one_room_key_is_still_incomplete(tmp_path):
    d = _door(1, "D1", "r1", "r2")
    del d["params"]["To Room"]
    res = _schedule(tmp_path, [d, _room(1, "101"), _room(2, "102")])
    assert res["complete"] is False


# --- server options ---------------------------------------------------------------------------

def test_validate_include_accepts_known_blocks_and_refuses_the_rest():
    assert engine.validate_snapshot_include(None) is None
    assert engine.validate_snapshot_include([]) is None
    assert engine.validate_snapshot_include([" Types ", "cad", "types"]) == ["types", "cad"]
    with pytest.raises(ValueError, match="unknown block 'views'"):
        engine.validate_snapshot_include(["views"])
    with pytest.raises(ValueError, match="list of block names"):
        engine.validate_snapshot_include("types")
    with pytest.raises(ValueError, match="list of block names"):
        engine.validate_snapshot_include([1])


def test_default_payload_is_unchanged_and_include_is_forwarded():
    assert engine._snapshot_payload({}) == {}
    assert engine._snapshot_payload({"include": ["types", "rooms"]}) == {"include": ["types", "rooms"]}
    assert revit_payload({}) == {"dirty_only": False}
    assert revit_payload({"include": ["cad"]}) == {"dirty_only": False, "include": ["cad"]}


def test_snapshot_take_schema_lists_include(tmp_path):
    provider = SemanticProvider(WorkspaceMonitor([tmp_path]), None)
    tool = next(t for t in provider._capabilities if t.name == "snapshot_take")
    assert tool.input_schema["properties"]["include"]["items"]["enum"] == ["types", "cad", "rooms"]


class FileAddin:
    """Writes the snapshot file the way the add-in does and returns its path."""

    def __init__(self, folder, extra):
        self.dir = folder / "addin"
        self.dir.mkdir(exist_ok=True)
        self.extra = extra
        self.calls = []

    async def execute_tool(self, name, payload):
        self.calls.append(dict(payload))
        data = {"schema": "amb.snapshot/1", "snapshot_id": "live1", "taken_at": "2026-11-25T10:00:00Z",
                "source": {"app": "revit", "doc_guid": "g", "doc_title": "M.rvt", "units": "SI"},
                "elements": [], "views": None, "sheets": None, "dirty_only": False,
                "counts": {"candidates": 0, "captured": 0, "truncated": False, "dirty_only": False,
                           "categories": [], "tracker": {"epoch": "e", "seq": 1}}, "deleted": []}
        if "include" in payload:
            data.update(self.extra)
            data["counts"]["include"] = list(payload["include"])
        path = self.dir / "live1.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return {"snapshot_id": "live1", "path": str(path)}


def test_include_reaches_the_add_in_and_new_keys_survive_saving(tmp_path):
    extra = {"types": [_type("10", "Chair", "Std", 2)], "cad_scanned": True, "cad": []}
    addin = FileAddin(tmp_path, extra)
    ws = WorkspaceMonitor([tmp_path])
    snap = asyncio.run(engine.snapshot_take(ws, addin, {"include": ["types", "cad"]}))
    assert addin.calls[0]["include"] == ["types", "cad"]
    assert snap.types[0].instance_count == 2
    saved = json.loads((tmp_path / "snapshots" / "live1.json").read_text(encoding="utf-8"))
    assert saved["cad_scanned"] is True and saved["types"][0]["instance_count"] == 2
    assert saved["schema"] == "amb.snapshot/1"
    r = ModelBloatModule().audit(snapshot_id="live1", workspace=ws)
    assert isinstance(r["cleanliness"]["score"], int)


def test_default_take_sends_no_include_and_writes_no_new_keys(tmp_path):
    addin = FileAddin(tmp_path, {"types": [_type("10", "Chair", "Std", 2)], "cad_scanned": True})
    ws = WorkspaceMonitor([tmp_path])
    asyncio.run(engine.snapshot_take(ws, addin, {}))
    assert "include" not in addin.calls[0]
    saved = json.loads((tmp_path / "snapshots" / "live1.json").read_text(encoding="utf-8"))
    assert "types" not in saved and "cad_scanned" not in saved
    assert Snapshot(**saved).types == []


def test_unknown_include_block_is_refused_before_revit_is_called(tmp_path):
    addin = FileAddin(tmp_path, {})
    with pytest.raises(ValueError, match="unknown block"):
        asyncio.run(engine.snapshot_take(WorkspaceMonitor([tmp_path]), addin, {"include": ["views"]}))
    assert addin.calls == []


# --- incremental and slices -------------------------------------------------------------------

def _base(include=None):
    counts = {"truncated": False, "tracker": {"epoch": "e", "seq": 1}, "categories": []}
    if include is not None:
        counts["include"] = include
    return {"schema": "amb.snapshot/1", "counts": counts}


def test_incremental_needs_a_base_with_the_same_optional_blocks():
    assert engine.incremental_base_problem(_base(), {}) is None
    assert engine.incremental_base_problem(_base(["types"]), {"include": ["types"]}) is None
    assert "optional blocks" in engine.incremental_base_problem(_base(), {"include": ["types"]})
    assert "optional blocks" in engine.incremental_base_problem(_base(["types"]), {})


def test_incremental_is_never_used_with_rooms():
    problem = engine.incremental_base_problem(_base(["rooms"]), {"include": ["rooms"]})
    assert problem and "full capture" in problem


def test_sliced_snapshot_keeps_blocks_written_by_the_first_part():
    first = {"schema": "amb.snapshot/1", "snapshot_id": "x", "elements": [], "views": [], "sheets": [],
             "types": [_type("10", "Chair", "Std", 1)], "cad_scanned": True, "cad": [],
             "counts": {"views_in_scope": True, "include": ["types", "cad"]}, "part": {"offset": 0}}
    second = {"schema": "amb.snapshot/1", "snapshot_id": "x", "elements": [_inst(1, "Chair", "Std", "10")],
              "counts": {}, "part": {"offset": 0}}
    data = engine.assemble_slices([first, second])
    assert data["cad_scanned"] is True and data["types"][0]["instance_count"] == 1
    assert data["counts"]["include"] == ["types", "cad"]
    assert len(data["elements"]) == 1
