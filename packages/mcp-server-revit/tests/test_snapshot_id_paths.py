"""Issue #141: every module that reads a snapshot by id builds the path with snapshot_file.

A caller-supplied id such as '../x' must be refused with the same plain error the
report_generator and qaqc_checker modules raise, and no file outside the workspace
snapshots folder may be opened.
"""
from __future__ import annotations

import builtins
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from revit_mcp_server.modules.clash_triage import module as clash_triage
from revit_mcp_server.modules.familytype_mapper import module as familytype_mapper
from revit_mcp_server.modules.links_worksets_audit import module as links_worksets_audit
from revit_mcp_server.modules.model_bloat import module as model_bloat
from revit_mcp_server.modules.model_changes import module as model_changes
from revit_mcp_server.modules.model_inspector import module as model_inspector
from revit_mcp_server.modules.naming_checker import module as naming_checker
from revit_mcp_server.modules.schedule_consistency import module as schedule_consistency
from revit_mcp_server.modules.selection_tools import module as selection_tools
from revit_mcp_server.modules.sheet_view_audit import module as sheet_view_audit
from revit_mcp_server.modules.warnings_triage import module as warnings_triage
from revit_mcp_server.semantic import engine

PLAIN = "plain snapshot name"
SRC = Path(__file__).parent.parent / "src" / "revit_mcp_server"

# '' is listed too: it is refused by every loader; a public command may instead take its
# documented no-snapshot path (mock data or "needs a snapshot_id"), which opens no file.
BAD_IDS = ["../x", "a/b", "a\\b", "ABS", ""]
BAD_IDS_NONEMPTY = [b for b in BAD_IDS if b]

CONVENTION = {"pattern": "{a}-{b}", "fields": {"a": {"allowed": ["A"]}, "b": {"regex": "[0-9]+"}}}


@pytest.fixture
def ws(tmp_path):
    work = tmp_path / "work"
    (work / "snapshots").mkdir(parents=True)
    payload = {"snapshot_id": "x", "elements": [], "types": [], "source": {}}
    (tmp_path / "x.json").write_text(json.dumps(payload), encoding="utf-8")
    (work / "x.json").write_text(json.dumps(payload), encoding="utf-8")
    (work / "snapshots" / "snap1.json").write_text(json.dumps(payload), encoding="utf-8")
    return SimpleNamespace(allowed_directories=[work], root=work, outside=tmp_path)


def _bad(ws, raw):
    return str(ws.outside / "x") if raw == "ABS" else raw


@pytest.fixture
def opened(monkeypatch):
    """Record every path opened through open() or Path.open/read_text/read_bytes."""
    seen: list[str] = []
    real_open = builtins.open

    def spy(file, *a, **k):
        if isinstance(file, (str, bytes, os.PathLike)):
            seen.append(os.path.realpath(os.fsdecode(file)))
        return real_open(file, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    return seen


def _assert_nothing_outside(ws, opened):
    """No decoy file outside snapshots/ was opened (commands may write their own outputs)."""
    decoys = {os.path.realpath(ws.outside / "x.json").lower(), os.path.realpath(ws.root / "x.json").lower()}
    snaps = os.path.realpath(ws.root / "snapshots").lower()
    for path in opened:
        assert path.lower() not in decoys, f"opened a file outside snapshots/: {path}"
        if os.path.basename(path).lower() == "x.json":
            assert os.path.dirname(path).lower() == snaps


def _commands(ws):
    fm = familytype_mapper.FamilytypeMapperModule()
    lw = links_worksets_audit.LinksWorksetsAuditModule()
    mb = model_bloat.ModelBloatModule() if hasattr(model_bloat, "ModelBloatModule") else None
    nc = naming_checker.NamingCheckerModule()
    sc = schedule_consistency.ScheduleConsistencyModule()
    st = selection_tools.SelectionToolsModule()
    sv = sheet_view_audit.SheetViewAuditModule()
    cmds = {
        "familytype_mapper.audit_families": lambda sid: fm.audit_families(snapshot_id=sid, workspace=ws),
        "familytype_mapper.list_type_mappings": lambda sid: fm.list_type_mappings(snapshot_id=sid, workspace=ws),
        "links_worksets_audit.audit": lambda sid: lw.audit(snapshot_id=sid, workspace=ws),
        "naming_checker.check_names": lambda sid: nc.check_names(convention=CONVENTION, snapshot_id=sid, workspace=ws),
        "schedule_consistency.check_doors_and_rooms": lambda sid: sc.check_doors_and_rooms(snapshot_id=sid, workspace=ws),
        "selection_tools.select_by_query": lambda sid: st.select_by_query(filter={}, snapshot_id=sid, workspace=ws),
        "selection_tools.group_rename": lambda sid: st.group_rename(group_uid="g", new_name="n", snapshot_id=sid, workspace=ws),
        "selection_tools.group_ungroup": lambda sid: st.group_ungroup(group_uid="g", snapshot_id=sid, workspace=ws),
        "selection_tools.group_convert_to_detail": lambda sid: st.group_convert_to_detail(group_uid="g", snapshot_id=sid, workspace=ws),
        "sheet_view_audit.run_audit": lambda sid: sv.run_audit(snapshot_id=sid, workspace=ws),
    }
    if mb is not None:
        cmds["model_bloat.audit"] = lambda sid: mb.audit(snapshot_id=sid, workspace=ws)
    return cmds


COMMAND_NAMES = sorted(_commands(SimpleNamespace(allowed_directories=[Path(".")])).keys())


@pytest.mark.parametrize("raw", BAD_IDS_NONEMPTY)
@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_command_refuses_a_hostile_snapshot_id(ws, opened, name, raw):
    with pytest.raises(ValueError, match=PLAIN):
        _commands(ws)[name](_bad(ws, raw))
    _assert_nothing_outside(ws, opened)


@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_command_with_empty_snapshot_id_opens_no_outside_file(ws, opened, name):
    try:
        _commands(ws)[name]("")
    except ValueError:
        pass  # "needs a snapshot_id" style refusal is fine
    _assert_nothing_outside(ws, opened)


LOADERS = {
    "familytype_mapper._load_snapshot": lambda sid, ws: familytype_mapper._load_snapshot(sid, ws),
    "links_worksets_audit._load_elements": lambda sid, ws: links_worksets_audit.LinksWorksetsAuditModule._load_elements(sid, ws),
    "model_bloat._load_snapshot": lambda sid, ws: model_bloat._load_snapshot(sid, ws),
    "naming_checker._load_snapshot": lambda sid, ws: naming_checker.NamingCheckerModule()._load_snapshot(sid, ws),
    "schedule_consistency._get_data": lambda sid, ws: schedule_consistency.ScheduleConsistencyModule()._get_data(sid, ws),
    "selection_tools._load_snapshot": lambda sid, ws: selection_tools._load_snapshot(sid, ws),
    # The grep guard below covers every module under modules/, so these four are held to it too.
    "model_inspector._load_snapshot": lambda sid, ws: model_inspector._load_snapshot(sid, ws),
    "model_changes._load": lambda sid, ws: model_changes._load(sid, ws),
    "warnings_triage._load_snapshot": lambda sid, ws: warnings_triage._load_snapshot(sid, ws),
    "clash_triage._get_data": lambda sid, ws: clash_triage.ClashTriageModule()._get_data(sid, ws),
}


@pytest.mark.parametrize("raw", [b for b in BAD_IDS if b != ""])
@pytest.mark.parametrize("name", sorted(LOADERS))
def test_loader_refuses_a_hostile_snapshot_id(ws, opened, name, raw):
    with pytest.raises(ValueError, match=PLAIN):
        LOADERS[name](_bad(ws, raw), ws)
    _assert_nothing_outside(ws, opened)


@pytest.mark.parametrize(
    "name", [n for n in sorted(LOADERS) if n not in ("schedule_consistency._get_data", "clash_triage._get_data")]
)
def test_loader_refuses_an_empty_snapshot_id(ws, name):
    with pytest.raises(ValueError, match=PLAIN):
        LOADERS[name]("", ws)


@pytest.mark.parametrize("raw", BAD_IDS)
def test_store_snapshot_file_refuses_a_hostile_snapshot_id(ws, raw):
    source = ws.outside / "source.json"
    source.write_text("{}", encoding="utf-8")
    before = sorted(p.name for p in ws.outside.rglob("*"))
    with pytest.raises(ValueError, match=PLAIN):
        engine._store_snapshot_file(ws, _bad(ws, raw), source)
    assert sorted(p.name for p in ws.outside.rglob("*")) == before


def test_store_snapshot_file_copies_for_a_real_id(ws):
    source = ws.outside / "source.json"
    source.write_text('{"a": 1}', encoding="utf-8")
    engine._store_snapshot_file(ws, "0123456789abcdef0123456789abcdef", source)
    assert (ws.root / "snapshots" / "0123456789abcdef0123456789abcdef.json").read_text(encoding="utf-8") == '{"a": 1}'


def test_real_snapshot_id_still_loads_everywhere(ws):
    assert familytype_mapper._load_snapshot("snap1", ws)["snapshot_id"] == "x"
    assert model_bloat._load_snapshot("snap1", ws)["snapshot_id"] == "x"
    assert model_inspector._load_snapshot("snap1", ws)["snapshot_id"] == "x"
    assert model_changes._load("snap1", ws)["snapshot_id"] == "x"
    assert warnings_triage._load_snapshot("snap1", ws)["snapshot_id"] == "x"
    assert selection_tools._load_snapshot("snap1", ws)["snapshot_id"] == "x"
    assert naming_checker.NamingCheckerModule()._load_snapshot("snap1", ws)["snapshot_id"] == "x"
    assert links_worksets_audit.LinksWorksetsAuditModule._load_elements("snap1", ws) == []
    assert schedule_consistency.ScheduleConsistencyModule()._get_data("snap1", ws)[0] == []
    with pytest.raises(ValueError, match="not found"):
        familytype_mapper._load_snapshot("missing", ws)


RAW_JOIN = re.compile(r"""f["']\{snapshot_id\}\.json["']""")


def test_no_raw_snapshot_id_json_join_under_modules_or_semantic():
    offenders = []
    for folder in ("modules", "semantic"):
        for path in (SRC / folder).rglob("*.py"):
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if RAW_JOIN.search(line):
                    offenders.append(f"{path.relative_to(SRC)}:{n}")
    assert not offenders, "use security.safe_paths.snapshot_file instead: " + ", ".join(offenders)
