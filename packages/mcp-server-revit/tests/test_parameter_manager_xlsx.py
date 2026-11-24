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
