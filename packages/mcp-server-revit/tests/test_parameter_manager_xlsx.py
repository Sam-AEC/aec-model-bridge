"""Excel round-trip for the parameter_manager module (#185)."""
import importlib.util
from pathlib import Path

import pytest
from openpyxl import load_workbook

_p = Path(__file__).parent.parent / "src/revit_mcp_server/modules/parameter_manager/module.py"
_spec = importlib.util.spec_from_file_location("_pm_xlsx_impl", _p)
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


def test_round_trip_makes_draft_plan_with_row_diff(pm, workspace, tmp_path):
    out = pm.export_params_xlsx(
        element_filter={"category": "OST_Doors"},
        param_names=["Mark", "FireRating"],
        output_filename="doors.xlsx",
        workspace=workspace,
    )
    assert out["status"] == "exported" and out["element_count"] == 1
    path = tmp_path / "doors.xlsx"

    same = pm.import_params_xlsx(xlsx_filename="doors.xlsx", workspace=workspace)
    assert same["preview"]["planned"] == []
    assert same["preview"]["row_diff"]["unchanged_rows"] == 1

    wb = load_workbook(path)
    ws = wb["Parameters"]
    col = [c.value for c in ws[1]].index("Mark") + 1
    ws.cell(row=2, column=col, value="D-999")
    ws.append(["no-such-uid", None, None, None, None, "X", None])
    wb.save(path)

    res = pm.import_params_xlsx(xlsx_filename="doors.xlsx", workspace=workspace)
    assert res["plan_type"] == "action_plan_draft"
    prev = res["preview"]
    assert prev["planned"][0]["updates"]["Mark"] == {"before": "D-101", "after": "D-999"}
    assert prev["row_diff"] == {"rows": 2, "changed_rows": 1, "unchanged_rows": 0, "unknown_rows": 1}
    assert any(b["uid"] == "no-such-uid" for b in prev["blocked"])
    assert res["actions"]


@pytest.mark.parametrize("name", ["../x.xlsx", "/etc/x.xlsx", "a/b.xlsx", "x.csv", None])
def test_names_cannot_escape_workspace(pm, workspace, name):
    with pytest.raises(ValueError):
        pm.import_params_xlsx(xlsx_filename=name, workspace=workspace)
    with pytest.raises(ValueError):
        pm.export_params_xlsx(element_filter={}, param_names=["Mark"], output_filename=name, workspace=workspace)


def test_missing_uid_header_is_refused(pm, workspace, tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Mark"])
    wb.save(tmp_path / "bad.xlsx")
    with pytest.raises(ValueError, match="uid"):
        pm.import_params_xlsx(xlsx_filename="bad.xlsx", workspace=workspace)


def test_cell_text_is_kept_exactly():
    assert _mod._cell_text(" A ") == " A "
    assert _mod._cell_text(3.0) == "3"


def test_whitespace_is_part_of_the_value_and_blank_cells_are_skipped(pm, workspace, tmp_path):
    pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, param_names=["Mark", "FireRating"],
                          output_filename="ws.xlsx", workspace=workspace)
    path = tmp_path / "ws.xlsx"
    wb = load_workbook(path)
    ws = wb["Parameters"]
    header = [c.value for c in ws[1]]
    ws.cell(row=2, column=header.index("Mark") + 1, value="D-101 ")
    ws.cell(row=2, column=header.index("FireRating") + 1, value="   ")
    wb.save(path)
    prev = pm.import_params_xlsx(xlsx_filename="ws.xlsx", workspace=workspace)["preview"]
    assert prev["planned"][0]["updates"] == {"Mark": {"before": "D-101", "after": "D-101 "}}


@pytest.mark.parametrize("cell", [" true ", "yes ", " 1", "TRUE"])
def test_boolean_cells_ignore_surrounding_spaces(cell):
    el = {"uid": "u1", "element_id": 1, "params": {"Is Fire Door": {"storage": "Boolean", "v": True}}}
    planned, blocked, counts = _mod._plan_rows([{"uid": "u1", "Is Fire Door": cell}], [el], skip_unchanged=True)
    assert planned == [] and blocked == [] and counts["unchanged_rows"] == 1


def _write_mapping(tmp_path, name, columns):
    import json
    folder = tmp_path / "excel_mappings"
    folder.mkdir(exist_ok=True)
    (folder / f"{name}.json").write_text(json.dumps({"columns": columns}), encoding="utf-8")


def test_mapping_headers_round_trip(pm, workspace, tmp_path):
    _write_mapping(tmp_path, "nl-doors", {"Deurnummer": "Mark", "Brandwerendheid": "FireRating"})
    out = pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, mapping="nl-doors",
                                output_filename="doors.xlsx", workspace=workspace)
    assert out["param_names"] == ["Mark", "FireRating"]
    path = tmp_path / "doors.xlsx"
    wb = load_workbook(path)
    ws = wb["Parameters"]
    header = [c.value for c in ws[1]]
    assert header[5:] == ["Deurnummer", "Brandwerendheid"]
    ws.cell(row=2, column=header.index("Deurnummer") + 1, value="D-999")
    wb.save(path)

    res = pm.import_params_xlsx(xlsx_filename="doors.xlsx", mapping="nl-doors", workspace=workspace)
    assert res["preview"]["planned"][0]["updates"] == {"Mark": {"before": "D-101", "after": "D-999"}}
    assert res["preview"]["mapping"] == "nl-doors"


def test_mapping_with_unknown_parameter_is_refused(pm, workspace, tmp_path):
    _write_mapping(tmp_path, "bad", {"Nummer": "Mark", "X": "NoSuchParam"})
    with pytest.raises(ValueError, match="NoSuchParam"):
        pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, mapping="bad", workspace=workspace)
    pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, param_names=["Mark"],
                          output_filename="d.xlsx", workspace=workspace)
    with pytest.raises(ValueError, match="NoSuchParam"):
        pm.import_params_xlsx(xlsx_filename="d.xlsx", mapping="bad", workspace=workspace)


@pytest.mark.parametrize("columns", [{}, {"uid": "Mark"}, {"A": "Mark", "B": "Mark"}, {"A": 3}, ["Mark"]])
def test_malformed_mapping_is_refused(pm, workspace, tmp_path, columns):
    _write_mapping(tmp_path, "m", columns)
    with pytest.raises(ValueError, match="mapping"):
        pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, mapping="m", workspace=workspace)


@pytest.mark.parametrize("name", ["../x", "a/b", "/etc/passwd", "", "missing"])
def test_mapping_names_are_plain_and_must_exist(pm, workspace, name):
    with pytest.raises(ValueError, match="mapping"):
        pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, mapping=name or " ", workspace=workspace)


def test_mapping_and_param_names_together_are_refused(pm, workspace, tmp_path):
    _write_mapping(tmp_path, "m", {"Nummer": "Mark"})
    with pytest.raises(ValueError, match="mapping"):
        pm.export_params_xlsx(element_filter={"category": "OST_Doors"}, mapping="m", param_names=["Mark"],
                              workspace=workspace)
