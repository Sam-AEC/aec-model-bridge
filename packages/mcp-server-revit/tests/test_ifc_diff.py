"""Tests for the ifc_diff module: GlobalId diff between two tiny inline IFC files."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.ifc_diff import module as mod
from revit_mcp_server.modules.ifc_diff.module import IfcDiffModule
from revit_mcp_server.security.workspace import WorkspaceMonitor

WALL_A = "1a2B3c4D5e6F7g8H9i0J1k"
WALL_B = "2a2B3c4D5e6F7g8H9i0J1k"
WALL_C = "3a2B3c4D5e6F7g8H9i0J1k"
DOOR_A = "4a2B3c4D5e6F7g8H9i0J1k"
WALL_D = "5a2B3c4D5e6F7g8H9i0J1k"

HEAD = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition[DesignTransferView]'),'2;1');
FILE_NAME('t.ifc','2026-11-24T20:04:05+00:00',(''),(''),'x','x','x');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0mdBLkBf99OOc4SMy9vGfy',$,'Tiny',$,$,$,$,$,$);
"""
TAIL = "ENDSEC;\nEND-ISO-10303-21;\n"


def ifc(entities, pset=None):
    """entities: list of (class, guid, name). pset: (wall guid, rating) adds a Pset_WallCommon."""
    lines = [HEAD]
    n = 10
    for cls, guid, name in entities:
        extra = ",$" * (4 if cls == "IFCDOOR" else 0)
        lines.append(f"#{n}={cls}('{guid}',$,'{name}',$,$,$,$,$,${extra});\n")
        n += 1
    if pset:
        guid, rating = pset
        target = next(10 + i for i, (_, g, _) in enumerate(entities) if g == guid)
        lines.append("#90=IFCPROPERTYSET('0iTvm81C1EfwqLKcxlYE9j',$,'Pset_WallCommon',$,(#92));\n")
        lines.append(f"#91=IFCRELDEFINESBYPROPERTIES('1CgwfE2pfBR9M8r5KPDFC5',$,$,$,(#{target}),#90);\n")
        lines.append(f"#92=IFCPROPERTYSINGLEVALUE('FireRating',$,IFCLABEL('{rating}'),$);\n")
    lines.append(TAIL)
    return "".join(lines)


OLD = ifc(
    [("IFCWALL", WALL_A, "Wall A"), ("IFCWALL", WALL_B, "Wall B"), ("IFCWALL", WALL_C, "Wall C"),
     ("IFCDOOR", DOOR_A, "Door A")],
    pset=(WALL_A, "EI60"),
)
NEW = ifc(
    [("IFCWALL", WALL_A, "Wall A"), ("IFCWALL", WALL_B, "Wall B renamed"), ("IFCWALL", WALL_D, "Wall D"),
     ("IFCDOOR", DOOR_A, "Door A")],
    pset=(WALL_A, "EI90"),
)


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "old.ifc").write_text(OLD, encoding="utf-8")
    (tmp_path / "new.ifc").write_text(NEW, encoding="utf-8")
    return SimpleNamespace(allowed_directories=[tmp_path])


def run(ws, **kw):
    kw.setdefault("older_ifc_path", "old.ifc")
    kw.setdefault("newer_ifc_path", "new.ifc")
    return IfcDiffModule().compare(workspace=ws, **kw)


def test_added_removed_changed(ws):
    res = run(ws)
    assert res["read_only"] is True
    assert [e["global_id"] for e in res["added"]] == [WALL_D]
    assert [e["global_id"] for e in res["removed"]] == [WALL_C]
    changed = {e["global_id"]: e for e in res["changed"]}
    assert set(changed) == {WALL_A, WALL_B}
    assert changed[WALL_B]["changes"]["name"] == {"old": "Wall B", "new": "Wall B renamed"}
    pset = changed[WALL_A]["changes"]["property_sets"]
    assert pset["changed"] == ["Pset_WallCommon"] and pset["added"] == [] and pset["removed"] == []
    assert pset["old_hash"] != pset["new_hash"]
    assert res["counts"] == {
        "older_elements": 4, "newer_elements": 4, "added": 1, "removed": 1, "changed": 2, "unchanged": 1,
    }
    assert res["removed"][0]["name"] == "Wall C" and res["added"][0]["class"] == "IfcWall"


def test_identical_files_have_no_differences(ws):
    (Path(ws.allowed_directories[0]) / "copy.ifc").write_text(OLD, encoding="utf-8")
    res = run(ws, newer_ifc_path="copy.ifc")
    assert (res["added"], res["removed"], res["changed"]) == ([], [], [])
    assert res["counts"]["unchanged"] == 4


def test_class_change_is_reported(ws):
    root = Path(ws.allowed_directories[0])
    (root / "new.ifc").write_text(ifc([("IFCSLAB", WALL_A, "Wall A")], pset=(WALL_A, "EI60")), encoding="utf-8")
    (root / "old.ifc").write_text(ifc([("IFCWALL", WALL_A, "Wall A")], pset=(WALL_A, "EI60")), encoding="utf-8")
    res = run(ws)
    assert res["changed"][0]["changes"]["class"] == {"old": "IfcWall", "new": "IfcSlab"}
    assert "property_sets" not in res["changed"][0]["changes"]


def test_class_filter(ws):
    res = run(ws, ifc_class="IfcDoor")
    assert res["ifc_class"] == "IfcDoor"
    assert res["counts"]["older_elements"] == 1 and res["counts"]["added"] == 0
    assert res["removed"] == [] and res["changed"] == []


def test_unknown_class_is_refused(ws):
    with pytest.raises(ValueError, match="not an IFC class"):
        run(ws, ifc_class="IfcNotAThing")


def test_lists_are_capped_with_complete_counts(ws):
    root = Path(ws.allowed_directories[0])
    many = [("IFCWALL", f"{i:03d}a2B3c4D5e6F7g8H9i0J1k"[:22], f"W{i}") for i in range(12)]
    (root / "old.ifc").write_text(ifc([many[0]]), encoding="utf-8")
    (root / "new.ifc").write_text(ifc(many), encoding="utf-8")
    res = run(ws, max_items=3)
    assert res["counts"]["added"] == 11 and len(res["added"]) == 3
    assert any("cut at 3" in n for n in res["notes"])


def test_duplicate_global_ids_are_counted(ws):
    root = Path(ws.allowed_directories[0])
    (root / "new.ifc").write_text(
        ifc([("IFCWALL", WALL_A, "Wall A"), ("IFCWALL", WALL_A, "Wall A copy")]), encoding="utf-8")
    res = run(ws)
    assert res["duplicate_global_ids"] == {"older": 0, "newer": 1}
    assert any("more than once" in n for n in res["notes"])


@pytest.mark.parametrize("kw,match", [
    ({"older_ifc_path": ""}, "required"),
    ({"newer_ifc_path": None}, "required"),
    ({"older_ifc_path": "missing.ifc"}, "not found"),
    ({"older_ifc_path": "notes.txt"}, r"must be a \.ifc"),
    ({"max_items": "many"}, "whole number"),
])
def test_bad_input_is_refused(ws, kw, match):
    (Path(ws.allowed_directories[0]) / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        run(ws, **kw)


def test_file_that_is_not_step_is_refused(ws):
    (Path(ws.allowed_directories[0]) / "fake.ifc").write_text("<html>not ifc</html>", encoding="utf-8")
    with pytest.raises(ValueError, match="not an IFC STEP file"):
        run(ws, older_ifc_path="fake.ifc")


def test_broken_ifc_is_refused(ws):
    (Path(ws.allowed_directories[0]) / "broken.ifc").write_text(
        "ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=IFCWALL(\n", encoding="utf-8")
    with pytest.raises(ValueError, match="could not be read"):
        run(ws, older_ifc_path="broken.ifc")


def test_oversized_file_is_refused(ws, monkeypatch):
    monkeypatch.setattr(mod, "MAX_IFC_BYTES", 10)
    with pytest.raises(ValueError, match="larger than"):
        run(ws)


def test_file_outside_workspace_is_refused(tmp_path):
    inside = tmp_path / "ws"
    inside.mkdir()
    (inside / "old.ifc").write_text(OLD, encoding="utf-8")
    outside = tmp_path / "outside.ifc"
    outside.write_text(NEW, encoding="utf-8")
    for monitor in (WorkspaceMonitor([inside]), SimpleNamespace(allowed_directories=[inside])):
        with pytest.raises(Exception, match="outside the allowed workspace"):
            IfcDiffModule().compare(older_ifc_path="old.ifc", newer_ifc_path=str(outside), workspace=monitor)
        with pytest.raises(Exception, match="outside the allowed workspace"):
            IfcDiffModule().compare(older_ifc_path="old.ifc", newer_ifc_path="../outside.ifc", workspace=monitor)


def test_result_is_json_serialisable(ws):
    json.dumps(run(ws))


def test_module_manifest_is_read_only():
    manifest = json.loads((Path(mod.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert [(c["id"], c["is_mutating"]) for c in manifest["commands"]] == [("compare", False), ("compare_snapshot", False)]


def _ifc_with_complex_property(ids):
    p, r, c, v = ids
    return (
        HEAD
        + f"#10=IFCWALL('{WALL_A}',$,'Wall A',$,$,$,$,$,$);\n"
        + f"#{p}=IFCPROPERTYSET('0iTvm81C1EfwqLKcxlYE9j',$,'Pset_Custom',$,(#{c}));\n"
        + f"#{r}=IFCRELDEFINESBYPROPERTIES('1CgwfE2pfBR9M8r5KPDFC5',$,$,$,(#10),#{p});\n"
        + f"#{c}=IFCCOMPLEXPROPERTY('Group',$,'U',(#{v}));\n"
        + f"#{v}=IFCPROPERTYSINGLEVALUE('A',$,IFCLABEL('x'),$);\n"
        + TAIL
    )


def test_same_nested_property_with_other_step_ids_is_not_a_change(ws):
    root = Path(ws.allowed_directories[0])
    (root / "old.ifc").write_text(_ifc_with_complex_property((90, 91, 92, 93)), encoding="utf-8")
    (root / "new.ifc").write_text(_ifc_with_complex_property((190, 191, 192, 193)), encoding="utf-8")
    assert run(ws)["counts"]["changed"] == 0


def test_entity_values_compare_by_content_not_step_id(ws, monkeypatch):
    import ifcopenshell
    import ifcopenshell.util.element as el_util

    model = ifcopenshell.file(schema="IFC4")
    first = model.createIfcOrganization(None, "Acme")
    model.createIfcProject(ifcopenshell.guid.new(), Name="padding")  # shifts the next STEP id
    second = model.createIfcOrganization(None, "Acme")
    other = model.createIfcOrganization(None, "Other")
    assert first.id() != second.id()

    def psets_for(entity):
        monkeypatch.setattr(el_util, "get_psets", lambda _el: {"P": {"id": 1, "Maker": entity}})
        return mod._psets(object())

    a, b, c = psets_for(first), psets_for(second), psets_for(other)
    assert a == b and mod._digest(a) == mod._digest(b)
    assert a != c and mod._digest(a) != mod._digest(c)
    assert "#" not in json.dumps(a)
