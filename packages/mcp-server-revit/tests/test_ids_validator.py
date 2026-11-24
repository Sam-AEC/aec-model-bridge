"""Tests for the ids_validator module (IFC against IDS). Needs the optional `ids` extra."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.ids_validator import module as iv
from revit_mcp_server.modules.ids_validator.module import IdsValidatorModule

DATA = Path(__file__).parent / "data" / "ids"
needs_ifctester = pytest.mark.skipif(
    importlib.util.find_spec("ifctester") is None,
    reason="ifctester is not installed (pip install 'aec-model-bridge[ids]')",
)


@pytest.fixture
def ws(tmp_path):
    shutil.copy(DATA / "tiny.ifc", tmp_path / "tiny.ifc")
    shutil.copy(DATA / "tiny.ids", tmp_path / "tiny.ids")
    return SimpleNamespace(allowed_directories=[tmp_path])


def _run(ws, **kw):
    kw.setdefault("ifc_path", "tiny.ifc")
    kw.setdefault("ids_path", "tiny.ids")
    return IdsValidatorModule().validate_ifc(workspace=ws, **kw)


@needs_ifctester
def test_per_specification_results(ws):
    res = _run(ws)
    assert res["read_only"] is True and res["passed"] is False
    assert (res["specifications_total"], res["specifications_passed"], res["specifications_failed"]) == (2, 1, 1)
    walls, doors = res["specifications"]
    assert walls["name"] == "Walls have a fire rating" and walls["status"] == "fail"
    assert (walls["applicable"], walls["applicable_passed"], walls["applicable_failed"]) == (3, 1, 2)
    assert {e["global_id"] for e in walls["failed_entities"]} == {"2a2B3c4D5e6F7g8H9i0J1k", "3a2B3c4D5e6F7g8H9i0J1k"}
    assert walls["failed_entities"][0]["class"] == "IfcWall" and walls["failed_entities"][0]["reasons"]
    assert doors["status"] == "pass" and doors["failed_entities_total"] == 0


@needs_ifctester
def test_failed_entities_are_capped_with_full_count(ws):
    res = _run(ws, max_failed=1)
    walls = res["specifications"][0]
    assert walls["failed_entities_total"] == 2 and walls["failed_entities_shown"] == 1
    assert len(walls["failed_entities"]) == 1


@needs_ifctester
def test_reports_written_inside_workspace(ws):
    res = _run(ws, html_filename="reports/ids.html", json_filename="reports/ids.json")
    root = ws.allowed_directories[0].resolve()
    assert Path(res["html_file"]).resolve().is_relative_to(root) and Path(res["json_file"]).resolve().is_relative_to(root)
    assert "Walls have a fire rating" in Path(res["html_file"]).read_text(encoding="utf-8")
    saved = json.loads(Path(res["json_file"]).read_text(encoding="utf-8"))
    assert saved["specifications_failed"] == 1


@needs_ifctester
@pytest.mark.parametrize("kw", [
    {"ifc_path": "../tiny.ifc"}, {"ids_path": "/etc/passwd"}, {"ifc_path": "tiny.ids"}, {"ids_path": "tiny.ifc"},
    {"ifc_path": "missing.ifc"}, {"ifc_path": ""}, {"html_filename": "../x.html"}, {"html_filename": "x.txt"},
    {"json_filename": "../x.json"},
])
def test_paths_are_sandboxed_and_checked(ws, kw):
    with pytest.raises(ValueError):
        _run(ws, **kw)


@needs_ifctester
def test_symlink_out_of_workspace_refused(ws, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "evil.ifc"
    shutil.copy(DATA / "tiny.ifc", outside)
    link = ws.allowed_directories[0] / "link.ifc"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not available")
    with pytest.raises(ValueError):
        _run(ws, ifc_path="link.ifc")


@needs_ifctester
def test_invalid_ids_and_ifc_are_refused_plainly(ws):
    root = ws.allowed_directories[0]
    (root / "bad.ids").write_text("<ids>not an ids file</ids>", encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid IDS"):
        _run(ws, ids_path="bad.ids")
    (root / "bad.ifc").write_text("this is not STEP", encoding="utf-8")
    with pytest.raises(ValueError, match="IFC file could not be read"):
        _run(ws, ifc_path="bad.ifc")


def test_missing_ifctester_gives_install_hint(ws, monkeypatch):
    for name in ("ifctester", "ifctester.ids", "ifctester.reporter"):
        monkeypatch.setitem(sys.modules, name, None)  # makes `import` raise ImportError
    with pytest.raises(ValueError, match=r"aec-model-bridge\[ids\]"):
        _run(ws)


def test_read_only_manifest_and_description():
    from revit_mcp_server.tool_metadata import DESCRIPTIONS

    manifest = json.loads((Path(iv.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert all(not c["is_mutating"] for c in manifest["commands"])
    assert DESCRIPTIONS["ids_validator_validate_ifc"].endswith("Read-only.")
