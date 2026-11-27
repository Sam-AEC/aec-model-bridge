"""scripts/sync_counts.py rewrites every tool count claim that test_tool_count_claims.py checks."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

COUNTS = {
    "tools": 330,
    "by_provider": {
        "revit": 115,
        "approval": 6,
        "module": 130,
        "rhino": 19,
        "speckle": 17,
        "navisworks": 15,
        "ifc": 7,
        "graph": 21,
    },
    "addin_commands": 200,
}

TABLE = """| Area | Tools | What |
|---|---|---|
| Revit | {} | Read |
| Approval | {} | Plan |
| Modules | {} | Checks |
| Rhino | {} | Geometry |
| Speckle | {} | Send |
| Navisworks | {} | Tree |
| IFC | {} | Files |
| Graph, jobs | {} | Audits |
"""


@pytest.fixture
def sc():
    spec = importlib.util.spec_from_file_location("sync_counts_script", REPO / "scripts" / "sync_counts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stale_tree(tmp_path: Path, tools: int = 324, rows=(112, 6, 124, 19, 17, 15, 7, 24)) -> Path:
    (tmp_path / "docs" / "i18n").mkdir(parents=True)
    (tmp_path / "README.md").write_text(
        f"# Title\n\nRevit MCP server · 2024 – 2027 · {tools} tools · Claude\n\n## Tools\n\n"
        + TABLE.format(*rows)
        + f"\n{tools} tools are listed in the default setup.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "i18n" / "README.de.md").write_text(
        "# Titel\n\n## Werkzeuge\n\n"
        + TABLE.format(*rows)
        + f"\nIn der Standardkonfiguration werden {tools} Werkzeuge aufgelistet.\n",
        encoding="utf-8",
    )
    (tmp_path / "llms.txt").write_text(
        f"# X\n- Tools: {tools} in the default setup, counted in mock mode. Revit has {rows[0]} of them.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "mcp-token-budget.md").write_text(
        f"# Budget\n\nThe checkout exposes **{tools}** tools rather than the estimated 298.\n\n| Full catalogue (302 tools) | 1 |\n",
        encoding="utf-8",
    )
    return tmp_path


def test_table_values_fold_the_remainder_into_the_last_row(sc):
    assert sc.table_values(COUNTS) == [115, 6, 130, 19, 17, 15, 7, 21]


def test_check_reports_drift_in_every_file(sc, tmp_path):
    root = stale_tree(tmp_path)
    drift = sc.sync(root, COUNTS, write=False)
    assert sorted(drift) == ["README.md", "docs/i18n/README.de.md", "docs/mcp-token-budget.md", "llms.txt"]


def test_write_rewrites_claims_and_leaves_unrelated_numbers(sc, tmp_path):
    root = stale_tree(tmp_path)
    sc.sync(root, COUNTS, write=True)
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "· 330 tools ·" in readme and "\n330 tools are listed" in readme
    rows = [line.split("|")[2].strip() for line in readme.splitlines() if line.startswith("| ") and line.split("|")[2].strip().isdigit()]
    assert rows == ["115", "6", "130", "19", "17", "15", "7", "21"]
    assert "werden 330 Werkzeuge" in (root / "docs/i18n/README.de.md").read_text(encoding="utf-8")
    assert "Tools: 330 in the default setup, counted in mock mode. Revit has 115 of them." in (root / "llms.txt").read_text(
        encoding="utf-8"
    )
    budget = (root / "docs/mcp-token-budget.md").read_text(encoding="utf-8")
    assert "exposes **330** tools" in budget and "(302 tools)" in budget
    assert sc.sync(root, COUNTS, write=False) == []


def test_write_keeps_crlf_line_endings(sc, tmp_path):
    root = stale_tree(tmp_path)
    path = root / "llms.txt"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    sc.sync(root, COUNTS, write=True)
    data = path.read_bytes()
    assert b"\r\n" in data and b"Tools: 330" in data


def test_missing_claim_is_an_error_not_a_silent_skip(sc, tmp_path):
    root = stale_tree(tmp_path)
    (root / "llms.txt").write_text("# X\nno count here\n", encoding="utf-8")
    with pytest.raises(sc.SyncError, match="llms.txt"):
        sc.sync(root, COUNTS, write=False)


def test_main_check_exit_code_and_message(sc, tmp_path, capsys, monkeypatch):
    root = stale_tree(tmp_path)
    monkeypatch.setattr(sc, "ROOT", root)
    monkeypatch.setattr(sc, "compute_counts", lambda: COUNTS)
    assert sc.main(["--check"]) == 1
    assert "python scripts/sync_counts.py" in capsys.readouterr().err
    assert sc.main([]) == 0
    assert sc.main(["--check"]) == 0


def test_repo_counts_are_in_sync():
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "sync_counts.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stderr
