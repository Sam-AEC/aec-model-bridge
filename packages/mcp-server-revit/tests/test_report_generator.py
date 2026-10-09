"""Tests for Phase 14 — Report Generator module (W8, W16)."""
import importlib.util
import sqlite3
import pytest
from pathlib import Path


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rg = _load_mod("src/revit_mcp_server/modules/report_generator/module.py", "_rg_impl")
ReportGeneratorModule = _rg.ReportGeneratorModule


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def module():
    return ReportGeneratorModule()


def test_export_excel_creates_file(module, workspace, tmp_path):
    result = module.export_excel(
        param_names=["Mark", "FireRating"],
        include_qaqc=False,
        workspace=workspace,
    )
    assert result["status"] == "exported"
    out = Path(result["output_file"])
    assert out.exists()
    assert out.suffix == ".xlsx"
    assert result["element_count"] == 6


def test_export_excel_includes_params_sheet(module, workspace, tmp_path):
    import openpyxl
    result = module.export_excel(
        param_names=["Mark"],
        include_qaqc=False,
        workspace=workspace,
    )
    wb = openpyxl.load_workbook(result["output_file"])
    assert "Parameters" in wb.sheetnames
    ws = wb["Parameters"]
    headers = [ws.cell(1, col).value for col in range(1, ws.max_column + 1)]
    assert "Mark" in headers


def test_export_excel_with_element_filter(module, workspace):
    result = module.export_excel(
        element_filter={"category": "OST_Doors"},
        include_qaqc=False,
        workspace=workspace,
    )
    assert result["element_count"] == 1


def test_export_excel_with_qaqc_no_issues(module, workspace):
    """QA sheet should exist even with no issue store."""
    import openpyxl
    result = module.export_excel(include_qaqc=True, workspace=workspace)
    wb = openpyxl.load_workbook(result["output_file"])
    assert "QA_QC Issues" in wb.sheetnames


def test_export_sqlite_creates_db(module, workspace, tmp_path):
    result = module.export_sqlite_summary(workspace=workspace)
    assert result["status"] == "exported"
    db_path = Path(result["output_file"])
    assert db_path.exists()
    
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM elements").fetchone()[0]
    conn.close()
    assert count == 6


def test_export_sqlite_type_table(module, workspace):
    result = module.export_sqlite_summary(workspace=workspace)
    conn = sqlite3.connect(result["output_file"])
    types = conn.execute("SELECT * FROM types").fetchall()
    conn.close()
    assert len(types) >= 2


def test_export_excel_custom_filename(module, workspace, tmp_path):
    result = module.export_excel(
        output_filename="custom_report.xlsx",
        include_qaqc=False,
        workspace=workspace,
    )
    assert Path(result["output_file"]).name == "custom_report.xlsx"


def test_export_excel_has_summary_sheet_first(tmp_path):
    import openpyxl
    from types import SimpleNamespace

    ws = SimpleNamespace(allowed_directories=[tmp_path])
    result = ReportGeneratorModule().export_excel(workspace=ws)
    wb = openpyxl.load_workbook(result["output_file"])
    assert wb.sheetnames[0] == "Summary"
    values = {row[0].value: row[1].value for row in wb["Summary"].iter_rows(min_row=2)}
    assert values["Snapshot ID"] == "(mock)"
    assert "mock" in values["Document"].lower()


# --- build_review_pack (one-file coordinator review) ---

def test_review_pack_sheets_columns_and_mock_label(tmp_path):
    import openpyxl
    from types import SimpleNamespace

    ws = SimpleNamespace(allowed_directories=[tmp_path])
    result = ReportGeneratorModule().build_review_pack(workspace=ws)
    assert result["data_source"] == "mock"
    wb = openpyxl.load_workbook(result["output_file"])
    assert wb.sheetnames == ["Cover", "Findings", "Counts by category", "What to do next"]
    cover = {r[0].value: r[1].value for r in wb["Cover"].iter_rows(min_row=2)}
    assert cover["Data source"] == "mock"
    assert "mock" in cover["Data source note"].lower()
    assert cover["Snapshot ID"]
    headers = [c.value for c in wb["Findings"][1]]
    assert headers == ["Severity", "Rule", "Category", "What is wrong", "Elements affected", "UniqueIds", "Next step"]
    assert [c.value for c in wb["Counts by category"][1]] == ["Category", "Elements", "Flagged by rules"]
    assert [c.value for c in wb["What to do next"][1]][:2] == ["Priority", "Action"]


def test_review_pack_real_snapshot_labelled_real(tmp_path):
    import json
    import openpyxl
    from types import SimpleNamespace

    (tmp_path / "snapshots").mkdir()
    snap = {
        "snapshot_id": "snap1", "taken_at": "2026-01-01T00:00:00Z",
        "source": {"doc_title": "Tower A", "doc_guid": "g-1"},
        "elements": [{"uid": "u1", "category": "OST_Rooms", "type_name": "Office", "params": {}}],
        "types": [],
    }
    (tmp_path / "snapshots" / "snap1.json").write_text(json.dumps(snap), encoding="utf-8")
    ws = SimpleNamespace(allowed_directories=[tmp_path])
    result = ReportGeneratorModule().build_review_pack(snapshot_id="snap1", workspace=ws)
    assert result["data_source"] == "real"
    wb = openpyxl.load_workbook(result["output_file"])
    cover = {r[0].value: r[1].value for r in wb["Cover"].iter_rows(min_row=2)}
    assert cover["Document"] == "Tower A"
    assert cover["Data source"] == "real"
    findings = list(wb["Findings"].iter_rows(min_row=2, values_only=True))
    assert any("u1" in (row[5] or "") for row in findings)


def test_review_pack_rejects_missing_snapshot_in_bridge_mode(tmp_path, monkeypatch):
    from revit_mcp_server.config import BridgeMode, config
    from types import SimpleNamespace

    monkeypatch.setattr(config, "mode", BridgeMode.bridge)
    ws = SimpleNamespace(allowed_directories=[tmp_path])
    with pytest.raises(ValueError, match="requires a snapshot_id"):
        ReportGeneratorModule().build_review_pack(snapshot_id="", workspace=ws)


def test_review_pack_rejects_path_outside_workspace(tmp_path):
    from types import SimpleNamespace

    ws = SimpleNamespace(allowed_directories=[tmp_path])
    with pytest.raises(Exception, match="outside the allowed workspace"):
        ReportGeneratorModule().build_review_pack(output_filename="../escape.xlsx", workspace=ws)


def _real_snapshot(tmp_path, elements, name="snap1"):
    import json

    (tmp_path / "snapshots").mkdir(exist_ok=True)
    snap = {
        "snapshot_id": name, "taken_at": "2026-01-01T00:00:00Z",
        "source": {"doc_title": "Tower A", "doc_guid": "g-1"},
        "elements": elements, "types": [],
    }
    (tmp_path / "snapshots" / f"{name}.json").write_text(json.dumps(snap), encoding="utf-8")


def test_review_pack_snapshot_id_cannot_escape_snapshots_dir(tmp_path):
    import json
    from types import SimpleNamespace

    (tmp_path / "snapshots").mkdir()
    (tmp_path / "outside.json").write_text(json.dumps({"snapshot_id": "x", "elements": []}), encoding="utf-8")
    ws = SimpleNamespace(allowed_directories=[tmp_path])
    for bad in ("../outside", str(tmp_path / "outside")):
        with pytest.raises(ValueError):
            ReportGeneratorModule().build_review_pack(snapshot_id=bad, workspace=ws)


def test_review_pack_cover_counts_distinct_elements(tmp_path):
    import openpyxl
    from types import SimpleNamespace

    # One room missing both Name and Number is flagged by two rules but is one element.
    _real_snapshot(tmp_path, [{"uid": "u1", "category": "OST_Rooms", "type_name": "Office", "params": {}}])
    ws = SimpleNamespace(allowed_directories=[tmp_path])
    result = ReportGeneratorModule().build_review_pack(snapshot_id="snap1", workspace=ws)
    wb = openpyxl.load_workbook(result["output_file"])
    cover = {r[0].value: r[1].value for r in wb["Cover"].iter_rows(min_row=2)}
    assert cover["Rules with findings"] >= 2
    assert cover["Elements flagged"] == 1
    assert cover["Elements flagged"] <= cover["Elements reviewed"]


def test_review_pack_keeps_every_uid_when_list_exceeds_cell_limit(tmp_path):
    import openpyxl
    from types import SimpleNamespace

    n = 1500
    uids = [f"{i:04d}-" + "x" * 40 for i in range(n)]  # ~ 45 chars each -> > 32,767 joined
    _real_snapshot(tmp_path, [{"uid": u, "category": "OST_Rooms", "type_name": "Office", "params": {}} for u in uids])
    ws = SimpleNamespace(allowed_directories=[tmp_path])
    result = ReportGeneratorModule().build_review_pack(snapshot_id="snap1", workspace=ws)
    wb = openpyxl.load_workbook(result["output_file"])
    found = set()
    for row in wb["Findings"].iter_rows(min_row=2, values_only=True):
        cell = row[5] or ""
        assert len(cell) <= 32767
        found.update(p for p in cell.split("; ") if p)
    assert set(uids) <= found
