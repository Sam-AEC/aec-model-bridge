"""Tests for Phase 10 — QA/QC Checker module (W7, W9)."""
import importlib.util
import pytest
from pathlib import Path
from revit_mcp_server.semantic.engine import generate_mock_snapshot


def _load_mod(relpath: str, name: str):
    p = Path(__file__).parent.parent / relpath
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_qaqc = _load_mod("src/revit_mcp_server/modules/qaqc_checker/module.py", "_qaqc_impl")
QaqcCheckerModule = _qaqc.QaqcCheckerModule


class MockWorkspace:
    def __init__(self, tmp_path: Path):
        self.allowed_directories = [tmp_path]


@pytest.fixture
def workspace(tmp_path):
    return MockWorkspace(tmp_path)


@pytest.fixture
def module():
    return QaqcCheckerModule()


@pytest.fixture
def snap_and_ws(tmp_path):
    ws = MockWorkspace(tmp_path)
    snap = generate_mock_snapshot()
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap_path = snap_dir / f"{snap.snapshot_id}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        f.write(snap.model_dump_json(by_alias=True, indent=2))
    return snap, ws


# --- Rule listing ---

def test_list_rules_core(module):
    result = module.list_rules(rule_pack="core")
    assert result["rules_count"] >= 10
    rule_ids = {r["id"] for r in result["rules"]}
    assert "room_not_placed" in rule_ids
    assert "door_missing_mark" in rule_ids
    assert "room_missing_number" in rule_ids


# --- Run check ---

def test_run_check_mock_snapshot(module, workspace):
    result = module.run_check(workspace=workspace)
    assert "total_findings" in result
    assert result["rules_run"] >= 10
    assert "by_severity" in result
    assert "error" in result["by_severity"]
    assert "warning" in result["by_severity"]
    assert "info" in result["by_severity"]
    # Check structure of findings
    for f in result["findings"]:
        assert "rule_id" in f
        assert "severity" in f
        assert "message" in f


def test_run_check_detects_unplaced_room(module, workspace):
    result = module.run_check(workspace=workspace)
    findings_by_rule = {f["rule_id"] for f in result["findings"]}
    # Mock snapshot has 1 unplaced room
    assert "room_not_placed" in findings_by_rule


def test_run_check_detects_missing_room_name(module, workspace):
    result = module.run_check(workspace=workspace)
    findings_by_rule = {f["rule_id"] for f in result["findings"]}
    # Mock snapshot rooms have no Name parameter → room_missing_name fires
    assert "room_missing_name" in findings_by_rule


def test_run_check_with_snapshot(module, snap_and_ws):
    snap, ws = snap_and_ws
    result = module.run_check(snapshot_id=snap.snapshot_id, workspace=ws)
    assert result["total_findings"] >= 1


# --- Issue store ---

def test_issues_persist_after_run(module, workspace):
    module.run_check(workspace=workspace)
    issues = module.list_issues(workspace=workspace)
    assert issues["total"] >= 1
    assert all("rule_id" in i for i in issues["issues"])
    assert all("status" in i for i in issues["issues"])
    assert all(i["status"] == "open" for i in issues["issues"])


def test_filter_issues_by_severity(module, workspace):
    module.run_check(workspace=workspace)
    errors = module.list_issues(severity="error", workspace=workspace)
    warnings = module.list_issues(severity="warning", workspace=workspace)
    assert all(i["severity"] == "error" for i in errors["issues"])
    assert all(i["severity"] == "warning" for i in warnings["issues"])


def test_resolve_issue(module, workspace):
    module.run_check(workspace=workspace)
    all_issues = module.list_issues(workspace=workspace)
    
    if not all_issues["issues"]:
        pytest.skip("No issues generated from mock snapshot")
    
    issue_id = all_issues["issues"][0]["id"]
    res = module.resolve_issue(issue_id=issue_id, workspace=workspace)
    assert res["status"] == "resolved"
    
    # Verify
    resolved = module.list_issues(status="resolved", workspace=workspace)
    assert any(i["id"] == issue_id for i in resolved["issues"])


def test_second_run_resolves_fixed_issues(module, workspace):
    """Running check twice with the same snapshot should keep issues open (not resolve them)."""
    module.run_check(workspace=workspace)
    first_count = module.list_issues(status="open", workspace=workspace)["total"]
    
    module.run_check(workspace=workspace)
    second_count = module.list_issues(status="open", workspace=workspace)["total"]
    
    # Same defects → same open count
    assert first_count == second_count


def test_resolve_nonexistent_issue_raises(module, workspace):
    # Ensure DB exists first
    module.run_check(workspace=workspace)
    with pytest.raises(ValueError, match="not found"):
        module.resolve_issue(issue_id="does-not-exist", workspace=workspace)


def test_run_check_without_snapshot_rejected_in_bridge_mode(module, workspace, monkeypatch):
    from revit_mcp_server.config import BridgeMode, config

    monkeypatch.setattr(config, "mode", BridgeMode.bridge)
    with pytest.raises(ValueError, match="requires a snapshot_id"):
        module.run_check(snapshot_id="", workspace=workspace)


# --- Shareable rule packs ---

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_PACK = REPO_ROOT / "rule_packs" / "examples" / "door-room-basics.yaml"

VALID_PACK = """rules:
  - id: door_mark_missing
    severity: warning
    description: "Door has no Mark."
    filter:
      category: OST_Doors
      parameter: {name: Mark, empty: true}
    assertion: "element_count == 0"
"""


def _write(ws, rel, text):
    p = ws.allowed_directories[0] / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_example_pack_is_valid_and_ships(module, workspace):
    ws_copy = _write(workspace, "door-room-basics.yaml", EXAMPLE_PACK.read_text(encoding="utf-8"))
    result = module.validate_rule_pack(path=str(ws_copy), workspace=workspace)
    assert result["valid"], result["errors"]
    assert result["rules_count"] == 3


def test_builtin_core_pack_validates(module, workspace):
    assert module.validate_rule_pack(rule_pack="core", workspace=workspace)["valid"]


def test_pack_runs_preserve_other_packs_and_refresh_their_own_findings(module, workspace, monkeypatch):
    monkeypatch.setattr(module, "_get_data", lambda *args: ([{"uid": "door-1", "category": "OST_Doors", "params": {}}], []))
    _write(workspace, "rule_packs/alpha.yaml", VALID_PACK)
    _write(workspace, "rule_packs/beta.yaml", VALID_PACK.replace("warning", "error").replace("Door has no Mark.", "Beta message."))
    module.run_check(rule_pack="alpha", workspace=workspace)
    alpha = module.list_issues(workspace=workspace)["issues"][0]
    module.run_check(rule_pack="beta", workspace=workspace)
    issues = module.list_issues(status="open", workspace=workspace)["issues"]
    assert len(issues) == 2
    assert {(i["rule_pack"], i["message"], i["severity"]) for i in issues} == {
        ("alpha", "Door has no Mark.", "warning"), ("beta", "Beta message.", "error"),
    }
    # Fix beta's matches; alpha still owns its open issue with the same rule ID.
    _write(workspace, "rule_packs/beta.yaml", VALID_PACK.replace("OST_Doors", "OST_Windows"))
    module.run_check(rule_pack="beta", workspace=workspace)
    assert [i["id"] for i in module.list_issues(status="open", workspace=workspace)["issues"]] == [alpha["id"]]
    _write(workspace, "rule_packs/alpha.yaml", VALID_PACK.replace("warning", "error").replace("Door has no Mark.", "Updated alpha."))
    module.run_check(rule_pack="alpha", workspace=workspace)
    updated = module.list_issues(status="open", workspace=workspace)["issues"][0]
    assert (updated["id"], updated["message"], updated["severity"]) == (alpha["id"], "Updated alpha.", "error")


def test_legacy_issue_database_migrates_without_losing_history(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.execute("""CREATE TABLE issues (
        id TEXT PRIMARY KEY, doc_guid TEXT NOT NULL, rule_id TEXT NOT NULL,
        severity TEXT NOT NULL, element_uid TEXT, label TEXT, message TEXT NOT NULL,
        fix_template TEXT, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)""")
    conn.execute("INSERT INTO issues VALUES ('old', 'doc', 'door', 'warning', 'uid', '', 'Keep me', '', 'open', 't', 't')")
    _qaqc._ensure_schema(conn)
    _qaqc._ensure_schema(conn)  # migration is idempotent
    assert conn.execute("SELECT id, rule_pack, message, status FROM issues").fetchall() == [("old", "core", "Keep me", "open")]
    conn.close()


def test_family_source_combinations_are_rejected_before_running(module, workspace):
    pack = VALID_PACK.replace("category: OST_Doors", "family_source: inplace")
    src = _write(workspace, "mixed.yaml", pack)
    result = module.validate_rule_pack(path=str(src), workspace=workspace)
    assert not result["valid"]
    assert any(e["field"] == "filter.family_source" and "cannot be combined" in e["message"] for e in result["errors"])
    with pytest.raises(ValueError, match="invalid rule pack"):
        module.import_rule_pack(source_path=str(src), workspace=workspace)


def test_validate_reports_actionable_errors_per_rule(module, workspace):
    p = _write(workspace, "bad.yaml", """rules:
  - id: ok_rule
    severity: error
    description: fine
    filter: {category: OST_Doors}
  - id: ok_rule
    severity: fatal
    filter:
      regex: "^D-"
      parameter: {name: Mark}
    assertion: "something else"
  - severity: error
""")
    r = module.validate_rule_pack(path=str(p), workspace=workspace)
    assert not r["valid"]
    msgs = [(e["rule_id"], e["field"], e["message"]) for e in r["errors"]]
    assert any(f == "id" and "Duplicate" in m for _, f, m in msgs)
    assert any(f == "severity" and "one of" in m for _, f, m in msgs)
    assert any(f == "description" for _, f, _ in msgs)
    assert any(f == "filter.regex" and "Unknown filter operator" in m for _, f, m in msgs)
    assert any(f == "filter.parameter" and "exactly one" in m for _, f, m in msgs)
    assert any(f == "assertion" and "Unknown assertion" in m for _, f, m in msgs)
    assert any(f == "id" and rid == "rules[2]" for rid, f, _ in msgs)


def test_validate_handles_non_yaml_and_wrong_shape(module, workspace):
    assert not module.validate_rule_pack(path=str(_write(workspace, "a.yaml", "rules: [")), workspace=workspace)["valid"]
    assert not module.validate_rule_pack(path=str(_write(workspace, "b.yaml", "- 1\n- 2\n")), workspace=workspace)["valid"]
    assert not module.validate_rule_pack(path=str(_write(workspace, "c.yaml", "rules: []\n")), workspace=workspace)["valid"]


def test_validate_does_not_execute_python_tags(module, workspace):
    p = _write(workspace, "evil.yaml", "rules: !!python/object/apply:os.system ['echo hi']\n")
    r = module.validate_rule_pack(path=str(p), workspace=workspace)
    assert not r["valid"]


def test_validate_rejects_path_outside_workspace(module, workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "x.yaml"
    outside.write_text(VALID_PACK, encoding="utf-8")
    with pytest.raises(Exception, match="outside the allowed workspace"):
        module.validate_rule_pack(path=str(outside), workspace=workspace)


def test_import_then_list_and_run_check_with_user_pack(module, workspace):
    src = _write(workspace, "incoming/firm.yaml", VALID_PACK)
    res = module.import_rule_pack(source_path=str(src), workspace=workspace)
    assert res["status"] == "imported"
    dest = workspace.allowed_directories[0] / "rule_packs" / "firm.yaml"
    assert dest.read_text(encoding="utf-8") == VALID_PACK

    packs = {p["name"]: p for p in module.list_rule_packs(workspace=workspace)["packs"]}
    assert packs["core"]["source"] == "builtin"
    assert packs["firm"]["source"] == "user" and packs["firm"]["valid"]

    assert module.list_rules(rule_pack="firm", workspace=workspace)["rules_count"] == 1
    result = module.run_check(rule_pack="firm", workspace=workspace)
    assert result["rule_pack"] == "firm"
    assert result["rules_run"] == 1


def test_import_refuses_invalid_pack(module, workspace):
    src = _write(workspace, "bad.yaml", "rules:\n  - id: x\n    severity: nope\n")
    with pytest.raises(ValueError, match="invalid"):
        module.import_rule_pack(source_path=str(src), workspace=workspace)
    assert not (workspace.allowed_directories[0] / "rule_packs" / "bad.yaml").exists()


def test_import_refuses_overwrite_unless_flag(module, workspace):
    src = _write(workspace, "firm.yaml", VALID_PACK)
    module.import_rule_pack(source_path=str(src), workspace=workspace)
    with pytest.raises(ValueError, match="overwrite=true"):
        module.import_rule_pack(source_path=str(src), workspace=workspace)
    assert module.import_rule_pack(source_path=str(src), overwrite=True, workspace=workspace)["status"] == "imported"


def test_import_refuses_builtin_name_and_bad_names(module, workspace):
    src = _write(workspace, "core.yaml", VALID_PACK)
    with pytest.raises(ValueError, match="built-in"):
        module.import_rule_pack(source_path=str(src), overwrite=True, workspace=workspace)
    for bad in ("../evil", "a/b", "..", ".hidden", "x" * 80):
        with pytest.raises(ValueError, match="Invalid rule pack name"):
            module.import_rule_pack(source_path=str(src), name=bad, workspace=workspace)


def test_import_rejects_source_outside_workspace(module, workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside2") / "x.yaml"
    outside.write_text(VALID_PACK, encoding="utf-8")
    with pytest.raises(Exception, match="outside the allowed workspace"):
        module.import_rule_pack(source_path=str(outside), workspace=workspace)
    traversal = workspace.allowed_directories[0] / ".." / outside.parent.name / "x.yaml"
    with pytest.raises(Exception, match="outside the allowed workspace"):
        module.import_rule_pack(source_path=str(traversal), workspace=workspace)


def test_run_check_rejects_traversal_pack_names(module, workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside3") / "evil.yaml"
    outside.write_text(VALID_PACK, encoding="utf-8")
    for bad in (str(outside), "../evil", "rule_packs/../../evil", "..\\evil"):
        with pytest.raises(ValueError, match="Invalid rule pack name"):
            module.run_check(rule_pack=bad, workspace=workspace)


def test_run_check_unknown_pack_and_invalid_user_pack(module, workspace):
    with pytest.raises(ValueError, match="not found"):
        module.run_check(rule_pack="nope", workspace=workspace)
    _write(workspace, "rule_packs/broken.yaml", "rules:\n  - id: x\n")
    with pytest.raises(ValueError, match="invalid"):
        module.run_check(rule_pack="broken", workspace=workspace)


def test_user_pack_cannot_shadow_builtin(module, workspace):
    _write(workspace, "rule_packs/core.yaml", VALID_PACK)
    assert module.list_rules(rule_pack="core", workspace=workspace)["rules_count"] >= 10


def test_export_builtin_and_user_pack(module, workspace):
    res = module.export_rule_pack(rule_pack="core", workspace=workspace)
    out = workspace.allowed_directories[0] / "exports" / "core.yaml"
    assert out.is_file() and res["rules_count"] >= 10
    with pytest.raises(ValueError, match="overwrite=true"):
        module.export_rule_pack(rule_pack="core", workspace=workspace)
    module.export_rule_pack(rule_pack="core", overwrite=True, workspace=workspace)

    _write(workspace, "rule_packs/firm.yaml", VALID_PACK)
    dest = workspace.allowed_directories[0] / "share"
    dest.mkdir()
    module.export_rule_pack(rule_pack="firm", destination=str(dest), workspace=workspace)
    assert (dest / "firm.yaml").read_text(encoding="utf-8") == VALID_PACK


def test_export_rejects_destination_outside_workspace(module, workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside4")
    with pytest.raises(Exception, match="outside the allowed workspace"):
        module.export_rule_pack(rule_pack="core", destination=str(outside / "core.yaml"), workspace=workspace)
    traversal = workspace.allowed_directories[0] / ".." / outside.name / "core.yaml"
    with pytest.raises(Exception, match="outside the allowed workspace"):
        module.export_rule_pack(rule_pack="core", destination=str(traversal), workspace=workspace)
    assert not (outside / "core.yaml").exists()
    with pytest.raises(ValueError, match="Invalid rule pack name"):
        module.export_rule_pack(rule_pack="../core", workspace=workspace)


def test_symlinked_user_pack_escaping_workspace_is_refused(module, workspace, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside5") / "evil.yaml"
    outside.write_text(VALID_PACK, encoding="utf-8")
    link = workspace.allowed_directories[0] / "rule_packs" / "link.yaml"
    link.parent.mkdir()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(Exception, match="outside the allowed workspace"):
        module.run_check(rule_pack="link", workspace=workspace)
    assert "link" not in {p["name"] for p in module.list_rule_packs(workspace=workspace)["packs"]}


def test_heijmans_derived_pack_is_valid():
    import yaml


    pack = REPO_ROOT / "rule_packs" / "heijmans-derived.yaml"
    result = _qaqc._validate_pack_data(yaml.safe_load(pack.read_text(encoding="utf-8")))
    assert result["errors"] == [] and result["rules_count"] == 5


def test_naming_check_reads_type_names_with_ename():
    # Live (Revit 2024): `type.Name` raised in IronPython, the script returned '' and every one of 13809 walls was
    # reported as off pattern.
    source = (REPO_ROOT / "packages" / "mcp-server-revit" / "src" / "revit_mcp_server" / "modules" / "revit" / "scripts"
              / "check_naming_and_params.ipy").read_text(encoding="utf-8")
    assert "str(ename(el))" in source and "str(el.Name)" not in source


# --- Issue 143: issues tied to a snapshot, stale detection ---

import json as _json


def _write_snapshot(ws, snapshot_id, door_uids, doc_guid="doc-143", taken_at="2026-11-01T10:00:00Z"):
    path = ws.allowed_directories[0] / "snapshots" / f"{snapshot_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "snapshot_id": snapshot_id,
        "taken_at": taken_at,
        "source": {"doc_guid": doc_guid},
        "elements": [{"uid": u, "category": "OST_Doors", "params": {}} for u in door_uids],
        "types": [],
    }
    path.write_text(_json.dumps(data), encoding="utf-8")


def _two_runs(module, workspace):
    uids = [f"door-{i}" for i in range(10)]
    _write_snapshot(workspace, "snap-a", uids, taken_at="2026-11-01T10:00:00Z")
    _write_snapshot(workspace, "snap-b", uids[3:], taken_at="2026-11-02T10:00:00Z")
    _write(workspace, "rule_packs/alpha.yaml", VALID_PACK)
    module.run_check(snapshot_id="snap-a", rule_pack="alpha", workspace=workspace)
    module.run_check(snapshot_id="snap-b", rule_pack="alpha", workspace=workspace)


def test_issue_acceptance_run_b_fixes_three_findings(module, workspace):
    _two_runs(module, workspace)
    current = module.list_issues(doc_guid="doc-143", workspace=workspace)
    assert current["total"] == 7
    assert {i["element_uid"] for i in current["issues"]} == {f"door-{i}" for i in range(3, 10)}
    assert all(i["stale"] is False and i["snapshot_id"] == "snap-b" for i in current["issues"])
    everything = module.list_issues(doc_guid="doc-143", include_stale=True, workspace=workspace)
    assert everything["total"] == 10
    stale = [i for i in everything["issues"] if i["stale"]]
    assert {i["element_uid"] for i in stale} == {"door-0", "door-1", "door-2"}
    assert all(i["snapshot_id"] == "snap-a" and i["last_seen_at"] for i in stale)


def test_list_issues_reports_latest_run_snapshot_and_capture_time(module, workspace):
    _two_runs(module, workspace)
    result = module.list_issues(doc_guid="doc-143", workspace=workspace)
    assert result["latest_run"]["snapshot_id"] == "snap-b"
    assert result["latest_run"]["captured_at"] == "2026-11-02T10:00:00Z"
    assert result["latest_run"]["doc_guid"] == "doc-143"


def test_list_issues_snapshot_id_filter(module, workspace):
    _two_runs(module, workspace)
    a = module.list_issues(doc_guid="doc-143", snapshot_id="snap-a", include_stale=True, workspace=workspace)
    assert a["total"] == 3
    b = module.list_issues(doc_guid="doc-143", snapshot_id="snap-b", workspace=workspace)
    assert b["total"] == 7
    # A stale-only snapshot is hidden unless include_stale is set.
    assert module.list_issues(doc_guid="doc-143", snapshot_id="snap-a", workspace=workspace)["total"] == 0


def test_explicit_resolved_or_orphaned_status_still_lists_fixed_rows(module, workspace):
    _two_runs(module, workspace)
    # The removed doors are gone from snap-b, so the run orphans them.
    orphaned = module.list_issues(doc_guid="doc-143", status="orphaned", workspace=workspace)
    assert orphaned["total"] == 3
    assert all(i["stale"] for i in orphaned["issues"])


def test_stale_is_tracked_per_document_and_pack(module, workspace):
    _two_runs(module, workspace)
    _write_snapshot(workspace, "snap-other", ["x-1", "x-2"], doc_guid="doc-other")
    module.run_check(snapshot_id="snap-other", rule_pack="alpha", workspace=workspace)
    # A run on another document must not make doc-143 issues stale.
    assert module.list_issues(doc_guid="doc-143", workspace=workspace)["total"] == 7
    assert module.list_issues(doc_guid="doc-other", workspace=workspace)["total"] == 2
    # Another pack's run on the same document does not make alpha rows stale.
    _write(workspace, "rule_packs/beta.yaml", VALID_PACK.replace("door_mark_missing", "beta_rule"))
    module.run_check(snapshot_id="snap-b", rule_pack="beta", workspace=workspace)
    alpha = module.list_issues(doc_guid="doc-143", include_stale=True, workspace=workspace)["issues"]
    assert sum(1 for i in alpha if i["rule_pack"] == "alpha" and not i["stale"]) == 7


def test_mock_run_without_snapshot_shows_unknown_snapshot(module, workspace):
    module.run_check(workspace=workspace)
    result = module.list_issues(workspace=workspace)
    assert result["total"] >= 1
    assert all(i["snapshot_id"] == "unknown" and i["stale"] is False for i in result["issues"])
    assert result["latest_run"]["snapshot_id"] == "unknown"


def test_database_from_1_5_0_opens_and_old_rows_show_unknown_snapshot(module, workspace):
    import sqlite3

    # Exact 1.5.0 schema: rule_pack present, no snapshot_id / last_seen_at.
    conn = sqlite3.connect(workspace.allowed_directories[0] / "qaqc_issues.db")
    conn.execute("""CREATE TABLE issues (
        id TEXT PRIMARY KEY, doc_guid TEXT NOT NULL, rule_pack TEXT NOT NULL DEFAULT 'core',
        rule_id TEXT NOT NULL, severity TEXT NOT NULL, element_uid TEXT, label TEXT,
        message TEXT NOT NULL, fix_template TEXT, status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    conn.execute("INSERT INTO issues VALUES ('old1', 'doc-143', 'alpha', 'door_mark_missing', 'warning', 'door-0', '', 'Old', '', 'open', 't', 't')")
    conn.execute("INSERT INTO issues VALUES ('old2', 'doc-143', 'alpha', 'door_mark_missing', 'warning', 'door-9', '', 'Old', '', 'open', 't', 't')")
    conn.commit()
    conn.close()

    before = module.list_issues(doc_guid="doc-143", workspace=workspace)
    assert before["total"] == 2  # no run recorded yet: nothing can be called stale
    assert all(i["snapshot_id"] == "unknown" and i["last_seen_at"] is None and i["stale"] is False for i in before["issues"])
    assert before["latest_run"] is None

    _write_snapshot(workspace, "snap-new", ["door-9"])
    _write(workspace, "rule_packs/alpha.yaml", VALID_PACK)
    module.run_check(snapshot_id="snap-new", rule_pack="alpha", workspace=workspace)
    after = module.list_issues(doc_guid="doc-143", include_stale=True, workspace=workspace)
    by_id = {i["id"]: i for i in after["issues"]}
    assert by_id["old2"]["snapshot_id"] == "snap-new" and by_id["old2"]["stale"] is False
    assert by_id["old1"]["snapshot_id"] == "unknown" and by_id["old1"]["stale"] is True
    assert module.list_issues(doc_guid="doc-143", workspace=workspace)["total"] == 1


def test_list_issues_schema_declares_snapshot_id_and_include_stale():
    mod_json = _json.loads(
        (Path(__file__).parent.parent / "src/revit_mcp_server/modules/qaqc_checker/module.json").read_text(encoding="utf-8")
    )
    cmd = next(c for c in mod_json["commands"] if c["id"] == "list_issues")
    props = cmd["input_schema"]["properties"]
    assert props["snapshot_id"]["type"] == "string"
    assert props["include_stale"]["type"] == "boolean"
