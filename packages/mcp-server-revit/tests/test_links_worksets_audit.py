"""Tests for the links and worksets audit module (read-only; fixtures stand in for Revit)."""
import importlib.util
import json
from pathlib import Path

import pytest


def _load_mod():
    p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/links_worksets_audit/module.py"
    spec = importlib.util.spec_from_file_location("_lwa_impl", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_mod()
Audit = _mod.LinksWorksetsAuditModule


class WS:
    def __init__(self, tmp_path):
        self.allowed_directories = [tmp_path]


# Shapes match what BridgeCommandFactory.cs returns today.
LINKS = {"links": [
    {"name": "ARC.rvt", "id": 1, "is_loaded": True, "is_nested": False, "path": "RSN://srv/ARC.rvt"},
    {"name": "STR.rvt", "id": 2, "is_loaded": False, "is_nested": False, "path": "RSN://srv/STR.rvt"},
    {"name": "MEP.rvt", "id": 3, "is_loaded": True, "is_nested": False, "path": "Unknown"},
]}
INSTANCES = {"instances": [{"name": "ARC.rvt : 1", "id": 10, "type_id": 1, "link_name": "ARC.rvt"}]}
WORKSETS = {"is_workshared": True, "worksets": [
    {"name": "Shared Levels and Grids", "id": 1, "is_open": True},
    {"name": "Workset1", "id": 2, "is_open": True},
    {"name": "Spare", "id": 3, "is_open": False},
]}


def rules(result):
    return {(f["rule"], f["item"]) for f in result["findings"]}


def test_unloaded_and_missing_path_links():
    r = Audit().audit(links=LINKS, link_instances=INSTANCES, worksets=WORKSETS)
    assert ("link_unloaded", "STR.rvt") in rules(r)
    assert ("link_missing_path", "MEP.rvt") in rules(r)
    assert ("link_unloaded", "ARC.rvt") not in rules(r)
    missing = next(f for f in r["findings"] if f["rule"] == "link_missing_path")
    assert missing["severity"] == "error" and missing["next_step"]
    assert r["by_severity"]["error"] == 1


def test_default_workset_name_and_gaps_marked_unverified():
    r = Audit().audit(links=LINKS, link_instances=INSTANCES, worksets=WORKSETS)
    assert ("workset_default_name", "Workset1") in rules(r)
    gaps = " ".join(r["gaps"])
    assert "UNVERIFIED" in gaps and "pinned" in gaps and "checked out" in gaps
    assert "UNVERIFIED" in r["unverified"]
    assert r["source"] == "supplied_data"


def test_findings_sorted_errors_first():
    r = Audit().audit(links=LINKS, worksets=WORKSETS)
    sev = [f["severity"] for f in r["findings"]]
    order = {"error": 0, "warning": 1, "info": 2}
    assert sev == sorted(sev, key=order.get)


def test_pinned_and_origin_to_origin_when_addin_supplies_fields():
    links = {"links": [{"name": "ARC.rvt", "id": 1, "is_loaded": True, "path": "RSN://x"}]}
    inst = {"instances": [
        {"type_id": 1, "pinned": True, "positioning": "Auto - Origin to Origin"},
        {"type_id": 1, "pinned": False, "positioning": "Shared Coordinates"},
    ]}
    r = Audit().audit(links=links, link_instances=inst)
    assert ("link_not_pinned", "ARC.rvt") in rules(r)
    assert ("link_origin_to_origin", "ARC.rvt") in rules(r)
    assert not any("pinned state" in g for g in r["gaps"])
    r2 = Audit().audit(links=links, link_instances=inst, expect_shared_coordinates=False)
    assert ("link_origin_to_origin", "ARC.rvt") not in rules(r2)


def test_coordinates_mismatch_is_error():
    links = [{"name": "CAD", "id": 1, "path": "RSN://x", "shared_coordinates_match": False}]
    r = Audit().audit(links=links)
    f = next(f for f in r["findings"] if f["rule"] == "link_coordinates_mismatch")
    assert f["severity"] == "error"


def test_nested_link_without_path_is_not_missing():
    r = Audit().audit(links=[{"name": "N", "id": 1, "is_nested": True, "path": "Nested"}])
    assert not r["findings"]


def test_workset_owner_and_empty_from_supplied_fields():
    ws = [
        {"name": "Arch", "owner": "alice", "element_count": 5},
        {"name": "Mine", "owner": "Bob", "element_count": 5},
        {"name": "Unused", "element_count": 0},
    ]
    r = Audit().audit(worksets=ws, current_user="bob")
    assert ("workset_open_by_other_user", "Arch") in rules(r)
    assert ("workset_open_by_other_user", "Mine") not in rules(r)
    assert ("workset_empty", "Unused") in rules(r)
    assert not any("checked out" in g for g in r["gaps"])


def test_not_workshared_model():
    r = Audit().audit(worksets={"is_workshared": False, "worksets": []})
    assert [f["rule"] for f in r["findings"]] == ["not_workshared"]


def test_snapshot_gives_empty_worksets_and_wrong_workset(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    elements = [
        {"uid": "w1", "category": "Walls", "workset": "Workset1"},
        {"uid": "w2", "category": "Walls", "workset": "Shared Levels and Grids"},
        {"uid": "d1", "category": "Doors", "workset": "Shared Levels and Grids"},
    ]
    (snap_dir / "s1.json").write_text(json.dumps({"elements": elements}), encoding="utf-8")
    r = Audit().audit(
        snapshot_id="s1", worksets=WORKSETS, workspace=WS(tmp_path),
        category_workset_map={"Walls": "Architecture", "Doors": "Shared Levels and Grids", "Roofs": "Roof"},
    )
    assert ("workset_empty", "Spare") in rules(r)
    assert ("workset_empty", "Workset1") not in rules(r)
    wrong = [f for f in r["findings"] if f["rule"] == "wrong_workset"]
    assert len(wrong) == 1 and wrong[0]["item"] == "Walls" and wrong[0]["count"] == 2
    assert set(wrong[0]["sample_uids"]) == {"w1", "w2"}


def test_mapping_without_snapshot_is_noted():
    r = Audit().audit(worksets=WORKSETS, category_workset_map={"Walls": "Arch"})
    assert any("snapshot_id" in n for n in r["notes"])


def test_unknown_snapshot_raises(tmp_path):
    with pytest.raises(ValueError):
        Audit().audit(snapshot_id="nope", workspace=WS(tmp_path))


def test_reads_live_tools_via_executor_and_unwraps_result():
    calls = []

    def ex(tool, args):
        calls.append(tool)
        return {"result": {"rvt_links": 1, **{"revit_get_rvt_links": LINKS,
                                              "revit_get_link_instances": INSTANCES,
                                              "revit_get_worksets": WORKSETS}[tool]}}

    r = Audit().audit(tool_executor=ex)
    assert calls == ["revit_get_rvt_links", "revit_get_link_instances", "revit_get_worksets"]
    assert r["source"] == "live_revit"
    assert ("link_unloaded", "STR.rvt") in rules(r)


def test_executor_failure_is_reported_not_raised():
    def ex(tool, args):
        raise RuntimeError("Revit not connected")

    r = Audit().audit(tool_executor=ex)
    assert r["total_findings"] == 0
    assert any("Revit not connected" in n for n in r["notes"])


def test_manifest_is_read_only():
    p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/links_worksets_audit/module.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    assert m["id"] == "links_worksets_audit"
    assert all(c["is_mutating"] is False for c in m["commands"])
    assert m["permissions"] == ["model.read"]
