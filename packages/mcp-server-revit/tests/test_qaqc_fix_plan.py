"""Tests for qaqc_checker draft_fix_plan (issue 187). Drafts only; nothing is written to the model."""
import json
import sqlite3
from pathlib import Path

import pytest
import yaml

import revit_mcp_server
from revit_mcp_server.modules.qaqc_checker.module import QaqcCheckerModule, _validate_pack_data

Mod = QaqcCheckerModule


class WS:
    def __init__(self, p):
        self.allowed_directories = [p]


def door(i, mark=None, rating=None):
    params = {}
    if mark is not None:
        params["Mark"] = {"v": mark}
    if rating is not None:
        params["FireRating"] = {"v": rating}
    return {"uid": f"d{i}", "element_id": 2000 + i, "category": "OST_Doors", "type_name": "Door", "params": params}


def room(i):
    return {"uid": f"r{i}", "element_id": 1000 + i, "category": "OST_Rooms", "type_name": "Room",
            "level_uid": "L1", "params": {}}


RULES = [
    {"id": "door_no_rating", "severity": "warning", "description": "Door has no fire rating.",
     "filter": {"category": "OST_Doors", "parameter": {"name": "FireRating", "empty": True}},
     "fix": {"parameter": "FireRating", "value": "30"}},
    {"id": "door_no_mark", "severity": "warning", "description": "Door has no mark.",
     "filter": {"category": "OST_Doors", "parameter": {"name": "Mark", "empty": True}},
     "fix_template": "Set a Mark for the door."},
    {"id": "room_no_name", "severity": "warning", "description": "Room has no name.",
     "filter": {"category": "OST_Rooms", "parameter": {"name": "Name", "empty": True}},
     "fix": {"parameter": "Name", "value": "Unassigned"}},
]


@pytest.fixture
def env(tmp_path):
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "rule_packs").mkdir()
    (tmp_path / "rule_packs" / "fixes.yaml").write_text(yaml.safe_dump({"rules": RULES}), encoding="utf-8")
    return tmp_path


def snapshot(env, name="s1", doc="doc-A", elements=None):
    els = elements if elements is not None else [door(1), door(2, mark="D2"), room(1)]
    (env / "snapshots" / f"{name}.json").write_text(
        json.dumps({"source": {"doc_guid": doc}, "elements": els, "types": []}), encoding="utf-8")
    return name


def ids_of(env):
    issues = Mod().list_issues(workspace=WS(env))["issues"]
    return {(i["rule_id"], i["element_uid"]): i["id"] for i in issues}


def check(env, name="s1"):
    res = Mod().run_check(snapshot_id=name, rule_pack="fixes", workspace=WS(env))
    return res, ids_of(env)


def draft(env, ids, **kw):
    return Mod().draft_fix_plan(issue_ids=ids, workspace=WS(env), **kw)


def sql(env, query, args=()):
    conn = sqlite3.connect(str(env / "qaqc_issues.db"))
    conn.execute(query, args)
    conn.commit()
    conn.close()


def test_fix_field_is_validated():
    assert _validate_pack_data({"rules": [dict(RULES[0])]})["errors"] == []
    for bad in ({"parameter": "", "value": "x"}, {"parameter": "P"}, {"parameter": "P", "value": ["x"]},
                {"parameter": "P", "value": ""}, {"value": "x"}, {"parameter": "P", "value": "x", "extra": 1},
                "set P"):
        errs = _validate_pack_data({"rules": [dict(RULES[0], fix=bad)]})["errors"]
        assert errs and errs[0]["field"] == "fix", bad


def test_findings_and_issues_carry_the_fix(env):
    snapshot(env)
    res, _ = check(env)
    with_fix = [f for f in res["findings"] if f["rule_id"] == "door_no_rating"]
    assert with_fix and all(f["fix"] == {"parameter": "FireRating", "value": "30"} for f in with_fix)
    assert all("fix" not in f for f in res["findings"] if f["rule_id"] == "door_no_mark")
    by_rule = {i["rule_id"]: i for i in Mod().list_issues(workspace=WS(env))["issues"]}
    assert by_rule["door_no_rating"]["fix"] == {"parameter": "FireRating", "value": "30"}
    assert by_rule["door_no_mark"]["fix"] is None
    assert "fix_json" not in by_rule["door_no_rating"]


def test_one_action_per_finding_in_one_pending_draft(env):
    snapshot(env)
    _, ids = check(env)
    sel = [ids[("door_no_rating", "d1")], ids[("door_no_rating", "d2")], ids[("room_no_name", "r1")]]
    out = draft(env, sel)
    assert out["requires_approval"] is True and out["read_only"] is True
    assert out["plan_type"] == "action_plan_draft"
    assert out["actions"] == [
        {"tool": "revit_set_parameter_value",
         "arguments": {"element_id": 2001, "parameter_name": "FireRating", "value": "30"}},
        {"tool": "revit_set_parameter_value",
         "arguments": {"element_id": 2002, "parameter_name": "FireRating", "value": "30"}},
        {"tool": "revit_set_parameter_value",
         "arguments": {"element_id": 1001, "parameter_name": "Name", "value": "Unassigned"}},
    ]
    assert out["skipped"] == []
    assert out["snapshot_id"] == "s1" and out["doc_guid"] == "doc-A"
    assert out["plan_arguments"]["snapshot_id"] == "s1"
    assert out["plan_arguments"]["actions"] == out["actions"]
    assert "plan_actions" in out["next_step"] and "approve" in out["next_step"].lower()


def test_findings_without_fix_are_listed_and_make_no_action(env):
    snapshot(env)
    _, ids = check(env)
    out = draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_mark", "d1")]])
    assert len(out["actions"]) == 1
    assert [s["issue_id"] for s in out["skipped"]] == [ids[("door_no_mark", "d1")]]
    assert "no fix" in out["skipped"][0]["reason"]
    assert out["skipped"][0]["rule_id"] == "door_no_mark"
    assert out["plan_arguments"]["skipped"] == out["skipped"]


def test_nothing_to_fix_is_refused(env):
    snapshot(env)
    _, ids = check(env)
    with pytest.raises(ValueError, match="No selected finding has a fix"):
        draft(env, [ids[("door_no_mark", "d1")]])


def test_unknown_ids_refuse_the_whole_draft(env):
    snapshot(env)
    _, ids = check(env)
    with pytest.raises(ValueError, match="Unknown issue id.*nope"):
        draft(env, [ids[("door_no_rating", "d1")], "nope"])


@pytest.mark.parametrize("bad", [None, [], "abc", [1], [""], ["a"] * 201])
def test_bad_selection_is_refused(env, bad):
    snapshot(env)
    with pytest.raises(ValueError):
        draft(env, bad)


def test_duplicate_ids_count_once(env):
    snapshot(env)
    _, ids = check(env)
    i = ids[("door_no_rating", "d1")]
    assert len(draft(env, [i, i])["actions"]) == 1


def test_resolved_finding_is_refused(env):
    snapshot(env)
    _, ids = check(env)
    i = ids[("door_no_rating", "d1")]
    Mod().resolve_issue(issue_id=i, workspace=WS(env))
    with pytest.raises(ValueError, match="not open"):
        draft(env, [i])


def test_stale_finding_is_refused(env):
    snapshot(env)
    _, ids = check(env)
    j = ids[("door_no_rating", "d2")]
    sql(env, "UPDATE issues SET last_seen_at='2000-01-01' WHERE id=?", (j,))
    with pytest.raises(ValueError, match="stale"):
        draft(env, [j])


def test_mixed_snapshots_are_refused(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET snapshot_id='s2' WHERE id=?", (ids[("door_no_rating", "d1")],))
    with pytest.raises(ValueError, match="more than one snapshot"):
        draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_rating", "d2")]])


def test_finding_without_snapshot_is_refused(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET snapshot_id='' WHERE id=?", (ids[("door_no_rating", "d1")],))
    with pytest.raises(ValueError, match="no snapshot"):
        draft(env, [ids[("door_no_rating", "d1")]])


def test_documents_must_match(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET doc_guid='doc-B' WHERE id=?", (ids[("door_no_rating", "d1")],))
    with pytest.raises(ValueError, match="more than one model"):
        draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_rating", "d2")]])


def test_snapshot_id_argument_must_match_the_findings(env):
    snapshot(env)
    _, ids = check(env)
    with pytest.raises(ValueError, match="s1"):
        draft(env, [ids[("door_no_rating", "d1")]], snapshot_id="other")
    assert draft(env, [ids[("door_no_rating", "d1")]], snapshot_id="s1")["snapshot_id"] == "s1"


def test_snapshot_from_another_model_is_refused(env):
    snapshot(env)
    _, ids = check(env)
    snapshot(env, "s1", doc="doc-B")
    with pytest.raises(ValueError, match="different model"):
        draft(env, [ids[("door_no_rating", "d1")]])


def test_missing_snapshot_is_refused(env):
    snapshot(env)
    _, ids = check(env)
    (env / "snapshots" / "s1.json").unlink()
    with pytest.raises(ValueError, match="not found"):
        draft(env, [ids[("door_no_rating", "d1")]])


def test_element_missing_from_snapshot_is_skipped(env):
    snapshot(env)
    _, ids = check(env)
    snapshot(env, "s1", elements=[door(2, mark="D2"), room(1)])
    out = draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_rating", "d2")]])
    assert [a["arguments"]["element_id"] for a in out["actions"]] == [2002]
    assert "not in snapshot" in out["skipped"][0]["reason"]


def test_conflicting_fixes_for_one_parameter_are_refused(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET fix_json=? WHERE id=?",
        (json.dumps({"parameter": "FireRating", "value": "60"}), ids[("door_no_mark", "d1")]))
    with pytest.raises(ValueError, match="conflict"):
        draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_mark", "d1")]])


def test_same_fix_twice_makes_one_action(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET fix_json=? WHERE id=?",
        (json.dumps({"parameter": "FireRating", "value": "30"}), ids[("door_no_mark", "d1")]))
    out = draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_mark", "d1")]])
    assert len(out["actions"]) == 1 and len(out["skipped"]) == 1
    assert "same" in out["skipped"][0]["reason"]


def test_corrupt_stored_fix_is_not_guessed(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET fix_json='{oops' WHERE id=?", (ids[("door_no_rating", "d1")],))
    sql(env, "UPDATE issues SET fix_json=? WHERE id=?", (json.dumps({"parameter": "P"}), ids[("door_no_rating", "d2")]))
    with pytest.raises(ValueError, match="No selected finding has a fix"):
        draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_rating", "d2")]])


def test_findings_without_element_are_skipped(env):
    snapshot(env)
    _, ids = check(env)
    sql(env, "UPDATE issues SET element_uid=NULL WHERE id=?", (ids[("door_no_rating", "d1")],))
    out = draft(env, [ids[("door_no_rating", "d1")], ids[("door_no_rating", "d2")]])
    assert len(out["actions"]) == 1 and "no element" in out["skipped"][0]["reason"]


def test_draft_writes_nothing(env):
    snapshot(env)
    _, ids = check(env)
    before = sorted(str(p) for p in env.rglob("*") if p.is_file())
    snap_before = (env / "snapshots" / "s1.json").read_bytes()
    draft(env, [ids[("door_no_rating", "d1")]])
    assert sorted(str(p) for p in env.rglob("*") if p.is_file()) == before
    assert (env / "snapshots" / "s1.json").read_bytes() == snap_before


def test_old_database_without_fix_column_migrates(env):
    conn = sqlite3.connect(str(env / "qaqc_issues.db"))
    conn.execute("""CREATE TABLE issues (id TEXT PRIMARY KEY, doc_guid TEXT NOT NULL,
        rule_pack TEXT NOT NULL DEFAULT 'core', rule_id TEXT NOT NULL, severity TEXT NOT NULL, element_uid TEXT,
        label TEXT, message TEXT NOT NULL, fix_template TEXT, status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, snapshot_id TEXT, last_seen_at TEXT)""")
    conn.commit()
    conn.close()
    snapshot(env)
    _, ids = check(env)
    assert len(draft(env, [ids[("door_no_rating", "d1")]])["actions"]) == 1


def test_mock_mode_without_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_REVIT_MODE", "mock")
    (tmp_path / "rule_packs").mkdir()
    rule = {"id": "door_set_fire", "severity": "info", "description": "Door fire rating check.",
            "filter": {"category": "OST_Doors"}, "fix": {"parameter": "FireRating", "value": "60"}}
    (tmp_path / "rule_packs" / "m.yaml").write_text(yaml.safe_dump({"rules": [rule]}), encoding="utf-8")
    Mod().run_check(rule_pack="m", workspace=WS(tmp_path))
    issues = Mod().list_issues(workspace=WS(tmp_path))["issues"]
    assert issues
    out = Mod().draft_fix_plan(issue_ids=[issues[0]["id"]], workspace=WS(tmp_path))
    assert out["requires_approval"] is True and out["actions"][0]["arguments"]["value"] == "60"


def test_command_is_not_mutating_and_registered():
    path = Path(revit_mcp_server.__file__).parent / "modules" / "qaqc_checker" / "module.json"
    cmd = next(c for c in json.loads(path.read_text(encoding="utf-8"))["commands"] if c["id"] == "draft_fix_plan")
    assert cmd["is_mutating"] is False
    assert cmd["input_schema"]["required"] == ["issue_ids"]
