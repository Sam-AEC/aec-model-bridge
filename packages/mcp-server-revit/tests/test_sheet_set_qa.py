"""Tests for the sheet_set_qa module (fixtures are synthetic saved snapshots)."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.sheet_set_qa import module as sq
from revit_mcp_server.modules.sheet_set_qa.module import SheetSetQaModule, split_number

FIELDS = {"Drawn By": {"v": "AB"}, "Checked By": "CD", "Sheet Issue Date": "2026-11-01"}


@pytest.fixture
def ws(tmp_path):
    return SimpleNamespace(allowed_directories=[tmp_path])


def _sheet(uid, number, name="Plan", views=("v",), **params):
    return {"uid": uid, "number": number, "name": name, "view_uids": list(views), "params": {**FIELDS, **params}}


def _run(ws, data, sid="snap", **kw):
    d = ws.allowed_directories[0] / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{sid}.json").write_text(json.dumps(data), encoding="utf-8")
    return SheetSetQaModule().check(snapshot_id=sid, workspace=ws, **kw)


def _by_check(result):
    return {f["check"]: f for f in result["findings"]}


CLEAN = {"sheets": [_sheet("a1", "A-101"), _sheet("a2", "A-102"), _sheet("a3", "A-201", "Sections"),
                    _sheet("s1", "S-101", "Framing")], "views": []}


def test_clean_set_is_ready_for_issue(ws):
    r = _run(ws, CLEAN)
    assert r["status"] == "ok" and r["total_findings"] == 0 and r["ready_for_issue"] is True
    assert r["sheets_per_prefix"] == {"A": 3, "S": 1}
    assert all(c["status"] == "ran" for c in r["checks"].values())
    assert r["read_only"] is True


def test_split_number():
    assert split_number("A-101.1") == ("A", "A-", 101, ".1", "101")
    assert split_number("a101B") == ("A", "a", 101, "b", "101")
    assert split_number("A1-005") == ("A1", "A1-", 5, "", "005")
    assert split_number("COVER") is None


def test_duplicate_and_equivalent_numbers(ws):
    data = {"sheets": CLEAN["sheets"] + [_sheet("d1", "a-101", "Dup"), _sheet("e1", "A102", "Same")]}
    f = _by_check(_run(ws, data))
    assert f["duplicate_sheet_numbers"]["severity"] == "error"
    assert f["duplicate_sheet_numbers"]["unique_ids"] == ["a1", "d1"]
    assert f["equivalent_sheet_numbers"]["severity"] == "warning"
    assert f["equivalent_sheet_numbers"]["unique_ids"] == ["a2", "e1"]


def test_gaps_reported_inside_a_series_only(ws):
    data = {"sheets": [_sheet("1", "A-101"), _sheet("2", "A-104"), _sheet("3", "A-201"),
                       _sheet("4", "M-01"), _sheet("5", "M-03"), _sheet("6", "COVER", "Cover")]}
    r = _run(ws, data)
    f = _by_check(r)["non_sequential_numbers"]
    assert f["severity"] == "info"
    assert [g["missing"] for g in f["gaps"]] == ["A-102 to A-103", "M-02"]
    assert f["gaps"][0]["missing_count"] == 2
    assert _by_check(r)["unparsed_sheet_numbers"]["unique_ids"] == ["6"]
    # A larger series joins A-104 and A-201 into one run.
    r = _run(ws, data, series_size=1000)
    assert "A-105 to A-200" in [g["missing"] for g in _by_check(r)["non_sequential_numbers"]["gaps"]]


def test_missing_required_fields_and_alias(ws):
    data = {"sheets": [_sheet("1", "A-101", **{"Checked By": ""}), _sheet("2", "A-102", **{"Drawn By": {"v": " "}})]}
    f = _run(ws, data)["findings"]
    missing = {x["field"]: x["unique_ids"] for x in f if x["check"] == "missing_required_field"}
    assert missing == {"Checked By": ["1"], "Drawn By": ["2"]}
    r = _run(ws, data, required_fields=["Issue Date"])  # alias of Sheet Issue Date
    assert r["checks"]["missing_required_fields"]["status"] == "ran" and r["total_findings"] == 0


def test_field_on_no_sheet_is_not_captured_not_passed(ws):
    r = _run(ws, CLEAN, required_fields=["Approved By"])
    assert r["status"] == "partial" and r["ready_for_issue"] is False
    assert r["checks"]["missing_required_fields"]["not_captured"] == ["Approved By"]
    f = _by_check(r)["field_not_found"]
    assert f["severity"] == "warning" and "NOT checked" in f["message"]


def test_sheets_without_views_and_placeholders(ws):
    data = {"sheets": CLEAN["sheets"] + [_sheet("e", "A-103", "Empty", views=()),
                                         {**_sheet("p", "A-104", "Placeholder", views=()), "is_placeholder": True}]}
    f = _by_check(_run(ws, data))["sheets_without_views"]
    assert f["unique_ids"] == ["e"] and f["severity"] == "warning"


def test_view_sheet_uid_counts_as_placed(ws):
    sheets = [{k: v for k, v in _sheet("a", "A-101").items() if k != "view_uids"}]
    r = _run(ws, {"sheets": sheets, "views": [{"uid": "v1", "sheet_uid": "a"}]})
    assert r["checks"]["sheets_without_views"]["status"] == "ran" and r["total_findings"] == 0


def test_patterns_default_custom_and_off(ws):
    data = {"sheets": CLEAN["sheets"] + [_sheet("x", "A-105 ", "Unnamed"), _sheet("y", "A-106", " Lead space")]}
    f = _by_check(_run(ws, data))
    assert f["name_pattern_mismatch"]["unique_ids"] == ["x", "y"]
    assert f["number_pattern_mismatch"]["unique_ids"] == ["x"]  # a trailing space breaks the pattern
    r = _run(ws, CLEAN, number_pattern=r"[AS]-\d{3}", name_pattern="")
    assert r["checks"]["name_pattern_mismatch"]["status"] == "off" and r["total_findings"] == 0
    r = _run(ws, CLEAN, number_pattern=r"S-\d{3}")
    assert _by_check(r)["number_pattern_mismatch"]["unique_ids"] == ["a1", "a2", "a3"]
    with pytest.raises(ValueError, match="not a valid regular expression"):
        _run(ws, CLEAN, number_pattern="([")


def test_issue_set_filter_and_missing_requested_sheet(ws):
    data = {"sheets": CLEAN["sheets"] + [_sheet("e", "A-103", "Empty", views=())]}
    r = _run(ws, data, sheet_numbers=["A-101", "a-102", "Z-999"])
    assert r["sheet_count"] == 2 and r["sheets_in_snapshot"] == 5
    f = _by_check(r)
    assert f["requested_sheet_missing"]["severity"] == "error"
    assert [s["number"] for s in f["requested_sheet_missing"]["sheets"]] == ["Z-999"]
    assert "sheets_without_views" not in f  # A-103 is not in the issue set
    assert r["findings"][0]["severity"] == "error" and r["ready_for_issue"] is False


def test_element_records_only_is_partial(ws):
    data = {"elements": [
        {"uid": "s1", "class": "ViewSheet", "params": {"Sheet Number": {"v": "A-101"}, "Sheet Name": {"v": "P"}, **FIELDS}},
        {"uid": "s2", "class": "ViewSheet", "params": {"Sheet Number": {"v": "A-101"}, "Sheet Name": {"v": "Q"}, **FIELDS}},
    ]}
    r = _run(ws, data)
    assert r["status"] == "partial" and r["data_source"] == "ViewSheet element records"
    assert r["checks"]["sheets_without_views"]["status"] == "not_enough_data"
    assert "NOT fully run" in r["message"]
    assert _by_check(r)["duplicate_sheet_numbers"]["unique_ids"] == ["s1", "s2"]


def test_no_sheets_is_reported_plainly(ws):
    r = _run(ws, {"elements": [{"uid": "w", "category": "OST_Walls"}], "counts": {"categories": ["OST_Walls"]}})
    assert r["status"] == "no_sheet_data" and r["findings"] == []
    assert "nothing was checked" in r["message"] and "category-filtered" in r["message"]


def test_partial_capture_flag(ws):
    r = _run(ws, {**CLEAN, "counts": {"truncated": True}})
    assert r["status"] == "partial" and r["ready_for_issue"] is False


def test_csv_output_escapes_formulas(ws):
    data = {"sheets": CLEAN["sheets"] + [_sheet("f", "A-105", "=HYPERLINK(1)", views=())]}
    r = _run(ws, data, csv_filename="reports/sheets.csv")
    rows = list(csv.DictReader(Path(r["csv_file"]).open(encoding="utf-8")))
    empty = [row for row in rows if row["check"] == "sheets_without_views"]
    assert empty[0]["sheet_name"] == "'=HYPERLINK(1)" and empty[0]["unique_id"] == "f"
    gap = [row for row in rows if row["check"] == "non_sequential_numbers"]
    assert gap[0]["sheet_number"] == "A-103 to A-104"
    for bad in ("../x.csv", "x.txt"):
        with pytest.raises(ValueError):
            _run(ws, CLEAN, csv_filename=bad)


def test_input_validation(ws):
    with pytest.raises(ValueError, match="snapshot_id"):
        SheetSetQaModule().check(workspace=ws)
    with pytest.raises(ValueError, match="plain snapshot name"):
        SheetSetQaModule().check(snapshot_id="../x", workspace=ws)
    with pytest.raises(ValueError, match="not found"):
        SheetSetQaModule().check(snapshot_id="nope", workspace=ws)
    with pytest.raises(ValueError, match="series_size"):
        _run(ws, CLEAN, series_size=0)


def test_manifest_and_description():
    from revit_mcp_server.tool_metadata import DESCRIPTIONS

    manifest = json.loads((Path(sq.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert all(not c["is_mutating"] for c in manifest["commands"])
    assert "files.write" in manifest["permissions"]
    assert DESCRIPTIONS["sheet_set_qa_check"].endswith("Read-only.")
