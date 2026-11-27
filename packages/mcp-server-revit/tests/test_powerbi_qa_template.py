"""The Power BI scripts under docs/examples/powerbi name exactly the columns the QA exporters write."""
import re
from pathlib import Path

import pytest

from revit_mcp_server.modules.model_health import module as model_health
from revit_mcp_server.modules.param_completeness import module as param_completeness
from revit_mcp_server.modules.sheet_set_qa import module as sheet_set_qa

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / "docs" / "examples" / "powerbi"
PAGE = ROOT / "docs" / "powerbi-qa-dashboard.md"


def _header(text: str) -> list[str]:
    return text.split("\n", 1)[0].split(",")


def _list(script: str, name: str) -> list[str]:
    m = re.search(rf"^\s*{name} = \{{(.*?)\}},", script, re.M)
    assert m, f"{name} not found"
    return re.findall(r'"([^"]+)"', m.group(1))


CASES = [
    ("sheet-set-qa.pq", lambda: _header(sheet_set_qa._csv_text([])), "sheet_set_qa.csv"),
    ("param-completeness.pq", lambda: _header(param_completeness._csv_text([], True)), "param_completeness.csv"),
    ("model-health-trend.pq", lambda: _header(model_health._csv_text([])), "model_health.csv"),
]


@pytest.mark.parametrize("script,header,csv_name", CASES)
def test_script_columns_match_exporter_header(script, header, csv_name):
    text = (DIR / script).read_text(encoding="utf-8")
    required = _list(text, "RequiredColumns")
    optional = _list(text, "OptionalColumns") if "OptionalColumns =" in text else []
    assert sorted(required + optional) == sorted(header())
    assert csv_name in text and csv_name in PAGE.read_text(encoding="utf-8").replace("qa/", "")


def test_required_columns_are_the_header_without_by_level():
    base = _header(param_completeness._csv_text([], False))
    assert "level" not in base
    assert base == _list((DIR / "param-completeness.pq").read_text(encoding="utf-8"), "RequiredColumns")


@pytest.mark.parametrize("script", [c[0] for c in CASES])
def test_scripts_are_unverified_and_fail_on_missing_columns(script):
    text = (DIR / script).read_text(encoding="utf-8")
    assert "UNVERIFIED" in text
    assert "Missing columns" in text
    assert "WorkspaceFolder" in text


def test_page_lists_every_column_and_every_script():
    page = PAGE.read_text(encoding="utf-8")
    for script, header, _ in CASES:
        assert f"docs/examples/powerbi/{script}" in page
        for col in header():
            assert f"`{col}`" in page, col
    assert "UNVERIFIED" in page
