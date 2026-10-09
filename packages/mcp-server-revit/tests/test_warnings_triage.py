"""Tests for the warnings_triage module (read-only Revit warnings triage)."""
import importlib.util
from pathlib import Path

import pytest

from revit_mcp_server.config import Config
from revit_mcp_server.module_registry import ModuleRegistry
from revit_mcp_server.providers.module_provider import ModuleProvider
from revit_mcp_server.security.workspace import WorkspaceMonitor
from revit_mcp_server.semantic.engine import generate_mock_snapshot


def _load(relpath, name):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_wt = _load("src/revit_mcp_server/modules/warnings_triage/module.py", "_wt_impl")
WarningsTriageModule = _wt.WarningsTriageModule


class WS:
    def __init__(self, p):
        self.allowed_directories = [p]


# Mixed fixture shaped like the add-in's revit.get_warnings output.
FIXTURE = {
    "count": 7,
    "warnings": [
        {"description": "Elements have duplicate 'Mark' values.", "severity": "Warning", "failing_elements": [100, 101]},
        {"description": "Elements have duplicate 'Mark' values.", "severity": "Warning", "failing_elements": [101, 200]},
        {"description": "Highlighted walls overlap.", "severity": "Warning", "failing_elements": [300, 400, 401, 9999]},
        {"description": "Room is not in a properly enclosed region.", "severity": "Warning", "failing_elements": [200]},
        {"description": "Highlighted walls are slightly off axis.", "severity": "Warning", "failing_elements": [300]},
        {"description": "Something unexpected happened", "severity": "Error", "failing_elements": []},
        {"description": "There are identical instances in the same place.", "severity": "Warning", "failing_elements": [100, 101, 200, 300, 400]},
    ],
}


def _default_executor(name, args):
    if name == "revit_get_document_info":
        return {"title": "Mock_Project.rvt"}
    return FIXTURE


def run(**kw):
    ex = kw.pop("tool_executor", _default_executor)
    return WarningsTriageModule().review_warnings(tool_executor=ex, **kw)


def test_groups_and_ranking():
    r = run()
    assert r["ok"] and r["read_only"]
    assert r["total_warnings"] == 7
    assert r["total_groups"] == 6
    counts = [g["elements_affected"] for g in r["groups"]]
    assert counts == sorted(counts, reverse=True)
    assert r["groups"][0]["elements_affected"] == 5 and r["groups"][0]["rank"] == 1
    dup = next(g for g in r["groups"] if g["family"] == "duplicate_mark")
    assert dup["warning_count"] == 2 and dup["elements_affected"] == 3  # 101 deduped


def test_coordinator_flags_and_next_steps():
    r = run()
    fam = {g["family"] for g in r["groups"]}
    assert {"duplicate_mark", "overlapping_elements", "room_not_enclosed"} <= fam
    flagged = {g["family"] for g in r["groups"] if g["coordinator_relevant"]}
    assert flagged == {"duplicate_mark", "overlapping_elements", "room_not_enclosed"}
    others = [g for g in r["groups"] if g["family"] == "other"]
    assert len(others) == 2 and not any(g["coordinator_relevant"] for g in others)
    assert all(g["next_step"] for g in r["groups"])
    assert r["coordinator_groups"] == 4  # identical instances + overlap + mark + room


def test_coordinator_only_and_top():
    r = run(coordinator_only=True)
    assert r["groups"] and all(g["coordinator_relevant"] for g in r["groups"])
    assert len(run(top=2)["groups"]) == 2


def test_unique_ids_from_snapshot(tmp_path):
    snap = generate_mock_snapshot()
    d = tmp_path / "snapshots"
    d.mkdir()
    (d / f"{snap.snapshot_id}.json").write_text(snap.model_dump_json(by_alias=True), encoding="utf-8")
    uid = {e.element_id: e.uid for e in snap.elements}
    r = run(snapshot_id=snap.snapshot_id, workspace=WS(tmp_path))
    assert r["unique_ids_available"]
    ov = next(g for g in r["groups"] if g["description"] == "Highlighted walls overlap.")
    assert set(ov["element_unique_ids"]) == {uid[300], uid[400], uid[401]}
    assert ov["element_ids_without_unique_id"] == [9999]


def _write_snapshot(tmp_path):
    snap = generate_mock_snapshot()
    d = tmp_path / "snapshots"
    d.mkdir(exist_ok=True)
    (d / f"{snap.snapshot_id}.json").write_text(snap.model_dump_json(by_alias=True), encoding="utf-8")
    return snap


def test_snapshot_id_cannot_escape_snapshots_dir(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text('{"elements": [{"element_id": 100, "uid": "LEAK"}]}', encoding="utf-8")
    (tmp_path / "snapshots").mkdir()
    for bad in ("../outside", str(tmp_path / "outside"), "..\\outside"):
        with pytest.raises(ValueError):
            run(snapshot_id=bad, workspace=WS(tmp_path))


def test_snapshot_from_other_document_is_not_mapped(tmp_path):
    snap = _write_snapshot(tmp_path)
    other = lambda n, a: {"title": "Other_Project.rvt"} if n == "revit_get_document_info" else FIXTURE  # noqa: E731
    r = run(snapshot_id=snap.snapshot_id, workspace=WS(tmp_path), tool_executor=other)
    assert not r["unique_ids_available"]
    assert all(g["element_unique_ids"] == [] for g in r["groups"])
    assert any("different" in n.lower() for n in r["notes"])


def test_unverifiable_document_identity_is_not_mapped(tmp_path):
    snap = _write_snapshot(tmp_path)
    nodoc = lambda n, a: FIXTURE  # noqa: E731
    r = run(snapshot_id=snap.snapshot_id, workspace=WS(tmp_path), tool_executor=nodoc)
    assert not r["unique_ids_available"]


def test_element_cap_is_shared_across_both_lists(tmp_path):
    snap = _write_snapshot(tmp_path)
    r = run(snapshot_id=snap.snapshot_id, workspace=WS(tmp_path), max_elements_per_group=2)
    for g in r["groups"]:
        assert len(g["element_unique_ids"]) + len(g["element_ids_without_unique_id"]) <= 2
    ov = next(g for g in r["groups"] if g["description"] == "Highlighted walls overlap.")
    assert ov["element_list_truncated"]


def test_without_snapshot_lists_revit_ids():
    r = run()
    assert not r["unique_ids_available"] and r["notes"]
    g = r["groups"][0]
    assert g["element_unique_ids"] == [] and g["element_ids_without_unique_id"]


def test_truncation_and_wrapped_response():
    r = run(max_elements_per_group=2, tool_executor=lambda n, a: {"data": FIXTURE})
    g = r["groups"][0]
    assert g["element_list_truncated"] and len(g["element_ids_without_unique_id"]) == 2
    assert g["elements_affected"] == 5


def test_no_revit_connection_says_what_is_missing():
    r = WarningsTriageModule().review_warnings()
    assert r["ok"] is False and "revit_get_warnings" in r["missing_data"]


def test_empty_warnings():
    r = run(tool_executor=lambda n, a: {"warnings": [], "count": 0})
    assert r["ok"] and r["groups"] == [] and r["total_warnings"] == 0


@pytest.mark.anyio
async def test_registered_as_read_only_tool(tmp_path):
    cfg = Config(
        workspace_dir=tmp_path,
        allowed_directories=[tmp_path],
        audit_log=tmp_path / "audit.log",
        enable_user_modules=False,
    )
    registry = ModuleRegistry(config_obj=cfg)
    registry.discover_and_load()
    provider = ModuleProvider(module_registry=registry, workspace=WorkspaceMonitor([tmp_path]))
    caps = {c.name: c for c in provider.get_capabilities()}
    assert "warnings_triage_review_warnings" in caps
    assert not caps["warnings_triage_review_warnings"].is_mutating
