"""Tests for the schedule_diff module (fixtures are synthetic saved snapshots)."""
import csv
import json
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.schedule_diff.module import ScheduleDiffModule, moved_keys


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _sheet(uid, number, name, **params):
    return {"uid": uid, "number": number, "name": name, "view_uids": [],
            "params": {k: {"v": v} for k, v in params.items()}}


def _sched(uid, name, rows, fields=("Mark", "Type"), **extra):
    return {"uid": uid, "name": name, "fields": list(fields), "rows": rows, **extra}


def _row(eid, *cells):
    return {"element_id": eid, "cells": list(cells)}


def _save(ws, sid, data):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")


def _run(ws, old, new, **kw):
    _save(ws, "old", old)
    _save(ws, "new", new)
    return ScheduleDiffModule().compare(older_snapshot_id="old", newer_snapshot_id="new", workspace=ws, **kw)


OLD_SHEETS = [_sheet("u1", "A-101", "Ground floor plan", **{"Current Revision": "P01"}),
              _sheet("u2", "A-102", "First floor plan"),
              _sheet("u3", "A-103", "Roof plan"),
              _sheet("u4", "A-104", "Sections")]


def test_sheet_added_removed_renamed_renumbered_and_revision(ws):
    new_sheets = [
        _sheet("u1", "A-101", "Ground floor plan", **{"Current Revision": "P02"}),  # revision moved on
        _sheet("u2", "A-102", "Level 1 plan"),                                      # renamed
        _sheet("u3", "A-203", "Roof plan"),                                         # renumbered
        _sheet("u5", "A-105", "Details"),                                           # added; u4 removed
    ]
    s = _run(ws, {"sheets": OLD_SHEETS}, {"sheets": new_sheets})["sheets"]
    assert s["status"] == "compared"
    assert [x["number"] for x in s["added"]] == ["A-105"]
    assert [x["number"] for x in s["removed"]] == ["A-104"]
    by_uid = {c["uid"]: c["changes"] for c in s["changed"]}
    assert by_uid["u2"] == [{"field": "name", "old": "First floor plan", "new": "Level 1 plan"}]
    assert by_uid["u3"] == [{"field": "number", "old": "A-103", "new": "A-203"}]
    assert by_uid["u1"] == [{"field": "revision: Current Revision", "old": "P01", "new": "P02"}]
    assert s["counts"]["added"] == 1 and s["counts"]["changed"] == 3


def test_sheet_moved_in_order_reports_only_the_mover(ws):
    # A-101 becomes A-199: it now sorts last. The three others keep their relative order.
    new_sheets = [_sheet("u1", "A-199", "Ground floor plan", **{"Current Revision": "P01"}), *OLD_SHEETS[1:]]
    s = _run(ws, {"sheets": OLD_SHEETS}, {"sheets": new_sheets})["sheets"]
    assert [(m["uid"], m["from_position"], m["to_position"]) for m in s["moved"]] == [("u1", 1, 4)]


def test_moved_keys_helper():
    assert moved_keys(["a", "b", "c", "d"], ["a", "b", "c", "d"]) == []
    assert moved_keys(["a", "b", "c", "d"], ["d", "a", "b", "c"]) == [("d", 4, 1)]
    assert moved_keys([], []) == []


def test_identical_snapshots_report_no_change_when_data_is_there(ws):
    s = _run(ws, {"sheets": OLD_SHEETS}, {"sheets": OLD_SHEETS})["sheets"]
    assert s["status"] == "compared" and s["counts"] == {"added": 0, "removed": 0, "changed": 0, "moved": 0}


def test_missing_schedule_block_is_not_captured_not_no_change(ws):
    r = _run(ws, {"sheets": OLD_SHEETS}, {"sheets": OLD_SHEETS})
    assert r["schedules"]["status"] == "not_captured"
    assert "not a result of no change" in r["schedules"]["message"]
    assert "367" in r["schedules"]["message"]
    assert r["revisions"]["status"] == "not_captured"
    assert r["status"] == "partial" and "schedules" in r["message"]


def test_schedule_only_in_one_snapshot_names_which(ws):
    r = _run(ws, {"sheets": OLD_SHEETS}, {"sheets": OLD_SHEETS, "schedules": []})
    assert r["schedules"]["status"] == "not_captured"
    assert r["schedules"]["message"].startswith("The older snapshot does not hold")


def test_no_sheets_and_no_schedules_is_no_data(ws):
    r = _run(ws, {"elements": []}, {"elements": []})
    assert r["status"] == "no_data"
    assert {r["sheets"]["status"], r["schedules"]["status"], r["revisions"]["status"]} == {"not_captured"}


def test_sheets_from_viewsheet_element_records(ws):
    def el(uid, number, name):
        return {"uid": uid, "class": "ViewSheet", "params": {"Sheet Number": {"v": number}, "Sheet Name": {"v": name}}}
    r = _run(ws, {"elements": [el("u1", "A1", "Plan")]}, {"elements": [el("u1", "A1", "Plan 2")]})
    assert r["sheets"]["data_source"] == "ViewSheet element records"
    assert r["sheets"]["changed"][0]["changes"] == [{"field": "name", "old": "Plan", "new": "Plan 2"}]


def test_schedule_rows_added_removed_changed_moved(ws):
    old = _sched("s1", "Door schedule", [_row(1, "D1", "Single"), _row(2, "D2", "Double"),
                                         _row(3, "D3", "Single"), _row(4, "D4", "Single")])
    new = _sched("s1", "Door schedule", [_row(3, "D3", "Single"), _row(1, "D1", "Single"),
                                         _row(2, "D2", "Fire door"), _row(5, "D5", "Single")])
    sc = _run(ws, {"sheets": [], "schedules": [old]}, {"sheets": [], "schedules": [new]})["schedules"]
    assert sc["status"] == "compared"
    item = sc["schedules"][0]
    assert [x["element_id"] for x in item["added"]] == ["5"]
    assert [x["element_id"] for x in item["removed"]] == ["4"]
    assert item["changed"][0]["element_id"] == "2"
    assert item["changed"][0]["changes"] == [{"field": "Type", "old": "Double", "new": "Fire door"}]
    assert [(m["element_id"], m["from_position"], m["to_position"]) for m in item["moved"]] == [("3", 3, 1)]
    assert sc["counts"] == {"schedules_added": 0, "schedules_removed": 0, "added": 1, "removed": 1,
                            "changed": 1, "moved": 1}


def test_schedule_added_removed_renamed_and_fields(ws):
    old = [_sched("s1", "Rooms", [_row(1, "R1", "x")]), _sched("s2", "Old list", [])]
    new = [_sched("s1", "Room schedule", [_row(1, "R1", "x")], fields=("Mark", "Type", "Area")),
           _sched("s3", "New list", [])]
    sc = _run(ws, {"schedules": old}, {"schedules": new})["schedules"]
    assert [s["name"] for s in sc["schedules_added"]] == ["New list"]
    assert [s["name"] for s in sc["schedules_removed"]] == ["Old list"]
    item = sc["schedules"][0]
    assert item["renamed_from"] == "Rooms" and item["fields_added"] == ["Area"]


def test_rows_without_element_id_match_by_text(ws):
    old = _sched("s1", "Legend", [{"cells": ["A", "1"]}, {"cells": ["B", "2"]}])
    new = _sched("s1", "Legend", [{"cells": ["B", "2"]}, {"cells": ["C", "3"]}])
    item = _run(ws, {"schedules": [old]}, {"schedules": [new]})["schedules"]["schedules"][0]
    assert [r["cells"] for r in item["added"]] == [{"Mark": "C", "Type": "3"}]
    assert [r["cells"] for r in item["removed"]] == [{"Mark": "A", "Type": "1"}]
    assert item["changed"] == [] and item["moved"] == []


def test_truncated_schedule_is_partial(ws):
    old = _sched("s1", "Big", [_row(1, "a", "b")], rows_truncated=True)
    new = _sched("s1", "Big", [_row(1, "a", "b")])
    r = _run(ws, {"schedules": [old]}, {"schedules": [new]})
    assert r["schedules"]["status"] == "partial" and "cut short" in r["schedules"]["message"]
    assert r["status"] == "partial"


def test_schedule_without_rows_is_flagged(ws):
    both = {"schedules": [{"uid": "s1", "name": "Doors"}]}
    r = _run(ws, both, both)
    assert r["schedules"]["status"] == "partial"
    assert r["schedules"]["schedules"][0]["rows"] == "not_captured"


def test_revision_list_diff(ws):
    old = {"sheets": [], "revisions": [{"uid": "r1", "sequence": 1, "description": "Issue", "issued": False}]}
    new = {"sheets": [], "revisions": [{"uid": "r1", "sequence": 1, "description": "Issue", "issued": True},
                                       {"uid": "r2", "sequence": 2, "description": "Update", "issued": False}]}
    rv = _run(ws, old, new)["revisions"]
    assert rv["status"] == "compared"
    assert [x["sequence"] for x in rv["added"]] == [2]
    assert rv["changed"][0]["changes"] == [{"field": "issued", "old": "False", "new": "True"}]


def test_max_items_caps_lists_but_not_counts(ws):
    new = [_sheet(f"n{i}", f"B-{i}", "x") for i in range(10)]
    r = _run(ws, {"sheets": []}, {"sheets": new}, max_items=3)
    assert len(r["sheets"]["added"]) == 3 and r["sheets"]["counts"]["added"] == 10
    assert "cut at 3" in r["message"]


def test_partial_capture_is_flagged(ws):
    r = _run(ws, {"sheets": OLD_SHEETS, "counts": {"truncated": True}}, {"sheets": OLD_SHEETS})
    assert r["status"] == "partial" and "truncated" in r["message"]


def test_csv_export_with_formula_guard(ws):
    old = {"sheets": [_sheet("u1", "A-101", "Plan")]}
    new = {"sheets": [_sheet("u1", "A-101", "=HYPERLINK(1)"), _sheet("u2", "A-102", "New")]}
    r = _run(ws, old, new, export_filename="reports/diff.csv")
    with open(r["export_file"], encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0][:3] == ["section", "schedule", "change"]
    assert any(row[2] == "added" and row[3] == "A-102" for row in rows)
    changed = [row for row in rows if row[2] == "changed"][0]
    assert changed[7] == "'=HYPERLINK(1)"
    assert r["difference_rows"] == len(rows) - 1


def test_xlsx_export(ws):
    openpyxl = pytest.importorskip("openpyxl")
    r = _run(ws, {"sheets": []}, {"sheets": [_sheet("u2", "A-102", "New")]}, export_filename="diff.xlsx")
    sheet = openpyxl.load_workbook(r["export_file"]).active
    assert [c.value for c in sheet[1]][:3] == ["section", "schedule", "change"]
    assert sheet.cell(2, 4).value == "A-102"


@pytest.mark.parametrize("name", ["diff.txt", "../out.csv", "/abs/x.csv"])
def test_export_name_is_refused_outside_workspace_or_wrong_type(ws, name):
    with pytest.raises(ValueError):
        _run(ws, {"sheets": []}, {"sheets": []}, export_filename=name)


def test_hostile_snapshot_id_and_missing_snapshot(ws):
    with pytest.raises(ValueError, match="plain snapshot name"):
        ScheduleDiffModule().compare(older_snapshot_id="../x", newer_snapshot_id="new", workspace=ws)
    with pytest.raises(ValueError, match="not found"):
        ScheduleDiffModule().compare(older_snapshot_id="nope", newer_snapshot_id="nope2", workspace=ws)
    with pytest.raises(ValueError, match="needs older_snapshot_id"):
        ScheduleDiffModule().compare(workspace=ws)


def test_read_only_flag(ws):
    assert _run(ws, {"sheets": []}, {"sheets": []})["read_only"] is True
