"""Three-column CSV (element_id, parameter, value) to a draft plan (#186)."""
import importlib.util
from pathlib import Path

import pytest

_p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/parameter_manager/module.py"
_spec = importlib.util.spec_from_file_location("_pm_csv_rows_impl", _p)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class WS:
    def __init__(self, tmp_path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return WS(tmp_path)


@pytest.fixture
def pm():
    return _mod.ParameterManagerModule()


def _write(tmp_path, text, name="rows.csv"):
    (tmp_path / name).write_text(text, encoding="utf-8", newline="")
    return name


def test_fixture_csv_makes_draft_plan_with_row_diff(pm, workspace, tmp_path):
    name = _write(
        tmp_path,
        "element_id,parameter,value\n"
        "300,Mark,D-999\n"
        "300,FireRating,30\n"  # equal to snapshot: unchanged
        "200,Unconnected Height,5.5\n",
    )
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["plan_type"] == "action_plan_draft"
    assert res["requires_approval"] is True
    prev = res["preview"]
    by_id = {p["element_id"]: p["updates"] for p in prev["planned"]}
    assert by_id[300] == {"Mark": {"before": "D-101", "after": "D-999"}}
    assert by_id[200] == {"Unconnected Height": {"before": 4.0, "after": 5.5}}
    assert prev["row_diff"] == {"rows": 2, "changed_rows": 2, "unchanged_rows": 0, "unknown_rows": 0, "csv_rows": 3}
    assert prev["blocked"] == []
    assert sorted((a["arguments"]["element_id"], a["arguments"]["parameter_name"]) for a in res["actions"]) == [
        (200, "Unconnected Height"), (300, "Mark")]
    assert {a["tool"] for a in res["actions"]} == {"revit_set_parameter_value"}


def test_unknown_ids_and_parameters_are_listed_and_make_no_action(pm, workspace, tmp_path):
    name = _write(
        tmp_path,
        "element_id,parameter,value\n"
        "9999,Mark,X\n"
        "300,NoSuchParam,1\n"
        "200,Length,3\n"  # read-only
        "abc,Mark,X\n",
    )
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["actions"] == [] and res["preview"]["planned"] == []
    reasons = " | ".join(b["reason"] for b in res["preview"]["blocked"])
    assert "9999" in reasons and "NoSuchParam" in reasons and "read-only" in reasons and "abc" in reasons
    assert res["preview"]["row_diff"]["unknown_rows"] == 2
    assert res["skipped"] == res["preview"]["blocked"]


def test_blank_value_and_blank_parameter_are_blocked(pm, workspace, tmp_path):
    name = _write(tmp_path, "element_id,parameter,value\n300,Mark,\n300,,x\n")
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["actions"] == []
    assert len(res["preview"]["blocked"]) == 2


def test_conflicting_duplicate_rows_are_blocked(pm, workspace, tmp_path):
    name = _write(tmp_path, "element_id,parameter,value\n300,Mark,A\n300,Mark,B\n300,FireRating,60\n")
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    updates = {p["element_id"]: p["updates"] for p in res["preview"]["planned"]}
    assert list(updates[300]) == ["FireRating"]
    assert any("more than once" in b["reason"] for b in res["preview"]["blocked"])


def test_reserved_names_are_blocked(pm, workspace, tmp_path):
    name = _write(tmp_path, "element_id,parameter,value\n300,category,X\n")
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["actions"] == [] and res["preview"]["blocked"]


def test_bad_value_for_numeric_parameter_is_blocked(pm, workspace, tmp_path):
    name = _write(tmp_path, "element_id,parameter,value\n200,Unconnected Height,tall\n")
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["actions"] == [] and "Cannot cast" in res["preview"]["blocked"][0]["reason"]


def test_header_is_case_and_space_tolerant_and_extra_columns_ignored(pm, workspace, tmp_path):
    name = _write(tmp_path, "﻿ Element_ID ,Parameter,VALUE,note\n300,Mark,D-5,hi\n")
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["preview"]["planned"][0]["updates"]["Mark"]["after"] == "D-5"


@pytest.mark.parametrize("header", ["element_id,parameter\n300,Mark\n", "id,param,val\n1,2,3\n", "foo,bar\n1,2\n"])
def test_missing_columns_refused(pm, workspace, tmp_path, header):
    name = _write(tmp_path, header)
    with pytest.raises(ValueError, match="element_id"):
        pm.import_params_csv(csv_filename=name, workspace=workspace)


def test_empty_and_header_only_files_refused(pm, workspace, tmp_path):
    with pytest.raises(ValueError, match="empty"):
        pm.import_params_csv(csv_filename=_write(tmp_path, "", "a.csv"), workspace=workspace)
    with pytest.raises(ValueError, match="no data rows"):
        pm.import_params_csv(csv_filename=_write(tmp_path, "element_id,parameter,value\n", "b.csv"), workspace=workspace)


def test_oversize_file_refused(pm, workspace, tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "_MAX_CSV_BYTES", 64)
    name = _write(tmp_path, "element_id,parameter,value\n" + "300,Mark,D-1\n" * 20)
    with pytest.raises(ValueError, match="too large"):
        pm.import_params_csv(csv_filename=name, workspace=workspace)


def test_too_many_rows_refused(pm, workspace, tmp_path, monkeypatch):
    monkeypatch.setattr(_mod, "_MAX_CSV_ROWS", 2)
    name = _write(tmp_path, "element_id,parameter,value\n300,Mark,A\n300,Mark,B\n300,Mark,C\n")
    with pytest.raises(ValueError, match="more than 2 rows"):
        pm.import_params_csv(csv_filename=name, workspace=workspace)


@pytest.mark.parametrize("name", ["../x.csv", "/etc/x.csv"])
def test_paths_cannot_escape_workspace(pm, workspace, name):
    with pytest.raises(ValueError):
        pm.import_params_csv(csv_filename=name, workspace=workspace)


def test_wide_csv_still_works(pm, workspace, tmp_path):
    name = _write(tmp_path, "uid,Mark\nc0326e0e-473d-4952-b8ec-f23696541f44-door-1,D-7\n")
    res = pm.import_params_csv(csv_filename=name, workspace=workspace)
    assert res["preview"]["planned"][0]["updates"]["Mark"]["after"] == "D-7"


@pytest.mark.parametrize("cell,expected", [
    ("true", True), (" TRUE ", True), ("1", True), ("Yes", True),
    ("false", False), ("0", False), (" No ", False),
])
def test_boolean_cells_accept_only_known_words(cell, expected):
    el = {"uid": "u1", "element_id": 1, "params": {"Flag": {"storage": "Boolean", "v": None}}}
    planned, blocked, _ = _mod._plan_rows([{"uid": "u1", "Flag": cell}], [el])
    assert blocked == [] and planned[0]["updates"]["Flag"]["after"] is expected


@pytest.mark.parametrize("cell", ["maybe", "2", "y", "on", "truee"])
def test_boolean_cells_with_other_words_are_blocked(cell):
    el = {"uid": "u1", "element_id": 1, "params": {"Flag": {"storage": "Boolean", "v": True}}}
    planned, blocked, _ = _mod._plan_rows([{"uid": "u1", "Flag": cell}], [el])
    assert planned == [] and "Cannot cast" in blocked[0]["reason"]


def test_oversized_cell_is_refused_with_a_plain_message(pm, workspace, tmp_path):
    name = _write(tmp_path, "element_id,parameter,value\n300,Mark," + "x" * 200_000 + "\n")
    with pytest.raises(ValueError, match="could not be read as CSV"):
        pm.import_params_csv(csv_filename=name, workspace=workspace)


def test_blocked_list_in_the_preview_is_capped(pm, workspace, tmp_path):
    name = _write(tmp_path, "element_id,parameter,value\n" + "".join(f"{9000 + i},Mark,X\n" for i in range(450)))
    prev = pm.import_params_csv(csv_filename=name, workspace=workspace)["preview"]
    assert prev["blocked_count"] == 450 and prev["blocked_total"] == 450
    assert len(prev["blocked"]) == 200
